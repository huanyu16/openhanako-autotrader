"""Oula Trading - Alpaca API Client"""
from datetime import datetime, timedelta
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, StopOrderRequest, GetOrdersRequest, OrderSide, TimeInForce, ClosePositionRequest
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, StockLatestTradeRequest, StockSnapshotRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    HAS_ALPACA = True
except ImportError: HAS_ALPACA = False
from .config import get_alpaca_credentials
class AlpacaClient:
    def __init__(self):
        if not HAS_ALPACA: raise ImportError("pip install alpaca-py")
        c = get_alpaca_credentials()
        if not c["api_key"] or not c["secret_key"]: raise ValueError("Fill API keys in .env")
        self.paper = c["paper"]
        self.trading = TradingClient(c["api_key"], c["secret_key"], paper=c["paper"])
        self.data = StockHistoricalDataClient(c["api_key"], c["secret_key"])
    def get_account(self):
        a = self.trading.get_account()
        return {"id":a.id,"cash":float(a.cash),"buying_power":float(a.buying_power),"portfolio_value":float(a.portfolio_value),"equity":float(a.equity),"status":a.status,"paper":self.paper}
    def get_positions(self):
        return [{"symbol":p.symbol,"qty":int(float(p.qty)),"avg_entry_price":float(p.avg_entry_price),"current_price":float(p.current_price),"market_value":float(p.market_value),"unrealized_pl":float(p.unrealized_pl),"unrealized_plpc":float(p.unrealized_plpc)*100,"side":p.side} for p in self.trading.get_all_positions()]
    def place_market_order(self, symbol, qty, side):
        r = MarketOrderRequest(symbol=symbol,qty=qty,side=OrderSide.BUY if side=="buy" else OrderSide.SELL,time_in_force=TimeInForce.DAY)
        o = self.trading.submit_order(r); return {"id":o.id,"symbol":o.symbol,"qty":float(o.qty),"side":str(o.side),"type":str(o.type),"status":str(o.status)}
    def place_limit_order(self, symbol, qty, side, limit_price):
        r = LimitOrderRequest(symbol=symbol,qty=qty,side=OrderSide.BUY if side=="buy" else OrderSide.SELL,time_in_force=TimeInForce.GTC,limit_price=limit_price)
        o = self.trading.submit_order(r); return {"id":o.id,"symbol":o.symbol,"status":str(o.status)}
    def cancel_all_orders(self): self.trading.cancel_orders(); return {"success":True}
    def get_orders(self, status="open"):
        r = GetOrdersRequest(status=status)
        return [{"id":o.id,"symbol":o.symbol,"qty":float(o.qty),"side":str(o.side),"type":str(o.type),"status":str(o.status)} for o in self.trading.get_orders(r)]
    def get_bars(self, symbol, timeframe="1Day", days=30):
        tf = {"1Min":TimeFrame(1,TimeFrameUnit.Minute),"5Min":TimeFrame(5,TimeFrameUnit.Minute),"15Min":TimeFrame(15,TimeFrameUnit.Minute),"1Hour":TimeFrame(1,TimeFrameUnit.Hour),"1Day":TimeFrame(1,TimeFrameUnit.Day),"1Week":TimeFrame(1,TimeFrameUnit.Week)}
        req = StockBarsRequest(symbol_or_symbols=symbol,timeframe=tf.get(timeframe,TimeFrame(1,TimeFrameUnit.Day)),start=(datetime.now()-timedelta(days=days)).isoformat())
        bars = self.data.get_stock_bars(req); result = []
        if hasattr(bars,'df') and symbol in bars.df.index.get_level_values(0):
            df = bars.df.xs(symbol,level=0)
            for idx,row in df.iterrows(): result.append({"time":str(idx),"open":float(row["open"]),"high":float(row["high"]),"low":float(row["low"]),"close":float(row["close"]),"volume":int(row["volume"])})
        return result
    def get_latest_quote(self, symbol):
        q = self.data.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))[symbol]
        return {"symbol":symbol,"bid_price":float(q.bid_price),"ask_price":float(q.ask_price),"mid_price":(float(q.bid_price)+float(q.ask_price))/2}
    def get_snapshot(self, symbol):
        s = self.data.get_stock_snapshot(StockSnapshotRequest(symbol_or_symbols=symbol))[symbol]
        return {"symbol":symbol,"latest_trade":float(s.latest_trade.price) if s.latest_trade else None,"daily_open":float(s.daily_bar.open) if s.daily_bar else None,"daily_high":float(s.daily_bar.high) if s.daily_bar else None,"daily_low":float(s.daily_bar.low) if s.daily_bar else None,"daily_close":float(s.daily_bar.close) if s.daily_bar else None,"daily_volume":int(s.daily_bar.volume) if s.daily_bar else None,"prev_close":float(s.prev_daily_bar.close) if s.prev_daily_bar else None}
    def liquidate_position(self, symbol, percentage=100):
        if percentage >= 100: self.trading.close_position(ClosePositionRequest(symbol=symbol,percentage=1.0)); return {"success":True,"symbol":symbol}
        pos = self.trading.get_position_by_symbol(symbol); sq = int(int(float(pos.qty))*percentage/100)
        return self.place_market_order(symbol,sq,"sell") if sq > 0 else {"success":False}
