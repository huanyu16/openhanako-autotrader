"""Oula Trading - Scheduler MCP Server (D) — 定时任务调度

提供交易自动化调度能力：创建定时任务、管理任务、生成交易报告。
典型场景：开盘前扫描 → 开盘执行 → 午间检查 → 收盘报告。
"""

import json
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

try:
    from mcp.server.fastmcp import FastMCP
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

from shared.config import DATA_DIR
from shared.alpaca_client import AlpacaClient

# ---------------------------------------------------------------------------
# Schedule Database
# ---------------------------------------------------------------------------

SCHEDULE_DB = str(DATA_DIR / "schedules.db")

def _init_db():
    conn = sqlite3.connect(SCHEDULE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            cron_expr TEXT,
            trigger_time TEXT,
            action TEXT NOT NULL,
            params TEXT,
            enabled INTEGER DEFAULT 1,
            created_at TEXT,
            last_run TEXT,
            next_run TEXT,
            run_count INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            report_type TEXT,
            content TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

_init_db()

# ---------------------------------------------------------------------------
# Preset Schedules
# ---------------------------------------------------------------------------

PRESET_SCHEDULES = [
    {
        "name": "开盘前扫描 (Pre-Market Scan)",
        "cron": "30 13 * * 1-5",  # 09:30 ET = 13:30 IST (approx, depends on DST)
        "action": "pre_market_scan",
        "description": "检查隔夜新闻、盘前数据、自选股状态"
    },
    {
        "name": "开盘执行 (Market Open)",
        "cron": "30 14 * * 1-5",  # 09:30 ET
        "action": "market_open_execute",
        "description": "执行策略信号，下单交易"
    },
    {
        "name": "午间检查 (Midday Check)",
        "cron": "0 18 * * 1-5",  # 12:00 ET
        "action": "midday_review",
        "description": "评估持仓，调整止损，检查盈亏"
    },
    {
        "name": "收盘前处理 (Pre-Close)",
        "cron": "0 21 * * 1-5",  # 15:00 ET
        "action": "pre_close_review",
        "description": "评估日结，决定是否平仓"
    },
    {
        "name": "收盘报告 (Close Report)",
        "cron": "0 22 * * 1-5",  # 16:00 ET
        "action": "daily_report",
        "description": "生成当日交易报告，更新 PnL"
    },
]

# ---------------------------------------------------------------------------
# Report Generator
# ---------------------------------------------------------------------------

def _generate_daily_report() -> dict:
    """生成每日交易报告"""
    try:
        client = AlpacaClient()
        account = client.get_account()
        positions = client.get_positions()
        orders = client.get_orders(status="all")

        total_unrealized = sum(p["unrealized_pl"] for p in positions)
        total_market_value = sum(p["market_value"] for p in positions)

        position_details = []
        for p in positions:
            pl_pct = p["unrealized_plpc"]
            emoji = "🟢" if pl_pct >= 0 else "🔴"
            position_details.append({
                "symbol": p["symbol"],
                "qty": p["qty"],
                "avg_cost": p["avg_entry_price"],
                "current": p["current_price"],
                "market_value": p["market_value"],
                "pl": round(p["unrealized_pl"], 2),
                "pl_pct": round(pl_pct, 2),
                "status": f"{emoji} {'盈利' if pl_pct >= 0 else '亏损'}"
            })

        report = {
            "date": date.today().isoformat(),
            "account": {
                "cash": round(account["cash"], 2),
                "buying_power": round(account["buying_power"], 2),
                "portfolio_value": round(account["portfolio_value"], 2),
                "equity": round(account["equity"], 2),
                "paper": account["paper"]
            },
            "positions": position_details,
            "total_positions": len(positions),
            "total_market_value": round(total_market_value, 2),
            "total_unrealized_pl": round(total_unrealized, 2),
            "orders_today": len([o for o in orders]),
            "generated_at": datetime.now().isoformat()
        }

        # 存入数据库
        conn = sqlite3.connect(SCHEDULE_DB)
        conn.execute(
            "INSERT INTO trade_reports (date, report_type, content, created_at) VALUES (?,?,?,?)",
            (report["date"], "daily", json.dumps(report, ensure_ascii=False), datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

        return report

    except Exception as e:
        return {"error": f"生成报告失败: {str(e)}"}


# ---------------------------------------------------------------------------
# MCP Server Definition
# ---------------------------------------------------------------------------

def create_server():
    mcp = FastMCP("scheduler")

    @mcp.tool()
    def create_schedule(
        name: str,
        cron_expr: str,
        action: str,
        params: str = "{}"
    ) -> dict:
        """创建定时交易任务。
        
        Args:
            name: 任务名称
            cron_expr: Cron 表达式 (如 "30 14 * * 1-5" 表示工作日 14:30)
            action: 触发动作 (pre_market_scan/market_open_execute/midday_review/pre_close_review/daily_report/custom)
            params: 附加参数 (JSON 字符串)
        """
        conn = sqlite3.connect(SCHEDULE_DB)
        cursor = conn.execute(
            "INSERT INTO schedules (name, cron_expr, action, params, enabled, created_at) VALUES (?,?,?,?,1,?)",
            (name, cron_expr, action, params, datetime.now().isoformat())
        )
        conn.commit()
        schedule_id = cursor.lastrowid
        conn.close()

        return {
            "success": True,
            "id": schedule_id,
            "name": name,
            "cron": cron_expr,
            "action": action,
            "message": f"定时任务 [{name}] 已创建 (ID: {schedule_id})"
        }

    @mcp.tool()
    def list_schedules(show_disabled: bool = False) -> list:
        """查看所有定时任务。
        
        Args:
            show_disabled: 是否显示已禁用的任务
        """
        conn = sqlite3.connect(SCHEDULE_DB)
        conn.row_factory = sqlite3.Row
        if show_disabled:
            rows = conn.execute("SELECT * FROM schedules ORDER BY id").fetchall()
        else:
            rows = conn.execute("SELECT * FROM schedules WHERE enabled=1 ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @mcp.tool()
    def toggle_schedule(schedule_id: int) -> dict:
        """启用/暂停定时任务。
        
        Args:
            schedule_id: 任务ID
        """
        conn = sqlite3.connect(SCHEDULE_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM schedules WHERE id=?", (schedule_id,)).fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": f"任务 ID {schedule_id} 不存在"}

        new_state = 0 if row["enabled"] else 1
        conn.execute("UPDATE schedules SET enabled=? WHERE id=?", (new_state, schedule_id))
        conn.commit()
        conn.close()

        status = "启用" if new_state else "暂停"
        return {
            "success": True,
            "id": schedule_id,
            "name": row["name"],
            "status": status,
            "message": f"任务 [{row['name']}] 已{status}"
        }

    @mcp.tool()
    def setup_preset_schedules() -> dict:
        """一键配置推荐的定时交易任务（5个预设任务）。
        
        包括：开盘前扫描、开盘执行、午间检查、收盘前处理、收盘报告。
        """
        conn = sqlite3.connect(SCHEDULE_DB)
        created = []
        for preset in PRESET_SCHEDULES:
            try:
                cursor = conn.execute(
                    "INSERT INTO schedules (name, cron_expr, action, params, enabled, created_at) VALUES (?,?,?,?,1,?)",
                    (preset["name"], preset["cron"], preset["action"], "{}", datetime.now().isoformat())
                )
                created.append({
                    "id": cursor.lastrowid,
                    "name": preset["name"],
                    "cron": preset["cron"],
                    "description": preset["description"]
                })
            except sqlite3.IntegrityError:
                pass  # 已存在则跳过
        conn.commit()
        conn.close()

        return {
            "success": True,
            "created_count": len(created),
            "schedules": created,
            "message": f"已配置 {len(created)} 个预设定时任务"
        }

    @mcp.tool()
    def get_trade_report(report_date: str = "") -> dict:
        """获取交易报告（日报/周报）。
        
        Args:
            report_date: 日期 (如 "2026-03-20"，留空则生成今日报告)
        """
        target_date = report_date if report_date else date.today().isoformat()

        # 先尝试从数据库取
        conn = sqlite3.connect(SCHEDULE_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM trade_reports WHERE date=? ORDER BY id DESC LIMIT 1",
            (target_date,)
        ).fetchone()
        conn.close()

        if row:
            return {"date": target_date, "cached": True, "report": json.loads(row["content"])}

        # 没有缓存，实时生成
        return _generate_daily_report()

    @mcp.tool()
    def remove_schedule(schedule_id: int) -> dict:
        """删除定时任务。
        
        Args:
            schedule_id: 任务ID
        """
        conn = sqlite3.connect(SCHEDULE_DB)
        cursor = conn.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
        conn.commit()
        deleted = cursor.rowcount
        conn.close()

        if deleted:
            return {"success": True, "message": f"任务 ID {schedule_id} 已删除"}
        return {"success": False, "error": f"任务 ID {schedule_id} 不存在"}

    return mcp


if __name__ == "__main__":
    if not HAS_MCP:
        print("请先安装: pip install mcp")
        exit(1)
    server = create_server()
    server.run(transport="stdio")
