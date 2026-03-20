# OpenHanako × Alpaca MCP 自动炒股系统 — 架构设计文档

> 版本：v1.0 | 日期：2026-03-20
> 基于 Alpaca 官方 MCP Server（[alpacahq/alpaca-mcp-server](https://github.com/alpacahq/alpaca-mcp-server)，565+ stars，活跃维护）

---

## 一、系统总览

### 1.1 目标

构建一套基于 OpenHanako Agent + Alpaca MCP 的自动化交易系统，支持：
- **股票**（美股）自动交易
- **期货**（Alpaca 支持期货）
- **加密货币**交易
- **期权**策略
- 自然语言驱动交易决策

### 1.2 核心约束

| 约束 | 说明 |
|------|------|
| 资金安全 | 必须有风控层，agent 不能直接裸调交易 API |
| 可审计 | 每笔操作必须有日志，支持事后追溯 |
| 多用户 | 系统给其他人用，需要支持多账户/多配置 |
| 合规 | Alpaca 本身是 SEC 注册券商，已解决基础合规 |
| 渐进上线 | 模拟盘 → 小资金实盘 → 正式实盘 |

---

## 二、架构全景图

```
┌─────────────────────────────────────────────────────────────┐
│                      用户层 (User Layer)                      │
│                                                              │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│   │  Web Dashboard│  │  OpenHanako   │  │  Mobile / CLI    │  │
│   │  (监控面板)   │  │  Chat (交互)  │  │  (命令行接口)     │  │
│   └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│          │                 │                    │            │
│          └────────────────┼────────────────────┘            │
└───────────────────────────┼─────────────────────────────────┘
                            │ 自然语言 / API
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Agent 层 (OpenHanako)                      │
│                                                              │
│   ┌────────────────────────────────────────────────────┐     │
│   │              LLM (决策引擎)                         │     │
│   │  - 市场分析 (行情解读、趋势判断)                     │     │
│   │  - 策略生成 (技术指标、信号识别)                     │     │
│   │  - 交易决策 (买/卖/持有/平仓)                       │     │
│   │  - 风险评估 (仓位建议、止损建议)                     │     │
│   └─────────────────────┬──────────────────────────────┘     │
│                         │                                    │
│   ┌─────────────────────▼──────────────────────────────┐     │
│   │           MCP Client (工具调用层)                    │     │
│   └────┬──────────┬──────────────┬──────────────┬─────┘     │
│        │          │              │              │           │
└────────┼──────────┼──────────────┼──────────────┼───────────┘
         │ MCP      │ MCP          │ MCP          │ MCP
         ▼          ▼              ▼              ▼
┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────────┐
│  MCP Server│ │  MCP Server│ │  MCP Server│ │   MCP Server   │
│  ┌──────┐  │ │  ┌──────┐  │ │  ┌──────┐  │ │   ┌────────┐  │
│  │Alpaca│  │ │  │风控  │  │ │  │策略  │  │ │   │定时任务 │  │
│  │Trade │  │ │  │Guard │  │ │  │引擎  │  │ │   │调度器   │  │
│  │交易  │  │ │  │拦截  │  │ │  │指标  │  │ │   │Cron     │  │
│  └──┬───┘  │ │  └──┬───┘  │ │  └──┬───┘  │ │   └───┬────┘  │
│     │      │ │     │      │ │     │      │ │       │       │
│     │      │ │     │      │ │     │      │ │       │       │
│  (A) 交易   │ │ (B) 风控  │ │ (C) 策略  │ │  (D) 调度     │
│  执行层     │ │  审计层   │ │  分析层   │ │  自动化层      │
└─────┼──────┘ └─────┼──────┘ └─────┼──────┘ └───────┼───────┘
      │              │              │               │
      └──────────────┼──────────────┘               │
                     ▼                              │
         ┌───────────────────────┐                  │
         │    Alpaca Trading API │◄─────────────────┘
         │  ┌─────────────────┐  │   (定时触发交易)
         │  │  股票/期货/期权 │  │
         │  │  加密货币       │  │
         │  │  市场数据       │  │
         │  └────────┬────────┘  │
         └───────────┼───────────┘
                     ▼
              ┌──────────────┐
              │   金融市场    │
              │  (US Markets) │
              └──────────────┘
```

---

## 三、四个 MCP Server 详细设计

### (A) Alpaca 交易 MCP Server — 官方版直接用

**来源**：[alpacahq/alpaca-mcp-server](https://github.com/alpacahq/alpaca-mcp-server)（官方，565 stars）

**已提供的能力**（无需自己写）：

| 工具类别 | 具体工具 | 说明 |
|---------|---------|------|
| **账户管理** | `get_account` | 查余额、购买力 |
| | `get_positions` | 查持仓 |
| | `get_position` | 单个持仓详情 |
| | `liquidate_position` | 清仓/部分平仓 |
| **下单** | `place_order` | 市价/限价/止损/追踪止损 |
| | `cancel_order` | 撤单 |
| | `cancel_all_orders` | 全部撤单 |
| | `get_orders` | 查订单历史 |
| **市场数据** | `get_quote` / `get_latest_trade` | 实时报价 |
| | `get_bars` / `get_snapshot` | K线/快照 |
| | `get_stock_history` | 历史数据 |
| **期权** | `search_options` / `get_option_quote` | 期权合约搜索/报价 |
| | `place_option_order` | 期权下单 |
| **加密货币** | `place_crypto_order` | 加密货币交易 |
| **市场状态** | `get_clock` / `get_calendar` | 开市时间/日历 |
| **资产搜索** | `search_assets` | 搜索股票/ETF/加密 |
| **自选股** | watchlist 相关工具 | 管理自选列表 |
| **公司行为** | `get_corporate_actions` | 分红/拆股/财报 |

**安装方式**：
```bash
uvx alpaca-mcp-server init
```

**OpenHanako MCP 配置**：
```json
{
  "mcpServers": {
    "alpaca-trade": {
      "command": "uvx",
      "args": ["alpaca-mcp-server", "serve"],
      "env": {
        "ALPACA_API_KEY": "<用户API_KEY>",
        "ALPACA_SECRET_KEY": "<用户SECRET_KEY>",
        "ALPACA_PAPER_TRADE": "true"
      }
    }
  }
}
```

---

### (B) 风控守卫 MCP Server — 需要自己写

**定位**：拦截 agent 的危险操作，强制执行风控规则

**核心工具设计**：

| 工具名 | 输入 | 输出 | 说明 |
|-------|------|------|------|
| `risk_check` | symbol, action, quantity, price | { approved: bool, reason: string } | 交易前置风控检查 |
| `get_risk_limits` | user_id | { max_position, max_loss, ... } | 获取用户风控配置 |
| `set_risk_limits` | user_id, limits | { success: bool } | 设置风控参数 |
| `get_audit_log` | user_id, date_range | [{timestamp, action, detail}] | 查询操作审计日志 |
| `emergency_stop` | user_id | { success: bool } | 紧急熔断，全部撤单+暂停交易 |

**风控规则引擎**：

```
风控检查流程（每次交易前触发）：

Agent 发起交易请求
        │
        ▼
┌─ 1. 单笔金额限制 ──────────────────────┐
│  超过单笔上限 → 拒绝 + 记录日志         │
└──────────────┬──────────────────────────┘
               │ 通过
┌─ 2. 日内累计损失限制 ───────────────────┐
│  当日亏损超阈值 → 拒绝 + 暂停交易        │
└──────────────┬──────────────────────────┘
               │ 通过
┌─ 3. 单标的仓位上限 ────────────────────┐
│  单个标的超总资产X% → 拒绝              │
└──────────────┬──────────────────────────┘
               │ 通过
┌─ 4. 总仓位上限 ────────────────────────┐
│  总持仓超总资产X% → 拒绝                 │
└──────────────┬──────────────────────────┘
               │ 通过
┌─ 5. 交易频率限制 ──────────────────────┐
│  单分钟内下单超过N次 → 拒绝（防滥用）    │
└──────────────┬──────────────────────────┘
               │ 通过
        ✅ 允许执行
```

**实现框架**：Python + FastMCP

```python
from mcp.server.fastmcp import FastMCP
import json
from datetime import datetime

mcp = FastMCP("risk-guard")

# 风控配置（实际项目中存数据库/Redis）
RISK_CONFIG = {
    "max_single_order_usd": 10000,      # 单笔最大金额
    "max_daily_loss_pct": 5,             # 日内最大亏损比例 (%)
    "max_single_position_pct": 20,       # 单标的最大仓位 (%)
    "max_total_position_pct": 80,        # 总仓位上限 (%)
    "max_orders_per_minute": 10,         # 每分钟最大下单次数
}

AUDIT_LOG = []  # 实际用 SQLite / 数据库

@mcp.tool()
def risk_check(symbol: str, action: str, quantity: int, 
               price: float, account_value: float) -> dict:
    """交易前置风控检查，所有交易必须先通过此检查"""
    
    order_value = quantity * price
    checks = []
    
    # 1. 单笔金额
    if order_value > RISK_CONFIG["max_single_order_usd"]:
        checks.append(f"❌ 单笔金额 ${order_value:.0f} 超过上限 ${RISK_CONFIG['max_single_order_usd']}")
    
    # 2. 日内亏损（简化示意，实际从 Alpaca API 获取当日盈亏）
    # ...
    
    # 3. 单标的仓位
    if order_value > account_value * RISK_CONFIG["max_single_position_pct"] / 100:
        checks.append(f"❌ 单标的仓位超过 {RISK_CONFIG['max_single_position_pct']}%")
    
    # 记录审计日志
    audit_entry = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "price": price,
        "approved": len(checks) == 0,
        "reasons": checks
    }
    AUDIT_LOG.append(audit_entry)
    
    return {
        "approved": len(checks) == 0,
        "reasons": checks if checks else ["✅ 风控检查通过"]
    }

@mcp.tool()
def emergency_stop() -> dict:
    """紧急熔断：撤销所有挂单 + 标记暂停交易"""
    # 实际实现调用 Alpaca cancel_all_orders
    return {"success": True, "message": "已执行紧急熔断"}

@mcp.tool()
def get_audit_log(limit: int = 20) -> list:
    """查询最近操作审计日志"""
    return AUDIT_LOG[-limit:]
```

---

### (C) 策略分析 MCP Server — 可选，增强 agent 能力

**定位**：提供技术指标计算、策略回测、信号识别能力

| 工具名 | 说明 |
|-------|------|
| `calculate_indicator` | 计算技术指标（MA/RSI/MACD/Bollinger/ATR） |
| `analyze_trend` | 趋势分析（上升/下降/盘整） |
| `scan_screener` | 市场扫描（按条件筛选标的） |
| `backtest_strategy` | 策略回测（历史数据模拟） |

> 💡 **初期可以不做这个 Server**，让 OpenHanako 的 LLM 直接分析 Alpaca MCP 提供的市场数据即可。等技术要求高了再加。

---

### (D) 定时任务调度 MCP Server — 自动化核心

**定位**：定时触发 agent 执行交易策略，无需人工介入

| 工具名 | 说明 |
|-------|------|
| `create_schedule` | 创建定时任务（开盘前分析、收盘检查等） |
| `list_schedules` | 查看所有定时任务 |
| `toggle_schedule` | 启用/暂停定时任务 |
| `get_trade_report` | 生成交易日报/周报 |

**典型调度场景**：

```
09:00 ET  → 开盘前扫描（检查隔夜新闻、盘前数据）
09:30 ET  → 开盘执行（执行策略信号）
12:00 ET  → 午间检查（评估持仓，调整止损）
15:30 ET  → 收盘前处理（评估日结，决定是否平仓）
16:00 ET  → 收盘报告（生成当日交易报告）
```

---

## 四、Agent 工作流设计

### 4.1 手动交易流（用户主动触发）

```
用户: "买入 100 股苹果，市价"
         │
         ▼
OpenHanako Agent 接收指令
         │
         ▼
[Step 1] 调用 alpaca-trade.get_account → 检查购买力
         │
         ▼
[Step 2] 调用 alpaca-trade.get_quote("AAPL") → 获取当前价格
         │
         ▼
[Step 3] 调用 risk-guard.risk_check → 风控检查
         │
    ┌────┴────┐
    │ 通过?   │
    ├─ YES ──→│
    │         ▼
    │   [Step 4] 调用 alpaca-trade.place_order → 执行下单
    │         │
    │         ▼
    │   [Step 5] 返回成交确认给用户
    │
    └─ NO ──→ 告知用户被风控拦截及原因
```

### 4.2 自动交易流（定时触发）

```
定时任务触发 (Cron)
         │
         ▼
OpenHanako Agent 被唤醒
         │
         ▼
[Step 1] 获取市场状态 → alpaca-trade.get_clock
         │
    ┌────┴────┐
    │ 市场开?  │
    ├─ NO ──→ 退出，等待下次触发
    │
    └─ YES ──→│
              ▼
    [Step 2] 获取持仓 → alpaca-trade.get_positions
              │
              ▼
    [Step 3] 获取自选股行情 → alpaca-trade.get_snapshot (批量)
              │
              ▼
    [Step 4] LLM 分析 → 判断买卖信号
              │
              ▼
    [Step 5] 对每个信号执行风控检查 → risk-guard.risk_check
              │
              ▼
    [Step 6] 通过风控的信号 → alpaca-trade.place_order
              │
              ▼
    [Step 7] 生成交易报告 → 存入审计日志
```

### 4.3 Agent System Prompt 要点

```
你是一个专业的自动交易 agent。你的职责是：

1. **执行交易指令**：用户说"买入/卖出"时，严格按流程执行
2. **风险第一**：每次交易前必须调用 risk_check，不通过不得下单
3. **信息透明**：每次交易前后都要告知用户关键信息（价格、金额、仓位占比）
4. **不猜测**：不知道就说不知道，不做没有数据支撑的判断
5. **遵守规则**：不在非交易时间下单，不做超出用户权限的操作

可用工具：
- alpaca-trade.* : 交易执行（下单/撤单/查持仓/查行情）
- risk-guard.*   : 风控检查（交易前置检查/审计日志/紧急熔断）
- scheduler.*    : 定时任务（创建/查看调度计划）

交易执行顺序：
get_account → get_quote → risk_check → place_order → 确认
```

---

## 五、部署架构

### 5.1 开发阶段（单机）

```
用户 Mac/PC
├── OpenHanako (MCP Client)
│   ├── alpaca-trade MCP Server (uvx 运行)
│   ├── risk-guard MCP Server (Python 进程)
│   └── scheduler MCP Server (Python 进程)
├── SQLite (审计日志 + 风控配置)
└── Alpaca Paper Trading API (模拟盘)
```

### 5.2 生产阶段（服务器）

```
┌─────────────────────────────────────┐
│           云服务器 (VPS)              │
│                                      │
│  ┌────────────────────────────┐      │
│  │     OpenHanako Agent       │      │
│  │     (Docker Container)     │      │
│  └─────────┬──────────────────┘      │
│            │ MCP (stdio/SSE)         │
│  ┌─────────▼──────────────────┐      │
│  │  MCP Server Cluster        │      │
│  │  ┌──────┐ ┌──────┐ ┌────┐ │      │
│  │  │Alpaca│ │Risk  │ │Sched│ │      │
│  │  │Trade │ │Guard │ │uler │ │      │
│  │  └──────┘ └──────┘ └────┘ │      │
│  └────────────────────────────┘      │
│            │                          │
│  ┌─────────▼──────────────────┐      │
│  │  PostgreSQL (审计+配置)     │      │
│  │  Redis (风控状态缓存)       │      │
│  └────────────────────────────┘      │
└────────────────┬─────────────────────┘
                 │ HTTPS
                 ▼
        Alpaca Trading API (实盘)
```

---

## 六、多用户支持

给其他人用的系统，需要多用户隔离：

```
┌───────────────────────────────────┐
│           用户 A                  │
│  API Key A | 风控配置 A | 审计日志 A │
├───────────────────────────────────┤
│           用户 B                  │
│  API Key B | 风控配置 B | 审计日志 B │
├───────────────────────────────────┤
│           用户 C                  │
│  API Key C | 风控配置 C | 审计日志 C │
└───────────────────────────────────┘
```

**实现方式**：
- 每个 OpenHanako 用户会话绑定独立的 Alpaca API Key
- risk-guard 根据用户 ID 读取对应的风控配置
- 审计日志按用户 ID 分表/分库

---

## 七、安全设计

### 7.1 API Key 管理

```
❌ 不要做的：
- 把 API Key 硬编码在代码里
- 把 API Key 存在明文配置文件里

✅ 应该做的：
- 使用环境变量或密钥管理服务（如 HashiCorp Vault）
- 每个用户独立 API Key
- API Key 加密存储，运行时解密
```

### 7.2 权限分级

| 级别 | 能力 | 适用场景 |
|------|------|---------|
| **只读** | 查行情、查持仓 | 观察者模式 |
| **模拟盘** | 模拟交易 | 新用户/测试 |
| **受限实盘** | 实盘交易，受严格风控 | 正式用户 |
| **管理员** | 修改风控配置、查看所有用户数据 | 系统运维 |

---

## 八、实施路线图

### Phase 1 — MVP（1-2 周）
- [ ] 安装配置 Alpaca MCP Server
- [ ] OpenHanako 接入 Alpaca MCP
- [ ] 模拟盘跑通「自然语言下单」流程
- [ ] 基础风控：单笔金额限制

### Phase 2 — 风控加固（2-3 周）
- [ ] 完成 risk-guard MCP Server
- [ ] 实现完整风控规则链
- [ ] 审计日志（SQLite）
- [ ] 紧急熔断功能

### Phase 3 — 自动化（2-3 周）
- [ ] 实现 scheduler MCP Server
- [ ] 定时策略执行（开盘/收盘任务）
- [ ] 交易日报生成
- [ ] 多用户支持

### Phase 4 — 生产化（3-4 周）
- [ ] Docker 容器化部署
- [ ] PostgreSQL + Redis
- [ ] Web 监控面板
- [ ] 实盘灰度上线

---

## 九、关键风险和缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Agent 误判导致亏损 | 高 | 风控层强制拦截 + 单笔金额限制 + 日内亏损熔断 |
| LLM 幻觉（编造数据） | 中 | 强制调用 API 获取真实数据，禁止 LLM 猜测价格 |
| API Key 泄露 | 高 | 加密存储 + 最小权限原则 + IP 白名单 |
| Alpaca API 宕机 | 中 | 重试机制 + 降级策略（暂停交易） |
| MCP Server 崩溃 | 中 | 进程守护（supervisor/systemd）+ 健康检查 |
| 合规风险 | 高 | Alpaca 已是 SEC 注册券商 + 系统内置审计日志 |

---

## 十、Alpaca 账户注册指引

1. 访问 [https://app.alpaca.markets](https://app.alpaca.markets)
2. 注册 **Paper Trading**（免费模拟盘账户）
3. 在 Dashboard 生成 API Key 和 Secret Key
4. 保存好 Key，配置到 MCP Server 的环境变量中
5. **实盘需要额外 KYC 审核和资金入账**

---

## 附录：Alpaca MCP Server 完整工具清单

> 来源：[alpacahq/alpaca-mcp-server](https://github.com/alpacahq/alpaca-mcp-server)

### 交易类
- `place_order` — 下单（市价/限价/止损/追踪止损）
- `cancel_order` — 撤销单个订单
- `cancel_all_orders` — 撤销所有挂单
- `get_orders` — 获取订单列表
- `get_order_by_id` — 获取单个订单详情

### 账户类
- `get_account` — 账户信息（余额、购买力）
- `get_positions` — 所有持仓
- `get_position` — 单个持仓
- `liquidate_position` — 清仓（全部/部分）
- `close_position` — 关闭持仓

### 市场数据类
- `get_quote` — 实时报价
- `get_latest_trade` — 最新成交
- `get_bars` — K线数据（可配置时间粒度）
- `get_snapshot` — 综合快照
- `get_stock_history` — 历史数据
- `search_assets` — 搜索资产

### 期权类
- `search_options` — 搜索期权合约
- `get_option_quote` — 期权报价
- `get_option_snapshot` — 期权快照
- `place_option_order` — 期权下单
- `exercise_option` — 行权

### 加密货币类
- `place_crypto_order` — 加密货币下单

### 市场状态类
- `get_clock` — 市场时间（开/闭市）
- `get_calendar` — 交易日历
- `get_corporate_actions` — 公司行为（分红/拆股/财报）

### 自选股类
- `get_watchlists` — 自选列表
- `add_to_watchlist` — 添加自选
- `remove_from_watchlist` — 移除自选
