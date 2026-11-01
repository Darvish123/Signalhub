"""Read-only Bitunix Futures connectivity smoke check; no credentials required."""
import asyncio
import json
import time

from app.config import settings
from app.exchange import BitunixClient, InvalidMarketDataError, validate_fresh_candles


async def main() -> int:
    client = BitunixClient(
        settings.bitunix_futures_base_url,
        settings.bitunix_spot_base_url,
        settings.request_timeout_seconds,
    )
    started = time.perf_counter()
    try:
        tickers = await client.futures_tickers()
        candles = await client.futures_klines("BTCUSDT", "15m", 20)
        validate_fresh_candles(candles, "15m")
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        print(json.dumps({
            "status": "CONNECTED",
            "mode": "public_read_only",
            "base_url": settings.bitunix_futures_base_url,
            "ticker_count": len(tickers),
            "sample_symbol": "BTCUSDT",
            "sample_interval": "15m",
            "sample_candles": len(candles),
            "latest_candle_open_time_ms": candles[-1].time_ms,
            "latency_ms": elapsed_ms,
            "credentials_required": False,
            "private_api_tested": False,
            "trading_enabled": False,
        }, indent=2))
        return 0
    except InvalidMarketDataError as exc:
        print(json.dumps({
            "status": "API_REACHABLE_DATA_INVALID",
            "mode": "public_read_only",
            "base_url": settings.bitunix_futures_base_url,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "hint": "The public endpoint responded, but at least one market-data candle failed OHLCV validation. Raw values were not modified or silently discarded.",
            "private_api_tested": False,
            "trading_enabled": False,
        }, indent=2))
        return 1
    except Exception as exc:
        print(json.dumps({
            "status": "CONNECTION_FAILED",
            "mode": "public_read_only",
            "base_url": settings.bitunix_futures_base_url,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "hint": "Check DNS/network access, API base URL, and Bitunix service availability. No API key is required for public market endpoints.",
            "private_api_tested": False,
            "trading_enabled": False,
        }, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
