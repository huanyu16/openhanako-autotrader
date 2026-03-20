# OpenHanako AutoTrader

> 基于 OpenHanako Agent + Alpaca MCP 的自动化交易系统
> 自然语言驱动 · 多资产支持 · 内置传奇交易策略

---

## 架构概览

```
用户 (自然语言指令)
        │
        ▼
OpenHanako Agent (LLM 决策引擎)
        │
        ├─ alpaca-trade MCP ──────→ Alpaca Trading API
        ├─ risk-guard MCP ────────→ 风控拦截 + 审计日志
        ├─ strategy MCP ──────────→ 技术指标 + 信号识别
        └─ scheduler MCP ─────────→ 定时策略自动执行
```

**支持资产**：美股 · 期货 · 加密货币 · 期权

---

## 功能特性

| 模块 | 能力 |
|------|------|
| **交易执行** | 市价/限价/止损/追踪止损下单，撤单，查持仓/订单 |
| **风控守卫** | 单笔限额、仓位上限、日内亏损熔断、交易频率限制、紧急止损 |
| **策略引擎** | SMA/EMA/RSI/MACD/Bollinger/ATR/ADX + Darvas Box + Livermore 突破 |
| **综合信号** | 多指标融合评分，输出 strong_buy → strong_sell 信号 |
| **趋势分析** | MA 均线排列 + ADX 趋势强度判定 |
| **自动调度** | 开盘前扫描 → 开盘执行 → 午间检查 → 收盘报告 |
| **多用户** | 独立 API Key、独立风控配置、独立审计日志 |
| **多风控档位** | 保守 · 达瓦斯 · 利弗莫尔 · 比赛 四档可切换 |

---

## 快速开始

### 前置条件

- Python 3.10+
- [Alpaca 账户](https://app.alpaca.markets)（免费注册 Paper Trading 模拟盘）
- OpenHanako Agent 运行环境

### 1. 克隆项目

```bash
git clone https://github.com/huanyu16/openhanako-autotrader.git
cd openhanako-autotrader
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

依赖清单：
```
mcp>=1.0.0
alpaca-py>=0.30.0
```

### 3. 配置 Alpaca API Key

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 Alpaca API 密钥：

```env
# 从 https://app.alpaca.markets/paper/dashboard/overview 获取
ALPACA_API_KEY=你的API Key
ALPACA_SECRET_KEY=你的Secret Key
ALPACA_PAPER_TRADE=true   # 建议先用模拟盘
```

### 4. 初始化目录结构

```bash
python install_all.py
```

这会自动创建 `shared/`、`servers/`、`config/`、`data/`、`logs/` 目录。

### 5. 配置 OpenHanako MCP

在 OpenHanako 的 MCP 配置中添加 Alpaca 交易服务：

```json
{
  "mcpServers": {
    "alpaca-trade": {
      "command": "uvx",
      "args": ["alpaca-mcp-server", "serve"],
      "env": {
        "ALPACA_API_KEY": "<你的API_KEY>",
        "ALPACA_SECRET_KEY": "<你的SECRET_KEY>",
        "ALPACA_PAPER_TRADE": "true"
      }
    }
  }
}
```

---

## 项目结构

```
oulay-trader/
├── README.md                  # 本文件
├── ARCHITECTURE.md            # 完整架构设计文档
├── requirements.txt           # Python 依赖
├── install_all.py             # 目录初始化脚本
├── .env.example               # 环境变量模板
├── config/
│   └── risk_profiles.json     # 风控档位配置
├── shared/
│   ├── __init__.py
│   ├── config.py              # 共享配置（环境变量加载）
│   ├── alpaca_client.py       # Alpaca API 封装
│   └── indicators.py          # 技术指标 + 策略信号引擎
├── servers/                   # MCP Server 实现目录（待扩展）
├── data/                      # 数据存储（审计数据库等）
└── logs/                      # 运行日志
```

---

## 内置交易策略

### Darvas Box（达瓦斯箱体）

尼古拉斯·达瓦斯的传奇箱体突破策略。自动计算价格箱体，突破上沿做多，跌破下沿做空。

```
composite_signal() → darvas_box 组件
输入：high[], low[], close[]
输出：box_top, box_bottom, signal (buy/sell/hold)
```

### Livermore Breakout（利弗莫尔突破）

杰西·利弗莫尔的突破交易法。结合价格突破 + 成交量确认，过滤假突破。

```
composite_signal() → livermore_breakout 组件
输入：high[], low[], close[], volume[]
输出：breakout_level, volume_ratio, signal, confidence
```

### 多指标融合信号

综合 RSI、Williams %R、Darvas Box、Livermore Breakout、趋势分析，输出 -10 ~ +10 综合评分：

```
from shared.indicators import composite_signal

result = composite_signal(close, high, low, volume)
# result.overall_signal: "strong_buy" / "buy" / "weak_buy" / "hold" / "weak_sell" / "sell" / "strong_sell"
# result.score: 综合评分
# result.confidence: 置信度 %
# result.components: 各指标明细
# result.reasons: 信号来源说明
```

---

## 风控配置

四档预设，在 `config/risk_profiles.json` 中配置：

| 档位 | 单笔上限 | 单标的上限 | 总仓位上限 | 日内止损 | 做空 | 杠杆 |
|------|---------|-----------|-----------|---------|------|------|
| **保守** | 5% | 15% | 50% | 2% | ❌ | 1x |
| **达瓦斯** | 15% | 25% | 70% | 5% | ❌ | 1x |
| **利弗莫尔** | 30% | 50% | 80% | 10% | ✅ | 2x |
| **比赛** | 80% | 100% | 100% | 50% | ✅ | 4x |

---

## Alpaca MCP Server 工具清单

> 基于 [alpacahq/alpaca-mcp-server](https://github.com/alpacahq/alpaca-mcp-server)（官方，565+ stars）

**交易**：`place_order` · `cancel_order` · `cancel_all_orders` · `get_orders`
**账户**：`get_account` · `get_positions` · `liquidate_position` · `close_position`
**行情**：`get_quote` · `get_latest_trade` · `get_bars` · `get_snapshot` · `get_stock_history` · `search_assets`
**期权**：`search_options` · `get_option_quote` · `place_option_order` · `exercise_option`
**加密**：`place_crypto_order`
**市场**：`get_clock` · `get_calendar` · `get_corporate_actions`
**自选**：`get_watchlists` · `add_to_watchlist` · `remove_from_watchlist`

---

## 使用示例

```
用户: "买入 100 股苹果，市价"
Agent: get_account → get_quote("AAPL") → risk_check → place_order → 确认

用户: "看看我的持仓"
Agent: get_positions → 汇总展示

用户: "AAPL 综合信号怎么样？"
Agent: get_bars → composite_signal → 输出评分和各指标明细

用户: "全部撤单"
Agent: cancel_all_orders → 确认
```

---

## 实施路线图

- [x] **Phase 1** — 架构设计 + Alpaca Client + 策略引擎 + 风控框架
- [ ] **Phase 2** — Risk Guard MCP Server（完整风控规则链 + 审计日志 + 熔断）
- [ ] **Phase 3** — Scheduler MCP Server（定时策略自动执行 + 交易日报）
- [ ] **Phase 4** — 多用户支持 + Web 监控面板 + Docker 容器化

---

## 安全提醒

- **不要**将 API Key 提交到 Git（`.env` 已在 `.gitignore` 中）
- 建议先用 Paper Trading 模拟盘充分测试
- 生产环境建议使用密钥管理服务（如 Vault）替代 `.env`
- 每个 Alpaca API Key 有独立权限，按需配置 IP 白名单

---

## License

MIT
