"""Oula Trading - Strategy Analysis MCP Server (C) — 策略分析

提供技术指标计算、市场扫描、趋势分析能力。
底层调用 shared/indicators.py 的指标库。
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


# ---------------------------------------------------------------------------
# MCP Server Definition
# ---------------------------------------------------------------------------

def create_server():
    mcp = FastMCP("strategy-analyzer")

    @mcp.tool()
    def calculate_indicator(
        symbol: str,
        indicator: str,
        period: int = 14,
        timeframe: str = "1Day",
        days: int = 200
    ) -> dict:
        """计算技术指标（SMA/EMA/RSI/MACD/Bollinger/ATR/ADX/Williams%R）。
        
        Args:
            symbol: 股票代码
            indicator: 指标名称 (sma/ema/rsi/macd/bollinger/atr/adx/williams_pct_r)
            period: 周期参数
            timeframe: K线周期 (1Min/5Min/15Min/1Hour/1Day/1Week)
            days: 获取多少天的历史数据
        """
        client = AlpacaClient()
        bars = client.get_bars(symbol, timeframe, days)
        c, h, l, v = _extract_arrays(bars)

        indicators_map = {
            "sma": lambda: {"values": sma(c, period)[-30:], "period": period},
            "ema": lambda: {"values": ema(c, period)[-30:], "period": period},
            "rsi": lambda: {"values": rsi(c, period)[-30:], "period": period},
            "macd": lambda: {
                "macd": macd(c)["macd"][-30:],
                "signal": macd(c)["signal"][-30:],
                "histogram": macd(c)["histogram"][-30:]
            },
            "bollinger": lambda: {
                "upper": bollinger(c, period)["upper"][-30:],
                "middle": bollinger(c, period)["middle"][-30:],
                "lower": bollinger(c, period)["lower"][-30:]
            },
            "atr": lambda: {"values": atr(h, l, c, period)[-30:], "period": period},
            "adx": lambda: {"values": adx(h, l, c, period)[-30:], "period": period},
            "williams_pct_r": lambda: {"values": williams_pct_r(h, l, c, period)[-30:], "period": period},
        }

        if indicator not in indicators_map:
            available = list(indicators_map.keys())
            return {"error": f"Unknown indicator: {indicator}. Available: {available}"}

        result = indicators_map[indicator]()
        result["symbol"] = symbol
        result["current"] = c[-1]
        result["bars_count"] = len(bars)
        return result

    @mcp.tool()
    def analyze_trend(symbol: str, timeframe: str = "1Day", days: int = 250) -> dict:
        """趋势分析（MA均线排列 + ADX趋势强度）。
        需要200+根K线才能计算完整。
        
        Args:
            symbol: 股票代码
            timeframe: K线周期
            days: 历史天数（建议≥250）
        """
        client = AlpacaClient()
        bars = client.get_bars(symbol, timeframe, days)
        c, h, l, v = _extract_arrays(bars)
        return trend_analysis(c, h, l)

    @mcp.tool()
    def composite_signal_analysis(
        symbol: str,
        timeframe: str = "1Day",
        days: int = 250
    ) -> dict:
        """多指标融合信号分析（综合 Darvas Box + Livermore + RSI + WR + 趋势）。
        输出 -10 ~ +10 的综合评分及 strong_buy/strong_sell 信号。
        
        Args:
            symbol: 股票代码
            timeframe: K线周期
            days: 历史天数（建议≥250）
        """
        client = AlpacaClient()
        bars = client.get_bars(symbol, timeframe, days)
        c, h, l, v = _extract_arrays(bars)
        result = composite_signal(c, h, l, v)
        result["symbol"] = symbol
        result["bars_used"] = len(bars)
        return result

    @mcp.tool()
    def scan_screener(
        symbols: str,
        min_signal_score: int = 3,
        timeframe: str = "1Day",
        days: int = 250
    ) -> dict:
        """市场扫描：批量分析多只股票，按综合信号评分排序。
        
        Args:
            symbols: 逗号分隔的股票代码列表 (如 "AAPL,TSLA,NVDA,GOOG")
            min_signal_score: 最低信号评分筛选
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
                if signal["score"] >= min_signal_score:
                    results.append(signal)
            except Exception as e:
                errors.append({"symbol": sym, "error": str(e)})

        # 按评分降序排列
        results.sort(key=lambda x: x["score"], reverse=True)

        return {
            "total_scanned": len(symbol_list),
            "qualified": len(results),
            "results": results,
            "errors": errors,
            "min_score_filter": min_signal_score
        }

    return mcp


if __name__ == "__main__":
    if not HAS_MCP:
        print("请先安装: pip install mcp")
        exit(1)
    server = create_server()
    server.run(transport="stdio")
