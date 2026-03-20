"""Oula Trading - Strategy Engine MCP Server (C) — 策略分析引擎

提供技术指标计算和传奇交易员策略分析。
底层调用 shared/indicators.py 的指标库。

工具清单：
  - full_analysis            核心工具：组合信号分析
  - darvas_box_signal        达瓦斯箱体理论
  - livermore_breakout_signal 利弗莫尔突破法
  - williams_analysis        威廉姆斯 %R 情绪判断
  - trend_signal             趋势分析（均线+ADX）
  - calculate_indicator      通用指标计算
  - market_scan              批量扫描多标的
  - get_account_overview     账户概览+持仓信号分析
"""

import json
from typing import Optional

try:
    from mcp.server.fastmcp import FastMCP
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

from shared.indicators import (
    sma, ema, rsi, macd, bollinger, atr, adx,
    williams_pct_r, volume_ratio,
    darvas_box, livermore_breakout, trend_analysis, composite_signal
)
from shared.alpaca_client import AlpacaClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_arrays(bars: list) -> tuple:
    """从 K 线数据中提取 OHLCV 数组"""
    if not bars:
        raise ValueError("No bar data available")
    c = [b["close"] for b in bars]
    h = [b["high"] for b in bars]
    l = [b["low"] for b in bars]
    v = [b["volume"] for b in bars]
    return c, h, l, v


def _fmt_pct(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    return f"{val:+.1f}%"


def _signal_emoji(signal: str) -> str:
    m = {
        "strong_buy": "🟢🟢", "buy": "🟢", "weak_buy": "🟡",
        "hold": "⚪", "weak_sell": "🟠", "sell": "🔴", "strong_sell": "🔴🔴"
    }
    return m.get(signal, "⚪")


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def create_server():
    mcp = FastMCP("strategy-engine")

    @mcp.tool()
    def full_analysis(
        symbol: str,
        timeframe: str = "1Day",
        days: int = 250
    ) -> dict:
        """核心工具：组合信号分析，综合多个策略输出买卖建议。
        融合 Darvas Box + Livermore Breakout + Williams %R + RSI + 趋势分析，
        输出 -10 ~ +10 综合评分及 strong_buy/strong_sell 信号。

        Args:
            symbol: 股票代码
            timeframe: K线周期 (1Min/5Min/15Min/1Hour/1Day/1Week)
            days: 历史天数（建议≥250）
        """
        client = AlpacaClient()
        bars = client.get_bars(symbol, timeframe, days)
        c, h, l, v = _extract_arrays(bars)
        result = composite_signal(c, h, l, v)
        result["symbol"] = symbol
        result["bars_used"] = len(bars)
        result["emoji"] = _signal_emoji(result["overall_signal"])
        return result

    @mcp.tool()
    def darvas_box_signal(
        symbol: str,
        lookback: int = 20,
        timeframe: str = "1Day",
        days: int = 60
    ) -> dict:
        """达瓦斯箱体理论：识别价格箱体突破。
        当价格突破箱体上沿且涨幅超过 2% 容差时发出买入信号，
        跌破箱体下沿发出卖出信号。

        Args:
            symbol: 股票代码
            lookback: 箱体回看天数
            timeframe: K线周期
            days: 历史天数
        """
        client = AlpacaClient()
        bars = client.get_bars(symbol, timeframe, days)
        c, h, l, v = _extract_arrays(bars)
        result = darvas_box(h, l, c, lookback)
        result["symbol"] = symbol
        result["strategy"] = "Darvas Box Theory (尼古拉斯·达瓦斯)"
        return result

    @mcp.tool()
    def livermore_breakout_signal(
        symbol: str,
        lookback: int = 20,
        volume_threshold: float = 1.5,
        timeframe: str = "1Day",
        days: int = 60
    ) -> dict:
        """利弗莫尔突破法：阻力位突破 + 量能确认。
        寻找前期高点阻力位，突破时结合成交量判断真假突破。
        成交量需达到均值的 volume_threshold 倍才确认为真突破。

        Args:
            symbol: 股票代码
            lookback: 阻力位回看天数
            volume_threshold: 成交量确认倍数（默认1.5倍）
            timeframe: K线周期
            days: 历史天数
        """
        client = AlpacaClient()
        bars = client.get_bars(symbol, timeframe, days)
        c, h, l, v = _extract_arrays(bars)
        result = livermore_breakout(h, l, c, v, lookback, volume_threshold)
        result["symbol"] = symbol
        result["strategy"] = "Livermore Breakout (杰西·利弗莫尔)"
        return result

    @mcp.tool()
    def williams_analysis(
        symbol: str,
        period: int = 14,
        timeframe: str = "1Day",
        days: int = 60
    ) -> dict:
        """威廉姆斯 %R：超买超卖情绪判断。
        %R < -80 为超卖区域（潜在买入机会），
        %R > -20 为超买区域（潜在卖出机会）。

        Args:
            symbol: 股票代码
            period: 计算周期
            timeframe: K线周期
            days: 历史天数
        """
        client = AlpacaClient()
        bars = client.get_bars(symbol, timeframe, days)
        c, h, l, v = _extract_arrays(bars)
        values = williams_pct_r(h, l, c, period)
        current = values[-1] if values and values[-1] is not None else -50

        if current <= -80:
            signal = "oversold"
            suggestion = "潜在买入机会"
        elif current >= -20:
            signal = "overbought"
            suggestion = "潜在卖出机会"
        else:
            signal = "neutral"
            suggestion = "暂无明确信号"

        return {
            "symbol": symbol,
            "indicator": "Williams %R",
            "current_value": round(current, 1),
            "period": period,
            "signal": signal,
            "suggestion": suggestion,
            "history": [round(v, 1) if v is not None else None for v in values[-20:]],
            "strategy": "Larry Williams %R (拉瑞·威廉姆斯)"
        }

    @mcp.tool()
    def trend_signal(
        symbol: str,
        timeframe: str = "1Day",
        days: int = 250
    ) -> dict:
        """趋势分析：MA 均线排列 + ADX 趋势强度。
        需要200+根K线。判断 strong_up/up/sideways/down/strong_down 趋势。

        Args:
            symbol: 股票代码
            timeframe: K线周期
            days: 历史天数（建议≥250）
        """
        client = AlpacaClient()
        bars = client.get_bars(symbol, timeframe, days)
        c, h, l, v = _extract_arrays(bars)
        result = trend_analysis(c, h, l)
        result["symbol"] = symbol
        result["bars_used"] = len(bars)
        return result

    @mcp.tool()
    def calculate_indicator(
        symbol: str,
        indicator: str,
        period: int = 14,
        timeframe: str = "1Day",
        days: int = 200
    ) -> dict:
        """通用指标计算：SMA/EMA/RSI/MACD/Bollinger/ATR/ADX。

        Args:
            symbol: 股票代码
            indicator: 指标名称 (sma/ema/rsi/macd/bollinger/atr/adx)
            period: 周期参数
            timeframe: K线周期
            days: 历史天数
        """
        client = AlpacaClient()
        bars = client.get_bars(symbol, timeframe, days)
        c, h, l, v = _extract_arrays(bars)

        indicators_map = {
            "sma": lambda: {"values": [round(x, 2) if x else None for x in sma(c, period)[-30:]], "period": period},
            "ema": lambda: {"values": [round(x, 2) if x else None for x in ema(c, period)[-30:]], "period": period},
            "rsi": lambda: {"values": [round(x, 1) if x else None for x in rsi(c, period)[-30:]], "period": period},
            "macd": lambda: {
                "macd": [round(x, 4) if x else None for x in macd(c)["macd"][-30:]],
                "signal": [round(x, 4) if x else None for x in macd(c)["signal"][-30:]],
                "histogram": [round(x, 4) if x else None for x in macd(c)["histogram"][-30:]]
            },
            "bollinger": lambda: {
                "upper": [round(x, 2) if x else None for x in bollinger(c, period)["upper"][-30:]],
                "middle": [round(x, 2) if x else None for x in bollinger(c, period)["middle"][-30:]],
                "lower": [round(x, 2) if x else None for x in bollinger(c, period)["lower"][-30:]]
            },
            "atr": lambda: {"values": [round(x, 2) if x else None for x in atr(h, l, c, period)[-30:]], "period": period},
            "adx": lambda: {"values": [round(x, 1) if x else None for x in adx(h, l, c, period)[-30:]], "period": period},
        }

        if indicator not in indicators_map:
            available = list(indicators_map.keys())
            return {"error": f"Unknown indicator: {indicator}. Available: {available}"}

        result = indicators_map[indicator]()
        result["symbol"] = symbol
        result["current_price"] = c[-1]
        result["bars_count"] = len(bars)
        return result

    @mcp.tool()
    def market_scan(
        symbols: str,
        min_score: int = 3,
        timeframe: str = "1Day",
        days: int = 250
    ) -> dict:
        """批量扫描：对多个标的运行组合分析，按综合评分排序。

        Args:
            symbols: 逗号分隔的股票代码 (如 "AAPL,TSLA,NVDA,GOOG")
            min_score: 最低信号评分筛选
            timeframe: K线周期
            days: 历史天数
        """
        symbol_list = [s.strip().upper() for s in symbols.split(",")]
        results = []
        errors = []

        client = AlpacaClient()
        for sym in symbol_list:
            try:
                bars = client.get_bars(sym, timeframe, days)
                c, h, l, v = _extract_arrays(bars)
                signal = composite_signal(c, h, l, v)
                signal["symbol"] = sym
                signal["emoji"] = _signal_emoji(signal["overall_signal"])
                if signal["score"] >= min_score:
                    results.append(signal)
            except Exception as e:
                errors.append({"symbol": sym, "error": str(e)})

        results.sort(key=lambda x: x["score"], reverse=True)

        return {
            "total_scanned": len(symbol_list),
            "qualified": len(results),
            "min_score_filter": min_score,
            "results": results,
            "errors": errors
        }

    @mcp.tool()
    def get_account_overview() -> dict:
        """账户概览：获取账户余额、持仓列表，并对每个持仓运行信号分析。
        """
        client = AlpacaClient()
        account = client.get_account()
        positions = client.get_positions()

        total_unrealized = sum(p["unrealized_pl"] for p in positions)
        position_signals = []

        for p in positions:
            try:
                bars = client.get_bars(p["symbol"], "1Day", 60)
                c, h, l, v = _extract_arrays(bars)
                signal = composite_signal(c, h, l, v)
                position_signals.append({
                    "symbol": p["symbol"],
                    "qty": p["qty"],
                    "market_value": p["market_value"],
                    "unrealized_pl": round(p["unrealized_pl"], 2),
                    "unrealized_plpc": round(p["unrealized_plpc"], 2),
                    "signal": signal["overall_signal"],
                    "signal_emoji": _signal_emoji(signal["overall_signal"]),
                    "score": signal["score"],
                    "confidence": signal["confidence"]
                })
            except Exception as e:
                position_signals.append({
                    "symbol": p["symbol"],
                    "qty": p["qty"],
                    "market_value": p["market_value"],
                    "unrealized_pl": round(p["unrealized_pl"], 2),
                    "unrealized_plpc": round(p["unrealized_plpc"], 2),
                    "signal": "error",
                    "error": str(e)
                })

        return {
            "account": {
                "cash": round(account["cash"], 2),
                "buying_power": round(account["buying_power"], 2),
                "portfolio_value": round(account["portfolio_value"], 2),
                "equity": round(account["equity"], 2),
                "paper": account["paper"]
            },
            "total_positions": len(positions),
            "total_unrealized_pl": round(total_unrealized, 2),
            "positions": position_signals,
            "timestamp": __import__("datetime").datetime.now().isoformat()
        }

    return mcp


if __name__ == "__main__":
    if not HAS_MCP:
        print("请先安装: pip install mcp")
        exit(1)
    server = create_server()
    server.run(transport="stdio")
