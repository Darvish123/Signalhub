#!/usr/bin/env python3
"""Reproducible two-year SignalHub futures portfolio backtest.

The Bitunix historical OHLC endpoint returned malformed candles, including
malformed MARK_PRICE bars. This runner therefore uses Binance USDⓈ-M perpetual
OHLCV and funding as an explicitly disclosed cross-venue benchmark. No keys or
order endpoints are used.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest import HOUR_MS if False else None
from app.funding import FundingRate, save_funding_csv
from app.models import Candle
from app.portfolio import run_portfolio_backtest
from app.data_quality import audit_candles, validated_candles

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "LINKUSDT", "LTCUSDT", "BCHUSDT",
]
BASE_URL = "https://fapi.binance.com"
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS


def parse_utc_date(value: str) -> int:
    parsed = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


async def get_json(client: httpx.AsyncClient, path: str, params: dict | None = None):
    url = BASE_URL + path
    for attempt in range(5):
        try:
            response = await client.get(url, params=params)
            if response.status_code in (418, 429):
                delay = float(response.headers.get("Retry-After", 1 + attempt * 2))
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload.get("code") not in (None, 0, "0"):
                raise RuntimeError(f"Binance API error: {payload}")
            return payload
        except (httpx.HTTPError, ValueError) as exc:
            if attempt == 4:
                raise RuntimeError(f"Binance request failed: {exc}") from exc
            await asyncio.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(f"Binance request retries exhausted for {path}")


async def download_hourly(
    client: httpx.AsyncClient, symbol: str, start_ms: int, end_exclusive_ms: int
) -> list[Candle]:
    """Download all 1H USDT-M perpetual klines in chronological pages."""
    cursor = start_ms
    records: dict[int, Candle] = {}
    pages = 0
    while cursor < end_exclusive_ms:
        pages += 1
        if pages > 100:
            raise RuntimeError(f"{symbol}: candle pagination exceeded safety page limit")
        rows = await get_json(client, "/fapi/v1/klines", {
            "symbol": symbol,
            "interval": "1h",
            "startTime": cursor,
            "endTime": end_exclusive_ms - 1,
            "limit": 1500,
        })
        if not isinstance(rows, list) or not rows:
            break
        parsed = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 8:
                raise RuntimeError(f"{symbol}: malformed Binance kline row: {row}")
            t = int(row[0])
            if start_ms <= t < end_exclusive_ms:
                candle = Candle(
                    t, float(row[1]), float(row[2]), float(row[3]), float(row[4]),
                    float(row[7]), float(row[5]),
                )
                if not candle.valid():
                    raise RuntimeError(f"{symbol}: invalid Binance OHLCV candle at {t}: {row}")
                records[t] = candle
                parsed.append(t)
        if not parsed:
            break
        newest = max(parsed)
        if newest < cursor:
            raise RuntimeError(f"{symbol}: Binance candle pagination made no progress")
        cursor = newest + HOUR_MS
        await asyncio.sleep(0.08)

    result = [records[t] for t in sorted(records)]
    if not result:
        raise RuntimeError(f"{symbol}: no Binance 1H history returned")
    return result


async def download_funding(
    client: httpx.AsyncClient, symbol: str, start_ms: int, end_exclusive_ms: int
) -> list[FundingRate]:
    """Download historical Binance funding settlements in 1,000-row pages."""
    cursor = start_ms
    records: dict[int, FundingRate] = {}
    pages = 0
    while cursor < end_exclusive_ms:
        pages += 1
        if pages > 20:
            raise RuntimeError(f"{symbol}: funding pagination exceeded safety page limit")
        rows = await get_json(client, "/fapi/v1/fundingRate", {
            "symbol": symbol,
            "startTime": cursor,
            "endTime": end_exclusive_ms - 1,
            "limit": 1000,
        })
        if not isinstance(rows, list):
            raise RuntimeError(f"{symbol}: malformed Binance funding response")
        if not rows:
            break
        times = []
        for row in rows:
            t = int(row["fundingTime"])
            mark = float(row.get("markPrice") or 0)
            rate = float(row["fundingRate"])
            if start_ms <= t < end_exclusive_ms:
                if mark <= 0:
                    raise RuntimeError(f"{symbol}: invalid funding mark price at {t}")
                records[t] = FundingRate(t, rate, mark)
                times.append(t)
        if not times:
            break
        newest = max(times)
        if newest < cursor:
            raise RuntimeError(f"{symbol}: funding pagination made no progress")
        cursor = newest + 1
        await asyncio.sleep(0.08)
        if len(rows) < 1000:
            break
    return [records[t] for t in sorted(records)]


def save_candles(rows: list[Candle], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp_ms", "open", "high", "low", "close",
                "quote_volume", "base_volume",
            ],
        )
        writer.writeheader()
        for c in rows:
            writer.writerow({
                "timestamp_ms": c.time_ms, "open": c.open, "high": c.high,
                "low": c.low, "close": c.close, "quote_volume": c.quote_volume,
                "base_volume": c.base_volume,
            })


def funding_audit(rows: list[FundingRate], start_ms: int, end_ms: int) -> dict:
    times = [x.funding_time_ms for x in rows]
    gaps = [b - a for a, b in zip(times, times[1:])]
    median_gap = int(statistics.median(gaps)) if gaps else None
    boundary_ok = bool(times) and times[0] <= start_ms + DAY_MS and times[-1] >= end_ms - DAY_MS
    gap_ok = bool(gaps) and max(gaps) <= max(3 * median_gap, 2 * DAY_MS)
    return {
        "records": len(rows),
        "first_funding_utc": datetime.fromtimestamp(times[0] / 1000, timezone.utc).isoformat() if times else None,
        "last_funding_utc": datetime.fromtimestamp(times[-1] / 1000, timezone.utc).isoformat() if times else None,
        "median_settlement_gap_hours": round(median_gap / HOUR_MS, 3) if median_gap else None,
        "max_settlement_gap_hours": round(max(gaps) / HOUR_MS, 3) if gaps else None,
        "boundary_coverage_ok": boundary_ok,
        "gap_audit_ok": gap_ok,
        "status": "PASS" if boundary_ok and gap_ok else "REVIEW_REQUIRED",
    }


def write_report(result: dict, data_audit: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "portfolio-report.json").write_text(
        json.dumps({"portfolio": result, "data_audit": data_audit}, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# SignalHub two-year futures backtest",
        "",
        f"- Test window: {result['test_window_utc']['start']} to {result['test_window_utc']['end']} (UTC, end exclusive)",
        "- Market data: **Binance USDⓈ-M perpetuals** (cross-venue benchmark; not Bitunix fills)",
        f"- Initial capital: **$ {result['initial_equity']:,.2f}**",
        f"- Final capital: **$ {result['final_equity']:,.2f}**",
        f"- Net PnL: **$ {result['net_pnl_quote']:,.2f} ({result['net_return_pct']:.2f}%)**",
        f"- Trades: **{result['accepted_trades']} accepted**, {result['rejected_candidates']} candidates rejected by portfolio limits",
        f"- Wins / losses: **{result['wins']} / {result['losses']}**",
        f"- Win rate: **{result['win_rate_pct']:.2f}%**",
        f"- Profit factor: **{result['profit_factor']}**",
        f"- Maximum drawdown: **{result['max_drawdown_pct']:.2f}%**",
        "",
        "## Assumptions and limitations",
        "",
        "- Strategy: repository backtest implementation (1D bias + 4H structure + 1H SMC/ICT trigger).",
        "- Execution: next 1H open; max holding period 48 hourly bars; stop is assumed hit before target if both touch in one candle.",
        "- Risk: 0.5% risk budget per trade, 2x maximum leverage, maximum 5 concurrent positions and 2% portfolio open-risk cap.",
        "- Costs: 5 bps fee + 2 bps slippage per side; Binance historical funding rates applied at recorded settlements.",
        "- The 15m Price Action filter in the live scan path is not present in the current historical backtest implementation.",
        "- Cross-venue limitation: prices, funding, liquidity and execution may differ from Bitunix. This is a benchmark, not an exact Bitunix simulation.",
        "- No liquidation engine, maintenance-margin tiers, cross-symbol correlation model or intrabar order-book simulation.",
        "",
        "## Per-symbol performance",
        "",
        "| Symbol | Candidate trades | Accepted | Wins | Losses | Net PnL ($) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for symbol, row in result["per_symbol_performance"].items():
        lines.append(
            f"| {symbol} | {row['candidate_trades']} | {row['accepted_trades']} | "
            f"{row['wins']} | {row['losses']} | {row['net_pnl_quote']:.2f} |"
        )
    lines.extend([
        "",
        "## Data integrity",
        "",
        "| Symbol | 1H candles | Candle audit | Funding records | Funding audit |",
        "|---|---:|---|---:|---|",
    ])
    for symbol, row in data_audit.items():
        lines.append(
            f"| {symbol} | {row['candles']} | {row['candle_status']} "
            f"(gaps: {row['candle_gaps']}) | {row['funding']['records']} | {row['funding']['status']} |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "This is a historical simulation, not a forecast or proof of future profitability. "
        "A result with any failed data/funding audit must be treated as provisional. "
        "The strategy score is not a calibrated win probability.",
        "",
    ])
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")


async def run(args: argparse.Namespace) -> None:
    symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    if len(symbols) != 10 or len(set(symbols)) != 10:
        raise ValueError("Exactly 10 unique symbols are required")

    test_start = parse_utc_date(args.start)
    test_end = parse_utc_date(args.end)
    if test_end <= test_start + 100 * DAY_MS:
        raise ValueError("Backtest period is too short")
    warmup_start = test_start - 60 * DAY_MS
    decision_end = test_end - 48 * HOUR_MS

    async with httpx.AsyncClient(timeout=25.0) as client:
        exchange_info = await get_json(client, "/fapi/v1/exchangeInfo")
        tradable = {
            row["symbol"] for row in exchange_info.get("symbols", [])
            if row.get("status") == "TRADING"
            and row.get("contractType") == "PERPETUAL"
            and row.get("quoteAsset") == "USDT"
        }
        missing = sorted(set(symbols) - tradable)
        if missing:
            raise RuntimeError(f"Requested Binance USDT perpetuals unavailable: {missing}")

        candles_by_symbol: dict[str, list[Candle]] = {}
        funding_by_symbol: dict[str, list[FundingRate]] = {}
        audit: dict[str, dict] = {}
        raw_dir = Path("artifacts/historical_data")
        for index, symbol in enumerate(symbols, start=1):
            print(f"[{index}/10] Downloading {symbol} Binance 1h perpetual candles...", flush=True)
            candles = await download_hourly(client, symbol, warmup_start, test_end)
            candle_audit = audit_candles(candles, HOUR_MS)
            if candles[0].time_ms > warmup_start or candles[-1].time_ms < test_end - HOUR_MS:
                raise RuntimeError(f"{symbol}: historical candle boundary coverage is incomplete")
            if candle_audit["invalid_count"] or candle_audit["duplicate_timestamps_ms"] or candle_audit["discontinuities"]:
                raise RuntimeError(
                    f"{symbol}: candle quality gate failed: {json.dumps(candle_audit)}"
                )
            candles_by_symbol[symbol] = validated_candles(candles, HOUR_MS)
            save_candles(candles, raw_dir / f"{symbol}_1h.csv")

            print(f"[{index}/10] Downloading {symbol} Binance historical funding...", flush=True)
            funding = await download_funding(client, symbol, test_start, test_end)
            if not funding:
                raise RuntimeError(f"{symbol}: no historical funding data; refusing incomplete futures backtest")
            funding_by_symbol[symbol] = funding
            save_funding_csv(funding, raw_dir / f"{symbol}_funding.csv")
            funding_check = funding_audit(funding, test_start, test_end)
            audit[symbol] = {
                "candles": len(candles),
                "first_candle_utc": datetime.fromtimestamp(candles[0].time_ms / 1000, timezone.utc).isoformat(),
                "last_candle_utc": datetime.fromtimestamp(candles[-1].time_ms / 1000, timezone.utc).isoformat(),
                "candle_status": "PASS",
                "candle_gaps": len(candle_audit["discontinuities"]),
                "price_source": "Binance USDⓈ-M perpetual klines",
                "funding_source": "Binance USDⓈ-M fundingRate history",
                "funding": funding_check,
            }

        print("Running shared-equity portfolio simulation...", flush=True)
        result = run_portfolio_backtest(
            candles_by_symbol=candles_by_symbol,
            funding_by_symbol=funding_by_symbol,
            start_ms=test_start,
            end_ms=decision_end,
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
            risk_pct=args.risk_pct,
            max_leverage=args.max_leverage,
            initial_equity=args.initial_equity,
            max_positions=args.max_positions,
            max_open_risk_pct=args.max_open_risk_pct,
        )

    per_symbol = {}
    for symbol in symbols:
        trades = [t for t in result["trades"] if t["symbol"] == symbol]
        rejected = [t for t in result["rejections"] if t["symbol"] == symbol]
        pnl = sum(t["portfolio_pnl_quote"] for t in trades)
        per_symbol[symbol] = {
            "candidate_trades": result["symbol_data_audit"][symbol]["candidate_trades"],
            "accepted_trades": len(trades),
            "wins": sum(t["portfolio_pnl_quote"] > 0 for t in trades),
            "losses": sum(t["portfolio_pnl_quote"] <= 0 for t in trades),
            "net_pnl_quote": round(pnl, 8),
            "portfolio_rejected": len(rejected),
        }

    result["per_symbol_performance"] = per_symbol
    result["test_window_utc"] = {
        "start": datetime.fromtimestamp(test_start / 1000, timezone.utc).isoformat(),
        "end": datetime.fromtimestamp(test_end / 1000, timezone.utc).isoformat(),
        "last_entry_decision_cutoff": datetime.fromtimestamp(decision_end / 1000, timezone.utc).isoformat(),
    }
    result["assumptions"] = {
        "symbols": symbols,
        "timeframe": "1H execution; 1D/4H/1H SMC strategy",
        "price_source": "Binance USDⓈ-M perpetual OHLCV",
        "funding_source": "Binance USDⓈ-M historical funding",
        "initial_equity_quote": args.initial_equity,
        "max_leverage": args.max_leverage,
        "risk_pct_per_trade": args.risk_pct,
        "max_positions": args.max_positions,
        "max_open_risk_pct": args.max_open_risk_pct,
        "fee_bps_per_side": args.fee_bps,
        "slippage_bps_per_side": args.slippage_bps,
        "warmup_days": 60,
        "time_exit_bars": 48,
        "15m_price_action_filter": "not included in current app.backtest.py implementation",
        "execution_venue_limitation": "Binance data used as cross-venue benchmark; not Bitunix exact fills",
    }
    output = Path(args.output)
    write_report(result, audit, output)
    print((output / "summary.md").read_text(encoding="utf-8"), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-10-30")
    parser.add_argument("--end", default="2026-10-30")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--initial-equity", type=float, default=1000.0)
    parser.add_argument("--max-leverage", type=float, default=2.0)
    parser.add_argument("--risk-pct", type=float, default=0.5)
    parser.add_argument("--max-positions", type=int, default=5)
    parser.add_argument("--max-open-risk-pct", type=float, default=2.0)
    parser.add_argument("--fee-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--output", default="artifacts/report")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
