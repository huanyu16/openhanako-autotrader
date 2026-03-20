"""Oula Trading - Risk Guard MCP Server (B) — 风控守卫

所有交易必须先通过风控检查。
提供：交易前置风控、审计日志、紧急熔断、止损监控、标的白名单。

工具清单：
  - risk_check               核心工具：交易前置风控检查
  - set_risk_profile         切换风控模板
  - get_risk_profile         查看当前风控配置
  - emergency_stop           紧急熔断：撤单+暂停交易
  - resume_trading           恢复交易
  - check_stop_loss          止损监控：检查所有持仓
  - set_universe             设置交易标的白名单
  - get_audit_log            查询审计日志
  - get_position_risk_summary 持仓风险概览
"""

import json
import sqlite3
from datetime import datetime, date
from typing import Optional

try:
    from mcp.server.fastmcp import FastMCP
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

from shared.config import CONFIG_DIR, DATA_DIR, load_risk_profiles

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

AUDIT_DB = str(DATA_DIR / "audit.db")
UNIVERSE_FILE = str(CONFIG_DIR / "universe.json")

# 风控状态
_trading_paused = {}  # {user_id: bool}

def _init_db():
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user_id TEXT DEFAULT 'default',
            symbol TEXT,
            action TEXT,
            quantity REAL,
            price REAL,
            order_value REAL,
            approved INTEGER,
            reasons TEXT,
            risk_profile TEXT DEFAULT '达瓦斯模式'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_pnl (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            user_id TEXT DEFAULT 'default',
            realized_pl REAL DEFAULT 0,
            unrealized_pl REAL DEFAULT 0,
            total_loss_pct REAL DEFAULT 0,
            UNIQUE(date, user_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS risk_state (
            user_id TEXT PRIMARY KEY,
            profile TEXT DEFAULT '达瓦斯模式',
            trading_paused INTEGER DEFAULT 0,
            paused_reason TEXT
        )
    """)
    conn.commit()
    conn.close()

_init_db()

# ---------------------------------------------------------------------------
# Profile Helpers
# ---------------------------------------------------------------------------

def _get_profile_name(name: str) -> str:
    """支持中英文 key 映射"""
    mapping = {
        "conservative": "保守模式",
        "moderate": "达瓦斯模式",
        "aggressive": "利弗莫尔模式",
        "tournament": "比赛模式",
        "保守模式": "保守模式",
        "达瓦斯模式": "达瓦斯模式",
        "利弗莫尔模式": "利弗莫尔模式",
        "比赛模式": "比赛模式",
    }
    return mapping.get(name, "达瓦斯模式")

def _load_profile(profile_name: str = "达瓦斯模式") -> dict:
    profiles = load_risk_profiles()
    key = _get_profile_name(profile_name)
    return profiles.get(key, profiles.get("达瓦斯模式", {
        "max_single_order_pct": 15,
        "max_single_position_pct": 25,
        "max_total_position_pct": 70,
        "stop_loss_pct": 5,
        "max_daily_loss_pct": 5,
        "allow_short": False,
        "max_leverage": 1.0
    }))

def _get_user_profile(user_id: str = "default") -> str:
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute("SELECT profile FROM risk_state WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else "达瓦斯模式"

def _is_paused(user_id: str = "default") -> tuple:
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute(
        "SELECT trading_paused, paused_reason FROM risk_state WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    if row and row[0]:
        return True, row[1]
    return False, None

def _get_daily_loss(user_id: str = "default") -> float:
    today = date.today().isoformat()
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute(
        "SELECT total_loss_pct FROM daily_pnl WHERE date=? AND user_id=?",
        (today, user_id)
    ).fetchone()
    conn.close()
    return row[0] if row else 0.0

def _get_orders_last_minute(user_id: str = "default") -> int:
    cutoff = (datetime.now().timestamp() - 60)
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE user_id=? AND timestamp>? AND approved=1",
        (user_id, datetime.fromtimestamp(cutoff).isoformat())
    ).fetchone()
    conn.close()
    return row[0]

def _get_universe(user_id: str = "default") -> Optional[list]:
    try:
        with open(UNIVERSE_FILE) as f:
            data = json.load(f)
            return data.get(user_id)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def _record_audit(user_id, symbol, action, quantity, price, approved, reasons, profile):
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute(
        "INSERT INTO audit_log (timestamp,user_id,symbol,action,quantity,price,order_value,approved,reasons,risk_profile) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(), user_id, symbol, action, quantity, price,
         quantity * price, 1 if approved else 0, json.dumps(reasons, ensure_ascii=False), profile)
    )
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Core Risk Check
# ---------------------------------------------------------------------------

def run_risk_check(
    symbol: str, action: str, quantity: int, price: float,
    account_value: float,
    current_position_value: float = 0,
    total_position_value: float = 0,
    user_id: str = "default",
    profile_name: str = ""
) -> dict:
    """核心风控检查"""
    if not profile_name:
        profile_name = _get_user_profile(user_id)
    profile = _load_profile(profile_name)
    checks = []
    order_value = quantity * price

    # 0. 交易暂停检查
    paused, reason = _is_paused(user_id)
    if paused:
        checks.append(f"🚫 交易已暂停: {reason}")
        _record_audit(user_id, symbol, action, quantity, price, False, checks, profile_name)
        return {
            "approved": False,
            "reasons": checks,
            "risk_profile": profile_name,
            "order_value": order_value,
            "trading_paused": True
        }

    # 1. 白名单检查
    universe = _get_universe(user_id)
    if universe is not None and symbol.upper() not in [s.upper() for s in universe]:
        checks.append(f"❌ {symbol} 不在交易白名单中")

    # 2. 做空限制
    if action.lower() == "sell" and not profile.get("allow_short", False):
        checks.append(f"❌ 当前风控档位 [{profile_name}] 不允许做空")

    # 3. 单笔金额限制
    max_single = account_value * profile["max_single_order_pct"] / 100
    if order_value > max_single:
        checks.append(
            f"❌ 单笔金额 ${order_value:,.0f} 超过上限 ${max_single:,.0f} "
            f"(账户 {profile['max_single_order_pct']}%)"
        )

    # 4. 单标的仓位上限
    new_position = current_position_value + (order_value if action.lower() == "buy" else -order_value)
    max_position = account_value * profile["max_single_position_pct"] / 100
    if new_position > max_position:
        checks.append(
            f"❌ {symbol} 仓位 ${new_position:,.0f} 将超过上限 ${max_position:,.0f} "
            f"(账户 {profile['max_single_position_pct']}%)"
        )

    # 5. 总仓位上限
    new_total = total_position_value + (order_value if action.lower() == "buy" else 0)
    max_total = account_value * profile["max_total_position_pct"] / 100
    if new_total > max_total:
        checks.append(
            f"❌ 总仓位 ${new_total:,.0f} 将超过上限 ${max_total:,.0f} "
            f"(账户 {profile['max_total_position_pct']}%)"
        )

    # 6. 日内亏损限制
    daily_loss = _get_daily_loss(user_id)
    if daily_loss >= profile["max_daily_loss_pct"]:
        checks.append(
            f"❌ 今日亏损 {daily_loss:.1f}% 已达上限 {profile['max_daily_loss_pct']}%，交易暂停"
        )

    # 7. 交易频率限制
    orders_recent = _get_orders_last_minute(user_id)
    if orders_recent >= 10:
        checks.append(
            f"❌ 最近一分钟已下 {orders_recent} 单，超过频率限制 (10单/分钟)"
        )

    approved = len(checks) == 0
    _record_audit(user_id, symbol, action, quantity, price, approved, checks, profile_name)

    return {
        "approved": approved,
        "reasons": checks if checks else ["✅ 风控检查通过"],
        "risk_profile": profile_name,
        "order_value": order_value,
        "daily_loss_pct": daily_loss,
        "orders_last_minute": orders_recent,
        "trading_paused": False
    }

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def create_server():
    mcp = FastMCP("risk-guard")

    @mcp.tool()
    def risk_check(
        symbol: str, action: str, quantity: int, price: float,
        account_value: float,
        current_position_value: float = 0,
        total_position_value: float = 0,
        user_id: str = "default"
    ) -> dict:
        """核心工具：交易前置风控检查。每次交易必须先调用此工具，不通过则不得下单。

        Args:
            symbol: 股票代码
            action: 交易方向 (buy/sell)
            quantity: 数量
            price: 价格
            account_value: 账户总资产
            current_position_value: 当前该标的持仓市值
            total_position_value: 当前总持仓市值
            user_id: 用户ID
        """
        return run_risk_check(
            symbol, action, quantity, price, account_value,
            current_position_value, total_position_value, user_id
        )

    @mcp.tool()
    def set_risk_profile(profile_name: str, user_id: str = "default") -> dict:
        """切换风控模板。可选：保守模式、达瓦斯模式、利弗莫尔模式、比赛模式。

        Args:
            profile_name: 风控模板名称
            user_id: 用户ID
        """
        resolved = _get_profile_name(profile_name)
        profiles = load_risk_profiles()
        if resolved not in profiles:
            available = list(profiles.keys())
            return {"success": False, "error": f"未知模板: {profile_name}", "available": available}

        conn = sqlite3.connect(AUDIT_DB)
        conn.execute("""
            INSERT INTO risk_state (user_id, profile, trading_paused) VALUES (?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET profile=excluded.profile
        """, (user_id, resolved))
        conn.commit()
        conn.close()

        return {
            "success": True,
            "user_id": user_id,
            "previous_profile": _get_user_profile(user_id),
            "current_profile": resolved,
            "limits": profiles[resolved],
            "message": f"风控模板已切换为 [{resolved}]"
        }

    @mcp.tool()
    def get_risk_profile(user_id: str = "default") -> dict:
        """查看当前风控配置。

        Args:
            user_id: 用户ID
        """
        profile_name = _get_user_profile(user_id)
        profile = _load_profile(profile_name)
        paused, reason = _is_paused(user_id)
        profiles = load_risk_profiles()
        return {
            "current_profile": profile_name,
            "limits": profile,
            "trading_paused": paused,
            "paused_reason": reason,
            "daily_loss_pct": _get_daily_loss(user_id),
            "available_profiles": list(profiles.keys())
        }

    @mcp.tool()
    def emergency_stop(user_id: str = "default") -> dict:
        """紧急熔断：撤销所有挂单 + 暂停交易。
        触发后所有交易请求将被拒绝，直到调用 resume_trading() 恢复。

        Args:
            user_id: 用户ID
        """
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute("""
            INSERT INTO risk_state (user_id, profile, trading_paused, paused_reason) VALUES (?, ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET trading_paused=1, paused_reason=excluded.paused_reason
        """, (user_id, _get_user_profile(user_id), "用户手动触发紧急熔断"))
        conn.execute(
            "INSERT INTO audit_log (timestamp,user_id,symbol,action,quantity,price,order_value,approved,reasons,risk_profile) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(), user_id, "ALL", "EMERGENCY_STOP", 0, 0, 0, 0,
             json.dumps(["🚨 紧急熔断触发"], ensure_ascii=False), _get_user_profile(user_id))
        )
        conn.commit()
        conn.close()
        return {
            "success": True,
            "message": f"🚨 紧急熔断已触发 (user: {user_id})",
            "action_required": "请立即调用 alpaca-trade.cancel_all_orders() 撤销所有挂单"
        }

    @mcp.tool()
    def resume_trading(user_id: str = "default") -> dict:
        """恢复交易：解除熔断状态，恢复正常交易。

        Args:
            user_id: 用户ID
        """
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute("""
            INSERT INTO risk_state (user_id, profile, trading_paused, paused_reason) VALUES (?, ?, 0, NULL)
            ON CONFLICT(user_id) DO UPDATE SET trading_paused=0, paused_reason=NULL
        """, (user_id, _get_user_profile(user_id)))
        conn.execute(
            "INSERT INTO audit_log (timestamp,user_id,symbol,action,quantity,price,order_value,approved,reasons,risk_profile) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(), user_id, "ALL", "RESUME_TRADING", 0, 0, 0, 1,
             json.dumps(["✅ 交易已恢复"], ensure_ascii=False), _get_user_profile(user_id))
        )
        conn.commit()
        conn.close()
        return {
            "success": True,
            "message": f"✅ 交易已恢复 (user: {user_id})"
        }

    @mcp.tool()
    def check_stop_loss(user_id: str = "default") -> dict:
        """止损监控：检查所有持仓是否触发止损线。
        需要调用 Alpaca API 获取实时持仓数据。

        Args:
            user_id: 用户ID
        """
        try:
            from shared.alpaca_client import AlpacaClient
            client = AlpacaClient()
            positions = client.get_positions()
            profile = _load_profile(_get_user_profile(user_id))
            stop_loss_pct = profile.get("stop_loss_pct", 5)

            alerts = []
            for p in positions:
                pl_pct = p["unrealized_plpc"]
                if pl_pct <= -stop_loss_pct:
                    alerts.append({
                        "symbol": p["symbol"],
                        "qty": p["qty"],
                        "unrealized_pl": round(p["unrealized_pl"], 2),
                        "unrealized_plpc": round(pl_pct, 2),
                        "stop_loss_line": -stop_loss_pct,
                        "action": "建议立即卖出止损" if pl_pct <= -stop_loss_pct else "监控中"
                    })

            return {
                "total_positions": len(positions),
                "stop_loss_line": f"-{stop_loss_pct}%",
                "triggered_count": len(alerts),
                "alerts": alerts,
                "message": f"检查 {len(positions)} 个持仓，{len(alerts)} 个触发止损线"
            }
        except Exception as e:
            return {"error": f"止损检查失败: {str(e)}"}

    @mcp.tool()
    def set_universe(symbols: str, user_id: str = "default") -> dict:
        """设置交易标的白名单。只有白名单中的标的才能交易。
        传入空字符串则清除白名单（允许所有标的）。

        Args:
            symbols: 逗号分隔的标的代码 (如 "AAPL,TSLA,NVDA,GOOG")，空字符串清除
            user_id: 用户ID
        """
        data = {}
        try:
            with open(UNIVERSE_FILE) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        if symbols.strip():
            data[user_id] = [s.strip().upper() for s in symbols.split(",")]
            msg = f"白名单已设置: {data[user_id]}"
        else:
            data.pop(user_id, None)
            msg = "白名单已清除，允许交易所有标的"

        with open(UNIVERSE_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return {"success": True, "user_id": user_id, "universe": data.get(user_id), "message": msg}

    @mcp.tool()
    def get_audit_log(user_id: str = "default", limit: int = 20) -> list:
        """查询审计日志。

        Args:
            user_id: 用户ID
            limit: 返回条数
        """
        conn = sqlite3.connect(AUDIT_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @mcp.tool()
    def get_position_risk_summary(user_id: str = "default") -> dict:
        """持仓风险概览：汇总当前持仓的风控状态。

        Args:
            user_id: 用户ID
        """
        try:
            from shared.alpaca_client import AlpacaClient
            client = AlpacaClient()
            account = client.get_account()
            positions = client.get_positions()
            profile = _load_profile(_get_user_profile(user_id))

            total_mv = sum(p["market_value"] for p in positions)
            total_pl = sum(p["unrealized_pl"] for p in positions)

            # 单标的集中度
            concentration = []
            for p in positions:
                pct = p["market_value"] / account["portfolio_value"] * 100 if account["portfolio_value"] > 0 else 0
                concentration.append({
                    "symbol": p["symbol"],
                    "market_value": p["market_value"],
                    "weight_pct": round(pct, 2),
                    "over_limit": pct > profile["max_single_position_pct"]
                })

            return {
                "profile": _get_user_profile(user_id),
                "account_value": account["portfolio_value"],
                "total_position_pct": round(total_mv / account["portfolio_value"] * 100, 2) if account["portfolio_value"] > 0 else 0,
                "total_position_limit": f"{profile['max_total_position_pct']}%",
                "total_unrealized_pl": round(total_pl, 2),
                "daily_loss_pct": _get_daily_loss(user_id),
                "daily_loss_limit": f"{profile['max_daily_loss_pct']}%",
                "trading_paused": _is_paused(user_id)[0],
                "positions": concentration,
                "over_limit_count": len([c for c in concentration if c["over_limit"]])
            }
        except Exception as e:
            return {"error": f"获取风险概览失败: {str(e)}"}

    return mcp


if __name__ == "__main__":
    if not HAS_MCP:
        print("请先安装: pip install mcp")
        exit(1)
    server = create_server()
    server.run(transport="stdio")
