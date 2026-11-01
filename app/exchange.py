import asyncio
from typing import Any
import httpx
from app.models import Candle
class ExchangeError(RuntimeError): pass
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
        if interval not in {"5m","15m","1h","4h","1d"}: raise ValueError("Unsupported interval")
        d=await self._get(f"{self.futures_base}/api/v1/futures/market/kline",{"symbol":symbol,"interval":interval,"limit":min(max(limit,20),200)})
        if not isinstance(d,list) or not d: raise ExchangeError(f"No candles for {symbol} {interval}")
        out=[]
        for x in d:
            try: c=Candle(int(x["time"]),float(x["open"]),float(x["high"]),float(x["low"]),float(x["close"]),float(x.get("quoteVol") or 0),float(x.get("baseVol") or 0))
            except (KeyError,TypeError,ValueError) as e: raise ExchangeError(f"Malformed candle: {e}") from e
            if not c.valid(): raise ExchangeError("Invalid OHLCV candle")
            out.append(c)
        out.sort(key=lambda x:x.time_ms)
        if len({x.time_ms for x in out})!=len(out): raise ExchangeError("Duplicate candle timestamps")
        return out
