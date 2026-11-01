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


async def check_symbol(client: BitunixClient, symbol: str) -> dict:
    started = time.perf_counter()
    result = {
        "symbol": symbol,
        "interval": INTERVAL,
        "requested_candles": CANDLE_LIMIT,
    }
    try:
        candles = await client.futures_klines(symbol, INTERVAL, CANDLE_LIMIT)
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
        # Repeat only this symbol to distinguish a transient response from a
        # reproducible bad candle. Never repair or silently discard bad data.
        try:
            second = await client.futures_klines(symbol, INTERVAL, CANDLE_LIMIT)
            result["repeat_check"] = {
                "status": "VALID_ON_REPEAT",
                "received_candles": len(second),
            }
        except InvalidMarketDataError as repeat_exc:
            result["repeat_check"] = {
                "status": "INVALID_ON_REPEAT",
                "received_candles": repeat_exc.total,
                "invalid_count": len(repeat_exc.invalid),
                "invalid_candles": repeat_exc.invalid[:5],
            }
        except Exception as repeat_exc:
            result["repeat_check"] = {
                "status": "REPEAT_REQUEST_FAILED",
                "error_type": type(repeat_exc).__name__,
                "error": str(repeat_exc),
            }
    except Exception as exc:
        result.update({
            "status": "REQUEST_FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
    result["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return result


async def main() -> int:
    client = BitunixClient(
        settings.bitunix_futures_base_url,
        settings.bitunix_spot_base_url,
        settings.request_timeout_seconds,
    )
    started = time.perf_counter()
    try:
        tickers = await client.futures_tickers()
    except Exception as exc:
        print(json.dumps({
            "status": "CONNECTION_FAILED",
            "mode": "public_read_only",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "private_api_tested": False,
            "trading_enabled": False,
        }, indent=2))
        return 1

    results = []
    # Sequential requests keep the diagnostic gentle on the public endpoint.
    for symbol in SYMBOLS:
        results.append(await check_symbol(client, symbol))

    counts = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    invalid_total = sum(item.get("invalid_count", 0) for item in results)
    summary_status = "ALL_VALID" if len(results) == counts.get("VALID", 0) else "ISSUES_FOUND"
    print(json.dumps({
        "status": summary_status,
        "mode": "public_read_only",
        "base_url": settings.bitunix_futures_base_url,
        "ticker_count": len(tickers),
        "interval": INTERVAL,
        "candles_per_symbol": CANDLE_LIMIT,
        "symbols_requested": SYMBOLS,
        "symbols_checked": len(results),
        "status_counts": counts,
        "invalid_candle_total": invalid_total,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "results": results,
        "credentials_required": False,
        "private_api_tested": False,
        "trading_enabled": False,
        "note": "Invalid data is reported, never modified or silently discarded.",
    }, indent=2))
    return 0 if summary_status == "ALL_VALID" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
