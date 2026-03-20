"""Oula Trading - Risk Guard MCP Server (B) — 风控守卫

所有交易请求必须先经过此 Server 的风控检查。
提供：交易前置风控、审计日志、紧急熔断、风控配置管理。
"""

import json
import sqlite3
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

try:
    from mcp.server.fastmcp import FastMCP
    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    print("WARNING: mcp not installed. Run: pip install mcp")

from shared.config import CONFIG_DIR, DATA_DIR, load_risk_profiles

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

AUDIT_DB = str(DATA_DIR / "audit.db")

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
            risk_profile TEXT DEFAULT 'moderate'
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
    conn.commit()
    conn.close()

_init_db()

# ---------------------------------------------------------------------------
# Risk Check Engine
# ---------------------------------------------------------------------------

def _load_profile(profile_name: str = "moderate") -> dict:
    profiles = load_risk_profiles()
    return profiles.get(profile_name, profiles.get("moderate", {
        "max_single_order_pct": 15,
        "max_single_position_pct": 25,
        "max_total_position_pct": 70,
        "stop_loss_pct": 5,
        "max_daily_loss_pct": 5,
        "allow_short": False,
        "max_leverage": 1.0
    }))

def _get_daily_loss(user_id: str = "default") -> float:
    """获取当日已记录的累计亏损百分比"""
    today = date.today().isoformat()
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute(
        "SELECT total_loss_pct FROM daily_pnl WHERE date=? AND user_id=?",
        (today, user_id)
    ).fetchone()
    conn.close()
    return row[0] if row else 0.0

def _get_orders_last_minute(user_id: str = "default") -> int:
    """获取最近一分钟内的下单次数"""
    cutoff = (datetime.now().timestamp() - 60)
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE user_id=? AND timestamp>? AND approved=1",
        (user_id, datetime.fromtimestamp(cutoff).isoformat())
    ).fetchone()
    conn.close()
    return row[0]

def _record_audit(user_id, symbol, action, quantity, price, approved, reasons, profile):
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute(
        "INSERT INTO audit_log (timestamp,user_id,symbol,action,quantity,price,order_value,approved,reasons,risk_profile) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(), user_id, symbol, action, quantity, price,
         quantity * price, 1 if approved else 0, json.dumps(reasons, ensure_ascii=False), profile)
    )
    conn.commit()
    conn.close()

def run_risk_check(
    symbol: str,
    action: str,
    quantity: int,
    price: float,
    account_value: float,
    current_position_value: float = 0,
    total_position_value: float = 0,
    user_id: str = "default",
    profile_name: str = "moderate"
) -> dict:
    """核心风控检查函数"""
    profile = _load_profile(profile_name)
    checks = []
    order_value = quantity * price

    # 1. 做空限制
    if action.lower() == "sell" and not profile.get("allow_short", False):
        checks.append(f"❌ 当前风控档位 [{profile_name}] 不允许做空")

    # 2. 单笔金额限制
    max_single = account_value * profile["max_single_order_pct"] / 100
    if order_value > max_single:
        checks.append(
            f"❌ 单笔金额 ${order_value:,.0f} 超过上限 ${max_single:,.0f} "
            f"(账户 {profile['max_single_order_pct']}%)"
        )

    # 3. 单标的仓位上限
    new_position = current_position_value + (order_value if action.lower() == "buy" else -order_value)
    max_position = account_value * profile["max_single_position_pct"] / 100
    if new_position > max_position:
        checks.append(
            f"❌ {symbol} 仓位 ${new_position:,.0f} 将超过上限 ${max_position:,.0f} "
            f"(账户 {profile['max_single_position_pct']}%)"
        )

    # 4. 总仓位上限
    new_total = total_position_value + (order_value if action.lower() == "buy" else 0)
    max_total = account_value * profile["max_total_position_pct"] / 100
    if new_total > max_total:
        checks.append(
            f"❌ 总仓位 ${new_total:,.0f} 将超过上限 ${max_total:,.0f} "
            f"(账户 {profile['max_total_position_pct']}%)"
        )

    # 5. 日内亏损限制
    daily_loss = _get_daily_loss(user_id)
    if daily_loss >= profile["max_daily_loss_pct"]:
        checks.append(
            f"❌ 今日亏损 {daily_loss:.1f}% 已达上限 {profile['max_daily_loss_pct']}%，交易暂停"
        )

    # 6. 交易频率限制
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
        "orders_last_minute": orders_recent
    }

# ---------------------------------------------------------------------------
# MCP Server Definition
# ---------------------------------------------------------------------------

def create_server():
    mcp = FastMCP("risk-guard")

    @mcp.tool()
    def risk_check(
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        account_value: float,
        current_position_value: float = 0,
        total_position_value: float = 0,
        user_id: str = "default",
        profile_name: str = "moderate"
    ) -> dict:
        """交易前置风控检查。每次交易必须先调用此工具，不通过则不得下单。
        
        Args:
            symbol: 股票代码 (如 AAPL)
            action: 交易方向 (buy/sell)
            quantity: 数量
            price: 价格
            account_value: 账户总资产
            current_position_value: 当前该标的持仓市值
            total_position_value: 当前总持仓市值
            user_id: 用户ID
            profile_name: 风控档位 (conservative/moderate/aggressive/tournament)
        """
        return run_risk_check(
            symbol, action, quantity, price, account_value,
            current_position_value, total_position_value, user_id, profile_name
        )

    @mcp.tool()
    def emergency_stop(user_id: str = "default") -> dict:
        """紧急熔断：记录熔断事件，返回需要执行的撤单指令。
        
        Args:
            user_id: 用户ID
        """
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute(
            "INSERT INTO audit_log (timestamp,user_id,symbol,action,quantity,price,order_value,approved,reasons,risk_profile) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(), user_id, "ALL", "EMERGENCY_STOP", 0, 0, 0, 0,
             json.dumps(["🚨 紧急熔断触发"], ensure_ascii=False), "emergency")
        )
        conn.commit()
        conn.close()
        return {
            "success": True,
            "message": f"🚨 紧急熔断已触发 (user: {user_id})",
            "action_required": "请立即调用 alpaca-trade.cancel_all_orders() 撤销所有挂单"
        }

    @mcp.tool()
    def get_audit_log(user_id: str = "default", limit: int = 20) -> list:
        """查询操作审计日志。
        
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
    def get_risk_limits(profile_name: str = "moderate") -> dict:
        """获取指定风控档位的限制参数。
        
        Args:
            profile_name: 风控档位名称
        """
        profiles = load_risk_profiles()
        all_profiles = list(profiles.keys())
        profile = profiles.get(profile_name, profiles.get("moderate", {}))
        return {
            "current_profile": profile_name,
            "limits": profile,
            "available_profiles": all_profiles
        }

    @mcp.tool()
    def set_daily_pnl(user_id: str, realized_pl: float = 0, unrealized_pl: float = 0, account_value: float = 100000) -> dict:
        """更新当日盈亏记录（由 scheduler 在收盘后调用）。
        
        Args:
            user_id: 用户ID
            realized_pl: 已实现盈亏
            unrealized_pl: 未实现盈亏
            account_value: 当前账户总资产
        """
        today = date.today().isoformat()
        total_loss_pct = ((realized_pl + unrealized_pl) / account_value * 100) if account_value > 0 else 0
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute("""
            INSERT INTO daily_pnl (date, user_id, realized_pl, unrealized_pl, total_loss_pct)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date, user_id) DO UPDATE SET
                realized_pl=excluded.realized_pl,
                unrealized_pl=excluded.unrealized_pl,
                total_loss_pct=excluded.total_loss_pct
        """, (today, user_id, realized_pl, unrealized_pl, total_loss_pct))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "date": today,
            "realized_pl": realized_pl,
            "unrealized_pl": unrealized_pl,
            "total_loss_pct": round(total_loss_pct, 2)
        }

    return mcp


if __name__ == "__main__":
    if not HAS_MCP:
        print("请先安装: pip install mcp")
        exit(1)
    server = create_server()
    server.run(transport="stdio")
