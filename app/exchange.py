import asyncio
import time
from typing import Any
import httpx
from app.models import Candle

class ExchangeError(RuntimeError):
    pass

class InvalidMarketDataError(ExchangeError):
    def __init__(self, symbol: str, interval: str, total: int, invalid: list[dict[str, Any]]):
        self.symbol, self.interval, self.total, self.invalid = symbol, interval, total, invalid
        super().__init__(f"{len(invalid)} of {total} candles failed OHLCV validation for {symbol} {interval}")

INTERVAL_MS = {
    "1m": 60000, "3m": 180000, "5m": 300000, "15m": 900000,
    "30m": 1800000, "1h": 3600000, "2h": 7200000, "4h": 14400000,
    "6h": 21600000, "8h": 28800000, "12h": 43200000,
    "1d": 86400000, "3d": 259200000, "1w": 604800000,
    "1M": 2592000000,
}

def validate_fresh_candles(candles: list[Candle], interval: str,
                            now_ms: int | None = None,
                            max_age_intervals: float = 2.5) -> None:
    if interval not in INTERVAL_MS:
        raise ValueError("Unsupported interval")
    if not candles:
        raise ExchangeError("Empty candle series")
    step = INTERVAL_MS[interval]
    now_ms = now_ms or int(time.time() * 1000)
    if any(b.time_ms <= a.time_ms for a, b in zip(candles, candles[1:])):
        raise ExchangeError("Candle timestamps must be strictly increasing")
    if any(b.time_ms - a.time_ms > step * 1.5 for a, b in zip(candles, candles[1:])):
        raise ExchangeError("Candle series contains a time gap larger than 1.5 intervals")
    # Fixed-duration intervals are epoch-aligned. Calendar months are not.
    if interval != "1M" and any(c.time_ms % step != 0 for c in candles):
        raise ExchangeError("Candle timestamps are not aligned to interval boundaries")
    age = now_ms - candles[-1].time_ms
    if age < -step or age > step * max_age_intervals:
        raise ExchangeError(f"Stale or future candle data: last candle age {age} ms")

class BitunixClient:
    """Public read-only Bitunix client. No credentials or trading endpoints."""
    def __init__(self, futures_base: str, spot_base: str, timeout: float = 12.):
        self.futures_base = futures_base.rstrip("/")
        self.spot_base = spot_base.rstrip("/")
        self.timeout = timeout

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    payload = response.json()
                if not isinstance(payload, dict) or str(payload.get("code", "0")) not in ("0", "200", "None"):
                    raise ExchangeError(f"Bitunix error: {payload}")
                return payload.get("data")
            except (httpx.HTTPError, ValueError, ExchangeError) as exc:
                last = exc
                if attempt < 2:
                    await asyncio.sleep(.4 * 2**attempt)
        raise ExchangeError(f"Bitunix request failed after retries: {last}") from last

    async def futures_tickers(self) -> list[dict[str, Any]]:
        data = await self._get(f"{self.futures_base}/api/v1/futures/market/tickers")
        if not isinstance(data, list):
            raise ExchangeError("Unexpected futures ticker response")
        return data

    async def futures_klines(self, symbol: str, interval: str, limit: int = 200,
                            candle_type: str = "LAST_PRICE",
                            end_time_ms: int | None = None,
                            strict_validation: bool = True) -> list[Candle]:
        if interval not in INTERVAL_MS:
            raise ValueError("Unsupported interval")
        if candle_type not in ("LAST_PRICE", "MARK_PRICE"):
            raise ValueError("Unsupported candle type")
        if not 1 <= limit <= 200:
            raise ValueError("Kline limit must be between 1 and 200")
        params = {"symbol": symbol, "interval": interval, "limit": limit, "type": candle_type}
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        data = await self._get(f"{self.futures_base}/api/v1/futures/market/kline", params)
        if not isinstance(data, list) or not data:
            raise ExchangeError(f"No candles for {symbol} {interval}")
        out, invalid = [], []
        for item in data:
            try:
                candle = Candle(int(item["time"]), float(item["open"]), float(item["high"]),
                    float(item["low"]), float(item["close"]),
                    float(item.get("quoteVol") or 0), float(item.get("baseVol") or 0))
            except (KeyError, TypeError, ValueError) as exc:
                raise ExchangeError(f"Malformed candle: {exc}") from exc
            if not candle.valid():
                invalid.append({"time_ms": candle.time_ms, "open": candle.open,
                    "high": candle.high, "low": candle.low, "close": candle.close,
                    "quote_volume": candle.quote_volume, "base_volume": candle.base_volume,
                    "reason": "OHLCV invariant failed"})
            out.append(candle)
        if invalid and strict_validation:
            raise InvalidMarketDataError(symbol, interval, len(data), invalid)
        out.sort(key=lambda x: x.time_ms)
        if len({x.time_ms for x in out}) != len(out):
            raise ExchangeError("Duplicate candle timestamps")
        return out
