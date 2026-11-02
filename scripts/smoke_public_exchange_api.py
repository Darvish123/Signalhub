#!/usr/bin/env python3
"""Read-only smoke test: Bitunix ticker universe + all live OKX timeframes + Bitunix candle diagnostics."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.exchange import BitunixClient, OKXClient, InvalidMarketDataError, validate_fresh_candles, INTERVAL_MS


async def probe(symbol: str) -> dict:
    bitunix = BitunixClient(
        settings.bitunix_futures_base_url,
        settings.bitunix_spot_base_url,
        settings.request_timeout_seconds,
    )
    okx = OKXClient(timeout=settings.request_timeout_seconds)
    result = {
        "symbol": symbol,
        "universe_source": "Bitunix public futures ticker API",
        "market_data_source": "OKX USDT linear perpetual candles",
        "ticker": {},
        "market_klines": {},
        "bitunix_kline_diagnostics": {},
    }
    try:
        tickers = await bitunix.futures_tickers()
        ticker = next((row for row in tickers if str(row.get("symbol", "")).upper() == symbol), None)
        result["ticker"] = {
            "status": "PASS" if ticker else "SYMBOL_NOT_FOUND",
            "ticker_count": len(tickers),
            "symbol_found": ticker is not None,
            "quote_volume": (ticker or {}).get("quoteVol"),
        }
    except Exception as exc:
        result["ticker"] = {"status": "ERROR", "error": str(exc)}

    now_ms = time.time_ns() // 1_000_000
    # These are exactly the four timeframes consumed by the live strategy.
    for interval in ("1d", "4h", "1h", "15m"):
        try:
            rows = await okx.futures_klines(symbol, interval, limit=100)
            validate_fresh_candles(rows, interval, now_ms)
            step = INTERVAL_MS[interval]
            closed = [row for row in rows if row.time_ms + step <= now_ms]
            validate_fresh_candles(closed, interval, now_ms)
            result["market_klines"][interval] = {
                "status": "PASS",
                "returned": len(rows),
                "closed": len(closed),
                "last_closed_time_ms": closed[-1].time_ms,
            }
        except Exception as exc:
            result["market_klines"][interval] = {"status": "ERROR", "error": str(exc)}

    # Bitunix candle checks remain diagnostic only; its malformed OHLC rows
    # must not silently become the primary market-data source.
    for interval in ("1h", "15m"):
        try:
            rows = await bitunix.futures_klines(symbol, interval, limit=100, strict_validation=True)
            validate_fresh_candles(rows, interval, now_ms)
            result["bitunix_kline_diagnostics"][interval] = {
                "status": "PASS", "returned": len(rows)
            }
        except InvalidMarketDataError as exc:
            result["bitunix_kline_diagnostics"][interval] = {
                "status": "INVALID_OHLCV",
                "invalid_count": len(exc.invalid),
                "returned": exc.total,
                "sample_invalid_rows": exc.invalid[:3],
            }
        except Exception as exc:
            result["bitunix_kline_diagnostics"][interval] = {
                "status": "ERROR", "error": str(exc)
            }

    result["overall"] = (
        "PASS"
        if result["ticker"].get("status") == "PASS"
        and all(item.get("status") == "PASS" for item in result["market_klines"].values())
        else "DEGRADED"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--output", default="artifacts/report/bitunix-public-api-smoke.json")
    args = parser.parse_args()
    report = asyncio.run(probe(args.symbol.upper()))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    if report["overall"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
