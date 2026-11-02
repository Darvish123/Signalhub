#!/usr/bin/env python3
"""Reproducible two-year SignalHub futures portfolio backtest.

Bitunix OHLC history contains malformed bars, while Binance/Bybit public APIs
were region-blocked from the GitHub Actions runner. This runner uses OKX linear
perpetual historical OHLCV as the price/volume benchmark and Bitunix historical
funding/mark prices for target-venue funding. No keys or order endpoints are used.
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

from app.config import settings
from app.exchange import BitunixClient
from app.funding import FundingRate, download_funding, save_funding_csv
from app.models import Candle
from app.portfolio import run_portfolio_backtest
from app.data_quality import audit_candles, validated_candles

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "LINKUSDT", "LTCUSDT", "BCHUSDT",
]
BASE_URL = "https://www.okx.com"
HOUR_MS = 3_600_000
M15_MS = 900_000
DAY_MS = 24 * HOUR_MS


def parse_utc_date(value: str) -> int:
    parsed = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def okx_inst_id(symbol: str) -> str:
    return symbol.removesuffix("USDT") + "-USDT-SWAP"


async def okx_data(client: httpx.AsyncClient, path: str, params: dict) -> list:
    url = BASE_URL + path
    for attempt in range(5):
        try:
            response = await client.get(url, params=params)
            if response.status_code in (418, 429):
                await asyncio.sleep(float(response.headers.get("Retry-After", 1 + attempt)))
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or str(payload.get("code")) != "0":
                raise RuntimeError(f"OKX API error: {payload}")
            return payload.get("data", [])
        except (httpx.HTTPError, ValueError) as exc:
            if attempt == 4:
                raise RuntimeError(f"OKX request failed: {exc}") from exc
            await asyncio.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(f"OKX request retries exhausted for {path}")


async def download_history(
    client: httpx.AsyncClient, symbol: str, start_ms: int, end_exclusive_ms: int,
    bar: str = "1H", interval_ms: int = HOUR_MS,
) -> list[Candle]:
    """Download confirmed OKX history candles, paging backwards without gaps."""
    inst_id = okx_inst_id(symbol)
    cursor = end_exclusive_ms
    records: dict[int, Candle] = {}
    pages = 0
    while cursor > start_ms:
        pages += 1
        if pages > 1200:
            raise RuntimeError(f"{symbol} {bar}: candle pagination exceeded safety page limit")
        rows = await okx_data(client, "/api/v5/market/history-candles", {
            "instId": inst_id, "bar": bar, "after": str(cursor), "limit": "100",
        })
        if not rows:
            break
        eligible = []
        for row in rows:
            if len(row) < 9:
                raise RuntimeError(f"{symbol}: malformed OKX candle row: {row}")
            t = int(row[0])
            if start_ms <= t < cursor:
                if str(row[8]) != "1":
                    raise RuntimeError(f"{symbol}: unconfirmed historical OKX candle at {t}")
                candle = Candle(
                    t, float(row[1]), float(row[2]), float(row[3]), float(row[4]),
                    float(row[7]), float(row[5]),
                )
                if not candle.valid():
                    raise RuntimeError(f"{symbol}: invalid OKX OHLCV candle at {t}: {row}")
                records[t] = candle
                eligible.append(t)
        if not eligible:
            break
        oldest = min(eligible)
        if oldest >= cursor:
            raise RuntimeError(f"{symbol}: OKX candle pagination made no progress")
        cursor = oldest
        await asyncio.sleep(0.11)

    result = [records[t] for t in sorted(records)]
    if not result:
        raise RuntimeError(f"{symbol}: no OKX {bar} history returned")
    return result


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
        "- Price/volume: **OKX linear perpetual OHLCV**; funding: **Bitunix historical funding**",
        f"- Initial capital: **$ {result['initial_equity']:,.2f}**",
        f"- Final capital: **$ {result['final_equity']:,.2f}**",
        f"- Net PnL: **$ {result['net_pnl_quote']:,.2f} ({result['net_return_pct']:.2f}%)**",
        f"- Trades: **{result['accepted_trades']} accepted**, {result['rejected_candidates']} candidates rejected by portfolio limits",
        f"- Wins / losses: **{result['wins']} / {result['losses']}**",
        f"- Win rate: **{result['win_rate_pct']:.2f}%**",
        f"- Profit factor: **{result['profit_factor']}**",
        f"- Maximum realized drawdown (closed trades only): **{result['max_drawdown_pct']:.2f}%**",
        f"- Drawdown basis: {result.get('max_drawdown_basis', 'not specified')}",
        "",
        "## Assumptions and limitations",
        "",
        "- Strategy: repository backtest implementation (1D bias + 4H structure + 1H SMC/ICT trigger).",
        "- Execution: next 1H OKX open; max holding period 48 hourly bars; stop is assumed hit before target if both touch in one candle.",
        "- Risk: 0.5% risk budget per trade, 2x maximum leverage, maximum 5 concurrent positions and 2% portfolio open-risk cap.",
        "- Costs: 5 bps fee + 2 bps slippage per side; Bitunix historical funding and mark prices applied at recorded settlements.",
        "- Cross-venue limitation: OHLCV comes from OKX while funding comes from Bitunix. Price, liquidity and execution may differ from Bitunix. This is a benchmark, not an exact Bitunix simulation.",
        "- The 15m Price Action filter is now applied to historical entries using only fully closed 15m candles at each hourly decision point.",
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
        "## Signal rejection diagnostics",
        "",
        "Counts below explain why hourly evaluations did not become entries. They are diagnostic counts, not trade counts.",
        "",
        "| Symbol | Rejection reason | Count |",
        "|---|---|---:|",
    ])
    for symbol, row in result["symbol_data_audit"].items():
        for reason, count in row.get("signal_diagnostics", {}).items():
            lines.append(f"| {symbol} | {reason.replace('|', '/') } | {count} |")
    lines.extend([
        "",
        "## Data integrity",
        "",
        "| Symbol | 1H candles | 15m candles | Candle audit (1H/15m) | Bitunix funding records | Funding audit |",
        "|---|---:|---:|---|---:|---|",
    ])
    for symbol, row in data_audit.items():
        lines.append(
            f"| {symbol} | {row['candles']} | {row['candles_15m']} | {row['candle_status']} "
            f"(1H gaps: {row['candle_gaps']}; 15m gaps: {row['candle_gaps_15m']}) | {row['funding']['records']} | {row['funding']['status']} |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "This is a historical simulation, not a forecast or proof of future profitability. "
        "Any failed data/funding audit invalidates the result. The strategy score is not a calibrated win probability.",
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

    bitunix_client = BitunixClient(
        settings.bitunix_futures_base_url,
        settings.bitunix_spot_base_url,
        settings.request_timeout_seconds,
    )
    async with httpx.AsyncClient(timeout=25.0) as client:
        for symbol in symbols:
            instruments = await okx_data(client, "/api/v5/public/instruments", {
                "instType": "SWAP", "instId": okx_inst_id(symbol),
            })
            if not any(
                row.get("instId") == okx_inst_id(symbol)
                and row.get("state") == "live"
                and row.get("settleCcy") == "USDT"
                for row in instruments
            ):
                raise RuntimeError(f"{symbol}: OKX USDT linear perpetual is not live")
            await asyncio.sleep(0.11)

        candles_by_symbol: dict[str, list[Candle]] = {}
        lower_tf_by_symbol: dict[str, list[Candle]] = {}
        funding_by_symbol: dict[str, list[FundingRate]] = {}
        audit: dict[str, dict] = {}
        raw_dir = Path("artifacts/historical_data")
        for index, symbol in enumerate(symbols, start=1):
            print(f"[{index}/10] Downloading {symbol} OKX 1h history candles...", flush=True)
            candles = await download_history(client, symbol, warmup_start, test_end, "1H", HOUR_MS)
            candle_audit = audit_candles(candles, HOUR_MS)
            if candles[0].time_ms > warmup_start or candles[-1].time_ms < test_end - HOUR_MS:
                raise RuntimeError(f"{symbol}: historical candle boundary coverage is incomplete")
            if candle_audit["invalid_count"] or candle_audit["duplicate_timestamps_ms"] or candle_audit["discontinuities"]:
                raise RuntimeError(
                    f"{symbol}: candle quality gate failed: {json.dumps(candle_audit)}"
                )
            candles_by_symbol[symbol] = validated_candles(candles, HOUR_MS)
            save_candles(candles, raw_dir / f"{symbol}_1h.csv")

            print(f"[{index}/10] Downloading {symbol} OKX 15m history candles...", flush=True)
            lower_rows = await download_history(client, symbol, warmup_start, test_end, "15m", M15_MS)
            lower_audit = audit_candles(lower_rows, M15_MS)
            if lower_rows[0].time_ms > warmup_start or lower_rows[-1].time_ms < test_end - M15_MS:
                raise RuntimeError(f"{symbol}: 15m historical candle boundary coverage is incomplete")
            if lower_audit["invalid_count"] or lower_audit["duplicate_timestamps_ms"] or lower_audit["discontinuities"]:
                raise RuntimeError(f"{symbol}: 15m candle quality gate failed: {json.dumps(lower_audit)}")
            lower_tf_by_symbol[symbol] = validated_candles(lower_rows, M15_MS)
            save_candles(lower_rows, raw_dir / f"{symbol}_15m.csv")

            print(f"[{index}/10] Downloading {symbol} Bitunix historical funding...", flush=True)
            funding = await download_funding(
                symbol, test_start, test_end,
                base_url=settings.bitunix_futures_base_url,
                timeout=settings.request_timeout_seconds,
            )
            if not funding:
                raise RuntimeError(f"{symbol}: no Bitunix historical funding data; refusing incomplete futures backtest")
            funding_by_symbol[symbol] = funding
            save_funding_csv(funding, raw_dir / f"{symbol}_funding.csv")
            funding_check = funding_audit(funding, test_start, test_end)
            if funding_check["status"] != "PASS":
                raise RuntimeError(f"{symbol}: Bitunix funding coverage audit failed: {json.dumps(funding_check)}")
            audit[symbol] = {
                "candles": len(candles),
                "candles_15m": len(lower_rows),
                "first_candle_utc": datetime.fromtimestamp(candles[0].time_ms / 1000, timezone.utc).isoformat(),
                "last_candle_utc": datetime.fromtimestamp(candles[-1].time_ms / 1000, timezone.utc).isoformat(),
                "candle_status": "PASS",
                "candle_gaps": len(candle_audit["discontinuities"]),
                "candle_gaps_15m": len(lower_audit["discontinuities"]),
                "candle_15m_status": "PASS",
                "price_source": "OKX linear perpetual history-candles",
                "funding_source": "Bitunix historical funding-rate API",
                "funding": funding_check,
            }

        print("Running shared-equity portfolio simulation...", flush=True)
        result = run_portfolio_backtest(
            candles_by_symbol=candles_by_symbol,
            funding_by_symbol=funding_by_symbol,
            lower_tf_by_symbol=lower_tf_by_symbol,
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
        "timeframe": "1H execution; 1D/4H/1H SMC with closed 15m Price Action trigger",
        "price_source": "OKX linear perpetual OHLCV",
        "funding_source": "Bitunix historical funding and mark price",
        "initial_equity_quote": args.initial_equity,
        "max_leverage": args.max_leverage,
        "risk_pct_per_trade": args.risk_pct,
        "max_positions": args.max_positions,
        "max_open_risk_pct": args.max_open_risk_pct,
        "fee_bps_per_side": args.fee_bps,
        "slippage_bps_per_side": args.slippage_bps,
        "warmup_days": 60,
        "time_exit_bars": 48,
        "15m_price_action_filter": "enabled; only fully closed OKX 15m candles are passed at each hourly decision",
        "execution_venue_limitation": "OKX OHLCV with Bitunix funding; cross-venue benchmark, not exact Bitunix fills",
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
