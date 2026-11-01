"""Read-only 500-candle BTCUSDT Futures data-quality audit for Bitunix."""
import asyncio
import json
import math
import os
import statistics
import time
from datetime import datetime, timezone

from app.config import settings
from app.exchange import BitunixClient, INTERVAL_MS

SYMBOL = "BTCUSDT"
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
PRICE_TYPES = ["LAST_PRICE", "MARK_PRICE"]
TARGET = 500
PAGE_SIZE = 200


def aligned_end(interval: str, now_ms: int) -> int:
    step = INTERVAL_MS[interval]
    return (now_ms // step) * step


def summarize(rows: list[dict], interval: str, price_type: str) -> dict:
    step = INTERVAL_MS[interval]
    parsed, malformed, invalid = [], [], []
    for row in rows:
        try:
            candle = {
                "time": int(row["time"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "quoteVol": float(row.get("quoteVol") or 0),
                "baseVol": float(row.get("baseVol") or 0),
            }
            vals = [candle[k] for k in ("open", "high", "low", "close", "quoteVol", "baseVol")]
            if not all(math.isfinite(v) for v in vals):
                invalid.append({"time": candle["time"], "reason": "non_finite"})
            elif min(candle[k] for k in ("open", "high", "low", "close")) <= 0:
                invalid.append({"time": candle["time"], "reason": "non_positive_price"})
            elif candle["high"] < max(candle["open"], candle["close"], candle["low"]):
                invalid.append({"time": candle["time"], "reason": "high_below_ohlc"})
            elif candle["low"] > min(candle["open"], candle["close"], candle["high"]):
                invalid.append({"time": candle["time"], "reason": "low_above_ohlc"})
            elif candle["quoteVol"] < 0 or candle["baseVol"] < 0:
                invalid.append({"time": candle["time"], "reason": "negative_volume"})
            parsed.append(candle)
        except (KeyError, TypeError, ValueError) as exc:
            malformed.append({"row": row, "error": str(exc)})

    parsed.sort(key=lambda x: x["time"])
    times = [x["time"] for x in parsed]
    duplicates = len(times) - len(set(times))
    gaps = [
        {"from": a, "to": b, "missing_intervals_estimate": max(0, round((b-a)/step)-1)}
        for a, b in zip(times, times[1:]) if b-a != step
    ]
    closes = [x["close"] for x in parsed]
    returns = [(b/a)-1 for a,b in zip(closes, closes[1:]) if a > 0]
    quote_vols = [x["quoteVol"] for x in parsed]
    base_vols = [x["baseVol"] for x in parsed]
    wicks = [
        ((x["high"]-x["low"])/x["open"])
        for x in parsed if x["open"] > 0
    ]
    return {
        "symbol": SYMBOL, "interval": interval, "price_type": price_type,
        "requested": TARGET, "received": len(rows), "parsed": len(parsed),
        "malformed_rows": malformed, "invalid_ohlc_or_volume": invalid,
        "duplicate_timestamps": duplicates, "timestamp_discontinuities": gaps,
        "first_candle_open_utc": datetime.fromtimestamp(times[0]/1000, timezone.utc).isoformat() if times else None,
        "last_candle_open_utc": datetime.fromtimestamp(times[-1]/1000, timezone.utc).isoformat() if times else None,
        "expected_interval_ms": step,
        "close_first": closes[0] if closes else None,
        "close_last": closes[-1] if closes else None,
        "return_first_to_last_pct": ((closes[-1]/closes[0])-1)*100 if len(closes)>1 else None,
        "max_abs_single_candle_return_pct": max((abs(x)*100 for x in returns), default=None),
        "median_abs_single_candle_return_pct": statistics.median(abs(x)*100 for x in returns) if returns else None,
        "quote_volume_sum": sum(quote_vols),
        "base_volume_sum": sum(base_vols),
        "zero_quote_volume_candles": sum(v == 0 for v in quote_vols),
        "zero_base_volume_candles": sum(v == 0 for v in base_vols),
        "max_high_low_range_pct_of_open": max((x*100 for x in wicks), default=None),
        "quality_pass": len(rows) == TARGET and len(parsed) == TARGET and not malformed and not invalid and not duplicates and not gaps,
        "invalid_examples": invalid[:20],
        "gap_examples": gaps[:20],
    }


async def main():
    client = BitunixClient(settings.bitunix_futures_base_url, settings.bitunix_spot_base_url, settings.request_timeout_seconds)
    now_ms = int(time.time()*1000)
    output = {
        "audit": "Bitunix BTCUSDT Futures market data",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": SYMBOL, "target_candles_per_series": TARGET,
        "timeframes": TIMEFRAMES, "price_types": PRICE_TYPES,
        "method": "REST kline pages <=200 rows using exclusive endTime aligned to timeframe open",
        "series": [], "snapshots": {}, "request_errors": [],
    }
    for interval in TIMEFRAMES:
        for price_type in PRICE_TYPES:
            rows, seen = [], set()
            end_time = aligned_end(interval, now_ms)
            while len(rows) < TARGET:
                limit = min(PAGE_SIZE, TARGET-len(rows))
                try:
                    page = await client._get(
                        f"{client.futures_base}/api/v1/futures/market/kline",
                        {"symbol": SYMBOL, "interval": interval, "endTime": end_time, "limit": limit, "type": price_type},
                    )
                    if not isinstance(page, list) or not page:
                        raise RuntimeError(f"empty/non-list page at endTime={end_time}")
                    page = sorted(page, key=lambda x: int(x["time"]))
                    new_rows = [x for x in page if int(x["time"]) not in seen]
                    if not new_rows:
                        raise RuntimeError(f"pagination made no progress at endTime={end_time}")
                    for row in new_rows:
                        seen.add(int(row["time"]))
                        rows.append(row)
                    oldest = min(int(x["time"]) for x in page)
                    end_time = oldest
                    if len(page) < limit:
                        break
                    await asyncio.sleep(0.15)
                except Exception as exc:
                    output["request_errors"].append({"interval": interval, "price_type": price_type, "error": str(exc)})
                    break
            rows.sort(key=lambda x: int(x["time"]))
            rows = rows[-TARGET:]
            output["series"].append({
                "summary": summarize(rows, interval, price_type),
                "raw_candles": rows,
            })
            print(f"{interval} {price_type}: {len(rows)}/{TARGET} candles")

    for name, path, params in [
        ("tickers", "/api/v1/futures/market/tickers", {"symbols": SYMBOL}),
        ("funding_rate", "/api/v1/futures/market/funding_rate", {"symbol": SYMBOL}),
        ("depth", "/api/v1/futures/market/depth", {"symbol": SYMBOL, "limit": "max"}),
        ("trading_pairs", "/api/v1/futures/market/trading_pairs", {"symbols": SYMBOL}),
    ]:
        try:
            output["snapshots"][name] = await client._get(f"{client.futures_base}{path}", params)
        except Exception as exc:
            output["request_errors"].append({"snapshot": name, "error": str(exc)})

    os.makedirs("artifacts", exist_ok=True)
    with open("artifacts/bitunix_btc_market_audit.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(json.dumps({
        "artifact": "artifacts/bitunix_btc_market_audit.json",
        "series": [x["summary"] for x in output["series"]],
        "snapshots_ok": list(output["snapshots"]),
        "request_errors": output["request_errors"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
