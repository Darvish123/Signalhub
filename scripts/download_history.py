"""Download continuous public Bitunix Futures OHLCV history using endTime pagination.

Bitunix documents endTime as an exclusive candle-open-time bound; startTime is
not supported. This script pages backwards in batches of at most 200 candles.
"""
import argparse
import asyncio
import csv
import time
from pathlib import Path

import httpx

INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "8h": 28_800_000, "12h": 43_200_000,
    "1d": 86_400_000,
}


async def download(symbol: str, interval: str, start_ms: int, end_ms: int,
                   base_url: str, timeout: float = 15.0) -> list[dict]:
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported interval: {interval}")
    if start_ms >= end_ms:
        raise ValueError("start must be before end")
    step = INTERVAL_MS[interval]
    if start_ms % step or end_ms % step:
        raise ValueError("start/end must align to the interval open time")

    url = base_url.rstrip("/") + "/api/v1/futures/market/kline"
    rows_by_time: dict[int, dict] = {}
    cursor = end_ms + step  # exclusive bound includes the requested end candle
    async with httpx.AsyncClient(timeout=timeout) as client:
        while cursor > start_ms:
            response = await client.get(url, params={
                "symbol": symbol.upper(), "interval": interval,
                "endTime": cursor, "limit": 200, "type": "LAST_PRICE",
            })
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or str(payload.get("code")) not in ("0", "200"):
                raise RuntimeError(f"Bitunix API error: {payload}")
            batch = payload.get("data")
            if not isinstance(batch, list) or not batch:
                break
            times = []
            for item in batch:
                t = int(item["time"])
                times.append(t)
                if start_ms <= t <= end_ms:
                    row = {
                        "timestamp_ms": t, "open": float(item["open"]),
                        "high": float(item["high"]), "low": float(item["low"]),
                        "close": float(item["close"]),
                        "quote_volume": float(item.get("quoteVol") or 0),
                        "base_volume": float(item.get("baseVol") or 0),
                    }
                    if not (row["low"] > 0 and row["high"] >= max(row["open"], row["close"], row["low"])
                            and row["low"] <= min(row["open"], row["close"], row["high"])):
                        raise ValueError(f"Invalid OHLC candle at {t}")
                    rows_by_time[t] = row
            oldest = min(times)
            if oldest >= cursor:
                raise RuntimeError("Pagination did not move backwards; aborting to avoid an infinite loop")
            cursor = oldest
            await asyncio.sleep(0.12)  # stay comfortably below the documented 10 req/s limit
    rows = [rows_by_time[t] for t in sorted(rows_by_time)]
    expected = (end_ms - start_ms) // step + 1
    if len(rows) != expected:
        missing = expected - len(rows)
        raise RuntimeError(f"History incomplete: expected {expected} candles, received {len(rows)} ({missing} missing)")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Download public Bitunix Futures candles to CSV")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="15m", choices=sorted(INTERVAL_MS))
    parser.add_argument("--start-ms", type=int, required=True, help="Inclusive interval-aligned candle open time (UTC)")
    parser.add_argument("--end-ms", type=int, required=True, help="Inclusive interval-aligned candle open time (UTC)")
    parser.add_argument("--base-url", default="https://fapi.bitunix.com")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    rows = asyncio.run(download(args.symbol, args.interval, args.start_ms, args.end_ms, args.base_url))
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "timestamp_ms", "open", "high", "low", "close", "quote_volume", "base_volume"
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} continuous {args.interval} candles to {path}")


if __name__ == "__main__":
    main()
