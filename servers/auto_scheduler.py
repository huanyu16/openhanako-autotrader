"""Oula Trading - Auto Scheduler MCP Server (D) — 定时调度器

管理自动化交易计划。
提供：预设调度任务、日报生成、信号缓存、任务模板。

工具清单：
  - setup_default_tasks        一键配置所有默认调度任务
  - create_task                创建自定义定时任务
  - list_tasks                 查看所有任务
  - toggle_task                启用/暂停任务
  - delete_task                删除任务
  - get_latest_signals         查看最新交易信号
  - get_daily_report           查看每日交易报告
  - generate_daily_report      手动生成今日报告
  - get_builtin_task_templates 查看内置任务模板
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
# Database
# ---------------------------------------------------------------------------

SCHEDULE_DB = str(DATA_DIR / "scheduler.db")
SIGNALS_FILE = str(DATA_DIR / "latest_signals.json")

def _init_db():
    conn = sqlite3.connect(SCHEDULE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            cron_expr TEXT,
            trigger_time TEXT,
            action TEXT NOT NULL,
            params TEXT,
            description TEXT,
            enabled INTEGER DEFAULT 1,
            created_at TEXT,
            last_run TEXT,
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
# Builtin Task Templates
# ---------------------------------------------------------------------------

BUILTIN_TEMPLATES = [
    {
        "name": "开盘前扫描",
        "cron": "30 13 * * 1-5",
        "action": "pre_market_scan",
        "description": "检查隔夜新闻、盘前数据、自选股状态",
        "params": {}
    },
    {
        "name": "开盘执行",
        "cron": "30 14 * * 1-5",
        "action": "market_open_execute",
        "description": "执行策略信号，对高置信度标的下单",
        "params": {}
    },
    {
        "name": "午间检查",
        "cron": "0 18 * * 1-5",
        "action": "midday_review",
        "description": "评估持仓，调整止损，检查盈亏",
        "params": {}
    },
    {
        "name": "收盘前处理",
        "cron": "0 21 * * 1-5",
        "action": "pre_close_review",
        "description": "评估日结，决定是否平仓",
        "params": {}
    },
    {
        "name": "收盘报告",
        "cron": "0 22 * * 1-5",
        "action": "daily_report",
        "description": "生成当日交易报告，更新 PnL，记录信号",
        "params": {}
    },
    {
        "name": "止损监控",
        "cron": "*/5 14-21 * * 1-5",
        "action": "stop_loss_check",
        "description": "每5分钟检查一次持仓止损线",
        "params": {}
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
            "orders_today": len(orders),
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

def _cache_signals(signals: list):
    """缓存最新信号到文件"""
    with open(SIGNALS_FILE, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "signals": signals
        }, f, ensure_ascii=False, indent=2)

def _load_cached_signals() -> Optional[dict]:
    """读取缓存的信号"""
    try:
        with open(SIGNALS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def create_server():
    mcp = FastMCP("auto-scheduler")

    @mcp.tool()
    def setup_default_tasks() -> dict:
        """一键配置所有默认调度任务（6个预设任务）。
        包括：开盘前扫描、开盘执行、午间检查、收盘前处理、收盘报告、止损监控。
        """
        conn = sqlite3.connect(SCHEDULE_DB)
        created = []
        skipped = []

        for template in BUILTIN_TEMPLATES:
            # 检查是否已存在同名任务
            existing = conn.execute(
                "SELECT id FROM tasks WHERE name=?", (template["name"],)
            ).fetchone()
            if existing:
                skipped.append(template["name"])
                continue

            cursor = conn.execute(
                "INSERT INTO tasks (name, cron_expr, action, params, description, enabled, created_at) VALUES (?,?,?,?,?,1,?)",
                (template["name"], template["cron"], template["action"],
                 json.dumps(template["params"], ensure_ascii=False),
                 template["description"], datetime.now().isoformat())
            )
            created.append({
                "id": cursor.lastrowid,
                "name": template["name"],
                "cron": template["cron"],
                "description": template["description"]
            })

        conn.commit()
        conn.close()

        return {
            "success": True,
            "created_count": len(created),
            "skipped_count": len(skipped),
            "created": created,
            "skipped": skipped,
            "message": f"已配置 {len(created)} 个任务，跳过 {len(skipped)} 个已存在任务"
        }

    @mcp.tool()
    def create_task(
        name: str,
        cron_expr: str,
        action: str,
        description: str = "",
        params: str = "{}"
    ) -> dict:
        """创建自定义定时任务。

        Args:
            name: 任务名称
            cron_expr: Cron 表达式 (如 "30 14 * * 1-5" 表示工作日 14:30)
            action: 触发动作
            description: 任务描述
            params: 附加参数 (JSON 字符串)
        """
        conn = sqlite3.connect(SCHEDULE_DB)
        cursor = conn.execute(
            "INSERT INTO tasks (name, cron_expr, action, params, description, enabled, created_at) VALUES (?,?,?,?,?,1,?)",
            (name, cron_expr, action, params, description, datetime.now().isoformat())
        )
        conn.commit()
        task_id = cursor.lastrowid
        conn.close()

        return {
            "success": True,
            "id": task_id,
            "name": name,
            "cron": cron_expr,
            "action": action,
            "message": f"任务 [{name}] 已创建 (ID: {task_id})"
        }

    @mcp.tool()
    def list_tasks(show_disabled: bool = False) -> list:
        """查看所有任务。

        Args:
            show_disabled: 是否显示已禁用的任务
        """
        conn = sqlite3.connect(SCHEDULE_DB)
        conn.row_factory = sqlite3.Row
        if show_disabled:
            rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        else:
            rows = conn.execute("SELECT * FROM tasks WHERE enabled=1 ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @mcp.tool()
    def toggle_task(task_id: int) -> dict:
        """启用/暂停任务。

        Args:
            task_id: 任务ID
        """
        conn = sqlite3.connect(SCHEDULE_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": f"任务 ID {task_id} 不存在"}

        new_state = 0 if row["enabled"] else 1
        conn.execute("UPDATE tasks SET enabled=? WHERE id=?", (new_state, task_id))
        conn.commit()
        conn.close()

        status = "启用" if new_state else "暂停"
        return {
            "success": True,
            "id": task_id,
            "name": row["name"],
            "status": status,
            "message": f"任务 [{row['name']}] 已{status}"
        }

    @mcp.tool()
    def delete_task(task_id: int) -> dict:
        """删除任务。

        Args:
            task_id: 任务ID
        """
        conn = sqlite3.connect(SCHEDULE_DB)
        cursor = conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
        deleted = cursor.rowcount
        conn.close()

        if deleted:
            return {"success": True, "message": f"任务 ID {task_id} 已删除"}
        return {"success": False, "error": f"任务 ID {task_id} 不存在"}

    @mcp.tool()
    def get_latest_signals() -> dict:
        """查看最新交易信号。返回最近一次扫描缓存的所有信号结果。
        """
        cached = _load_cached_signals()
        if cached:
            return cached
        return {
            "updated_at": None,
            "signals": [],
            "message": "暂无缓存的信号数据。请先运行 full_analysis 或 market_scan。"
        }

    @mcp.tool()
    def get_daily_report(report_date: str = "") -> dict:
        """查看每日交易报告。

        Args:
            report_date: 日期 (如 "2026-03-20"，留空则查今日)
        """
        target_date = report_date if report_date else date.today().isoformat()

        conn = sqlite3.connect(SCHEDULE_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM trade_reports WHERE date=? ORDER BY id DESC LIMIT 1",
            (target_date,)
        ).fetchone()
        conn.close()

        if row:
            return {"date": target_date, "cached": True, "report": json.loads(row["content"])}

        return {"date": target_date, "cached": False, "message": f"没有 {target_date} 的报告"}

    @mcp.tool()
    def generate_daily_report() -> dict:
        """手动生成今日交易报告。实时调用 Alpaca API 获取最新数据。
        """
        return _generate_daily_report()

    @mcp.tool()
    def get_builtin_task_templates() -> dict:
        """查看内置任务模板。展示所有可用的预设调度任务。
        """
        return {
            "count": len(BUILTIN_TEMPLATES),
            "templates": BUILTIN_TEMPLATES,
            "message": "使用 setup_default_tasks 一键创建所有预设任务"
        }

    return mcp


if __name__ == "__main__":
    if not HAS_MCP:
        print("请先安装: pip install mcp")
        exit(1)
    server = create_server()
    server.run(transport="stdio")
