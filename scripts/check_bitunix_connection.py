"""Read-only Bitunix Futures market-data check across 15 liquid USDT symbols."""
import asyncio
import json
import time

from app.config import settings
from app.exchange import (
    BitunixClient,
    ExchangeError,
    InvalidMarketDataError,
    validate_fresh_candles,
)

# Fixed sample makes runs comparable; every symbol uses the same interval/limit.
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT", "AVAXUSDT",
    "DOTUSDT", "LTCUSDT", "BCHUSDT", "SUIUSDT", "ETCUSDT",
]
INTERVAL = "15m"
CANDLE_LIMIT = 20


async def check_symbol(client: BitunixClient, symbol: str, candle_type: str) -> dict:
    started = time.perf_counter()
    result = {
        "symbol": symbol,
        "interval": INTERVAL,
        "candle_type": candle_type,
        "requested_candles": CANDLE_LIMIT,
    }
    try:
        candles = await client.futures_klines(
            symbol, INTERVAL, CANDLE_LIMIT, candle_type=candle_type
        )
        result.update({
            "status": "VALID",
            "received_candles": len(candles),
            "latest_candle_open_time_ms": candles[-1].time_ms,
        })
        try:
            validate_fresh_candles(candles, INTERVAL)
            result["freshness_and_continuity"] = "VALID"
        except ExchangeError as exc:
            result["freshness_and_continuity"] = "INVALID"
            result["data_quality_error"] = str(exc)
            result["status"] = "INVALID_DATA_QUALITY"
    except InvalidMarketDataError as exc:
        result.update({
            "status": "INVALID_OHLCV",
            "received_candles": exc.total,
            "invalid_count": len(exc.invalid),
            "invalid_candles": exc.invalid[:5],
        })
    except Exception as exc:
        result.update({
            "status": "REQUEST_FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
    result["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return result
