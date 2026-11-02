#!/usr/bin/env python3
"""Read-only Bitunix public API smoke test. Never uses private keys or order endpoints."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.exchange import BitunixClient, InvalidMarketDataError, validate_fresh_candles, INTERVAL_MS


async def probe(symbol: str) -> dict:
    client = BitunixClient(
        settings.bitunix_futures_base_url,
        settings.bitunix_spot_base_url,
        settings.request_timeout_seconds,
    )
    result = {"symbol": symbol, "source": "Bitunix public futures API", "ticker": {}, "klines": {}}
    try:
        tickers = await client.futures_tickers()
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
    for interval in ("1h", "15m"):
        try:
            rows = await client.futures_klines(symbol, interval, limit=100, strict_validation=True)
            validate_fresh_candles(rows, interval, now_ms)
            step = INTERVAL_MS[interval]
            closed = [row for row in rows if row.time_ms + step <= now_ms]
            validate_fresh_candles(closed, interval, now_ms)
            result["klines"][interval] = {
                "status": "PASS",
                "returned": len(rows),
                "closed": len(closed),
                "last_closed_time_ms": closed[-1].time_ms,
            }
        except InvalidMarketDataError as exc:
            result["klines"][interval] = {
                "status": "INVALID_OHLCV",
                "invalid_count": len(exc.invalid),
                "returned": exc.total,
                "sample_invalid_rows": exc.invalid[:3],
            }
        except Exception as exc:
            result["klines"][interval] = {"status": "ERROR", "error": str(exc)}

    result["overall"] = (
        "PASS"
        if result["ticker"].get("status") == "PASS"
        and all(item.get("status") == "PASS" for item in result["klines"].values())
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
