import asyncio
import time
from typing import Any
import httpx
from app.models import Candle
class ExchangeError(RuntimeError): pass
class InvalidMarketDataError(ExchangeError):
    def __init__(self, symbol: str, interval: str, total: int, invalid: list[dict[str, Any]]):
        self.symbol = symbol
        self.interval = interval
        self.total = total
        self.invalid = invalid
        super().__init__(f"{len(invalid)} of {total} candles failed OHLCV validation for {symbol} {interval}")
INTERVAL_MS={"5m":300000,"15m":900000,"1h":3600000,"4h":14400000,"1d":86400000}
def validate_fresh_candles(candles:list[Candle],interval:str,now_ms:int|None=None,max_age_intervals:float=2.5)->None:
    if interval not in INTERVAL_MS: raise ValueError("Unsupported interval")
    if not candles: raise ExchangeError("Empty candle series")
    step=INTERVAL_MS[interval]; now_ms=now_ms or int(time.time()*1000)
    if any(b.time_ms<=a.time_ms for a,b in zip(candles,candles[1:])):
        raise ExchangeError("Candle timestamps must be strictly increasing")
    if any(b.time_ms-a.time_ms>step*1.5 for a,b in zip(candles,candles[1:])):
        raise ExchangeError("Candle series contains a time gap larger than 1.5 intervals")
    age=now_ms-candles[-1].time_ms
    if age < -step or age > step*max_age_intervals:
        raise ExchangeError(f"Stale or future candle data: last candle age {age} ms")
class BitunixClient:
    """Public read-only Bitunix client. No credentials or trading endpoints."""
    def __init__(self,futures_base:str,spot_base:str,timeout:float=12.):
        self.futures_base=futures_base.rstrip("/"); self.spot_base=spot_base.rstrip("/"); self.timeout=timeout
    async def _get(self,url:str,params:dict[str,Any]|None=None)->Any:
        last=None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as c:
                    r=await c.get(url,params=params); r.raise_for_status(); p=r.json()
                if not isinstance(p,dict) or str(p.get("code","0")) not in ("0","200","None"): raise ExchangeError(f"Bitunix error: {p}")
                return p.get("data")
            except (httpx.HTTPError,ValueError,ExchangeError) as e:
                last=e
                if attempt<2: await asyncio.sleep(.4*2**attempt)
        raise ExchangeError(f"Bitunix request failed after retries: {last}") from last
    async def futures_tickers(self)->list[dict[str,Any]]:
        d=await self._get(f"{self.futures_base}/api/v1/futures/market/tickers")
        if not isinstance(d,list): raise ExchangeError("Unexpected futures ticker response")
        return d
    async def futures_klines(self,symbol:str,interval:str,limit:int=200)->list[Candle]:
        if interval not in INTERVAL_MS: raise ValueError("Unsupported interval")
        d=await self._get(f"{self.futures_base}/api/v1/futures/market/kline",{"symbol":symbol,"interval":interval,"limit":min(max(limit,20),200)})
        if not isinstance(d,list) or not d: raise ExchangeError(f"No candles for {symbol} {interval}")
        out=[]
        invalid=[]
        for x in d:
            try:
                c=Candle(int(x["time"]),float(x["open"]),float(x["high"]),float(x["low"]),float(x["close"]),float(x.get("quoteVol") or 0),float(x.get("baseVol") or 0))
            except (KeyError,TypeError,ValueError) as exc:
                raise ExchangeError(f"Malformed candle: {exc}") from exc
            if not c.valid():
                invalid.append({
                    "time_ms": c.time_ms, "open": c.open, "high": c.high,
                    "low": c.low, "close": c.close,
                    "quote_volume": c.quote_volume, "base_volume": c.base_volume,
                    "reason": "OHLCV invariant failed",
                })
            out.append(c)
        if invalid:
            raise InvalidMarketDataError(symbol, interval, len(d), invalid)
        out.sort(key=lambda x:x.time_ms)
        if len({x.time_ms for x in out})!=len(out): raise ExchangeError("Duplicate candle timestamps")
        return out
