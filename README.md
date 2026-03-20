# OpenHanako AutoTrader

> OpenHanako Agent 自动交易系统
> 集成了传奇交易员策略（达瓦斯箱体、利弗莫尔突破、威廉姆斯%R），
> 配备完整风控系统和自动调度引擎。

---

## 📁 项目结构

```
openhanako-auto-trader/
├── install.sh                    # 一键安装脚本
├── requirements.txt              # Python 依赖
├── .env.example                  # 环境变量模板
├── README.md                     # 本文件
│
├── shared/                       # 共享库
│   ├── __init__.py
│   ├── config.py                 # 配置加载
│   ├── alpaca_client.py          # Alpaca API 封装
│   └── indicators.py             # 技术指标 + 传奇策略算法
│
├── servers/                      # MCP Servers
│   ├── strategy_engine.py        # 策略分析引擎
│   ├── risk_guard.py             # 风控守卫
│   └── auto_scheduler.py         # 定时调度器
│
├── config/                       # 配置文件
│   ├── openhanako_mcp.json       # OpenHanako MCP 配置
│   └── risk_profiles.json        # 风控模板定义
│
├── docs/                         # 文档
│   └── 传奇交易员研究.md
│
└── data/                         # 运行时数据（自动创建）
    ├── audit.db                  # 审计日志数据库
    └── scheduler.db              # 调度任务数据库
```

---

## 🚀 快速安装

### 前置条件
- Python 3.10+
- [Alpaca 账户](https://app.alpaca.markets)（免费注册）
- OpenHanako 已安装并运行
- uv 包管理器（安装 Alpaca 官方 MCP 用）

### 安装步骤

```bash
# 1. 克隆/解压项目
cd openhanako-auto-trader

# 2. 运行安装脚本
bash install.sh

# 3. 填写 Alpaca API Key
nano .env
# 把 your_api_key_here 和 your_secret_key_here 替换成你的真实 Key

# 4. 安装 Alpaca 官方交易 MCP Server
uvx alpaca-mcp-server init
# 按提示输入 API Key，选择 Paper Trading

# 5. 配置 OpenHanako
# 将 config/openhanako_mcp.json 的内容合并到 OpenHanako 的 MCP 配置中
```

---

## 📊 四个 MCP Server 说明

### 1. Strategy Engine（策略分析引擎）

提供技术指标计算和传奇交易员策略分析。

| 工具 | 说明 |
|------|------|
| `full_analysis` | 核心工具：组合信号分析，综合多个策略输出买卖建议 |
| `darvas_box_signal` | 达瓦斯箱体理论：识别价格箱体突破 |
| `livermore_breakout_signal` | 利弗莫尔突破法：阻力位突破+量能确认 |
| `williams_analysis` | 威廉姆斯 %R：超买超卖情绪判断 |
| `trend_signal` | 趋势分析：均线排列+ADX 趋势强度 |
| `calculate_indicator` | 通用指标计算：SMA/EMA/RSI/MACD/布林带/ATR/ADX |
| `market_scan` | 批量扫描：对多个标的运行组合分析 |
| `get_account_overview` | 账户概览+持仓信号分析 |

### 2. Risk Guard（风控守卫）

所有交易必须先通过风控检查。

| 工具 | 说明 |
|------|------|
| `risk_check` | 核心工具：交易前置风控检查 |
| `set_risk_profile` | 切换风控模板 |
| `get_risk_profile` | 查看当前风控配置 |
| `emergency_stop` | 紧急熔断：撤单+暂停交易 |
| `resume_trading` | 恢复交易 |
| `check_stop_loss` | 止损监控：检查所有持仓 |
| `set_universe` | 设置交易标的白名单 |
| `get_audit_log` | 查询审计日志 |
| `get_position_risk_summary` | 持仓风险概览 |

### 3. Auto Scheduler（定时调度器）

管理自动化交易计划。

| 工具 | 说明 |
|------|------|
| `setup_default_tasks` | 一键配置所有默认调度任务 |
| `create_task` | 创建自定义定时任务 |
| `list_tasks` | 查看所有任务 |
| `toggle_task` | 启用/暂停任务 |
| `delete_task` | 删除任务 |
| `get_latest_signals` | 查看最新交易信号 |
| `get_daily_report` | 查看每日交易报告 |
| `generate_daily_report` | 手动生成今日报告 |
| `get_builtin_task_templates` | 查看内置任务模板 |

### 4. Alpaca Trade（官方交易执行层）

由 Alpaca 官方提供，负责实际下单和获取市场数据。

安装：`uvx alpaca-mcp-server init`

---

## 🛡️ 风控模板

| 模板 | 单笔上限 | 总仓位 | 止损 | 适用场景 |
|------|---------|--------|------|---------|
| 保守模式 | 5% | 50% | 3% | 新手/不确定市场 |
| 达瓦斯模式 | 15% | 70% | 5% | 箱体突破确认后 |
| 利弗莫尔模式 | 30% | 80% | 8% | 高置信度信号 |
| 比赛模式 | 80% | 100% | 15% | 仅模拟盘 |

---

## 💬 OpenHanako Agent Prompt 建议

将以下内容加入你的 OpenHanako Agent System Prompt：

```
你是一个专业的自动交易 agent，受传奇交易员思想训练。

## 交易流程（必须严格遵守）
1. 获取行情 → alpaca-trade.get_quote / get_snapshot
2. 策略分析 → full_analysis / darvas_box_signal / livermore_breakout_signal
3. 风控检查 → risk_guard.risk_check（必须通过！）
4. 执行下单 → alpaca-trade.place_order
5. 确认结果 → 返回给用户

## 行为准则
- 趋势是朋友，只做趋势明确的交易
- 严格止损，不扛单
- 让利润奔跑，不要小盈就跑
- 信号驱动，不猜测
- 多信号一致时加大仓位，信号冲突时观望
- 绝对禁止：报复性交易、非交易时间下单
```

---

## 🔧 典型使用场景

### 场景 1：手动交易

```
用户: "买入 100 股苹果"
Agent: 调用 get_quote(AAPL) → 调用 full_analysis(AAPL)
     → 调用 risk_check(AAPL, buy, 100, price)
     → 通过后调用 place_order
```

### 场景 2：每日自动扫描

```
调度器触发 → Agent 对白名单标的逐个运行 full_analysis
         → 过滤高置信度信号
         → 生成今日关注列表
         → 用户确认后执行
```

### 场景 3：紧急风控

```
用户: "熔断！"
Agent: 调用 emergency_stop() → 所有挂单撤销，交易暂停

用户: "解除熔断"
Agent: 调用 resume_trading() → 交易恢复
```

---

## ⚠️ 免责声明

本软件仅供学习和研究使用。交易有风险，投资需谨慎。
使用者应自行承担所有交易决策的风险和后果。
建议先使用 Alpaca 模拟盘充分测试后再考虑实盘。

## 📄 License

MIT
