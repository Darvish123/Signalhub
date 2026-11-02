"""Event-driven multi-symbol portfolio backtest with shared equity and open-risk limits.

Per-symbol candidate generation reuses the single-symbol engine; portfolio accounting
then accepts/rejects entries chronologically against one shared equity pool.
"""
from __future__ import annotations
from app.backtest import run_backtest

def run_portfolio_backtest(
    candles_by_symbol: dict[str, list],
    funding_by_symbol: dict[str, list],
    start_ms: int,
    end_ms: int,
    fee_bps: float = 5.0,
    slippage_bps: float = 2.0,
    risk_pct: float = 0.5,
    max_leverage: float = 1.0,
    initial_equity: float = 100.0,
    max_positions: int = 5,
    max_open_risk_pct: float = 2.0,
    lower_tf_by_symbol: dict[str, list] | None = None,
) -> dict:
    if not candles_by_symbol:
        raise ValueError("At least one symbol dataset is required")
    if max_positions < 1 or not 0 < max_open_risk_pct <= 10:
        raise ValueError("Invalid portfolio position or risk limits")
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")

    candidates = []
    symbol_reports = {}
    for symbol, candles in sorted(candles_by_symbol.items()):
        report = run_backtest(
            candles, symbol, start_ms, end_ms, fee_bps, slippage_bps,
            risk_pct, max_leverage=max_leverage,
            funding_rates=funding_by_symbol.get(symbol, []),
            initial_equity=initial_equity,
            lower_tf_candles=(lower_tf_by_symbol or {}).get(symbol),
        )
        symbol_reports[symbol] = {
            "candidate_trades": report["trades"].__len__(),
            "funding_records_loaded": report["funding_records_loaded"],
            "funding_settlements_in_test_window": report["funding_settlements_in_test_window"],
            "signal_diagnostics": report.get("signal_diagnostics", {}),
        }
        candidates.extend(report["trades"])

    candidates.sort(key=lambda t: (t["entry_time_ms"], t["symbol"]))
    active = []
    accepted = []
    rejected = []
    equity = initial_equity
    peak = equity
    max_drawdown = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    wins = losses = 0
    equity_curve = [{"time_ms": start_ms, "equity": round(equity, 8)}]

    def close_until(timestamp: int) -> None:
        nonlocal equity, peak, max_drawdown, gross_profit, gross_loss, wins, losses, active
        closing = sorted([x for x in active if x["exit_time_ms"] <= timestamp],
                         key=lambda x: (x["exit_time_ms"], x["symbol"]))
        for trade in closing:
            pnl = trade["portfolio_equity_at_entry"] * trade["equity_pnl_pct"] / 100.0
            equity += pnl
            if pnl > 0:
                gross_profit += pnl
                wins += 1
            else:
                gross_loss += abs(pnl)
                losses += 1
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)
            equity_curve.append({"time_ms": trade["exit_time_ms"], "equity": round(equity, 8)})
            active.remove(trade)

    for trade in candidates:
        close_until(trade["entry_time_ms"])
        stop_distance = abs(trade["entry"] - trade["stop"]) / trade["entry"]
        round_trip_cost_pct = 2.0 * (fee_bps + slippage_bps) / 10_000.0
        risk_on_equity_pct = trade["position_fraction"] * (stop_distance + round_trip_cost_pct) * 100.0
        current_open_risk = sum(x["_risk_pct"] for x in active)
        reason = None
        if len(active) >= max_positions:
            reason = "MAX_CONCURRENT_POSITIONS"
        elif current_open_risk + risk_on_equity_pct > max_open_risk_pct + 1e-9:
            reason = "PORTFOLIO_OPEN_RISK_LIMIT"
        if reason:
            rejected.append({"symbol": trade["symbol"], "entry_time_ms": trade["entry_time_ms"],
                             "reason": reason, "risk_pct": round(risk_on_equity_pct, 5)})
            continue
        item = dict(trade)
        item["_risk_pct"] = risk_on_equity_pct
        item["portfolio_equity_at_entry"] = round(equity, 8)
        accepted.append(item)
        active.append(item)

    close_until(2**63 - 1)
    for item in accepted:
        item.pop("_risk_pct", None)
        item["portfolio_pnl_quote"] = round(
            item["portfolio_equity_at_entry"] * item["equity_pnl_pct"] / 100.0, 8
        )
    total = len(accepted)
    return {
        "model": "shared_equity_event_driven_portfolio",
        "symbols": sorted(candles_by_symbol),
        "period_start_ms": start_ms,
        "period_end_ms": end_ms,
        "initial_equity": initial_equity,
        "final_equity": round(equity, 8),
        "net_pnl_quote": round(equity - initial_equity, 8),
        "net_return_pct": round((equity / initial_equity - 1) * 100.0, 5),
        "accepted_trades": total,
        "rejected_candidates": len(rejected),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / total * 100.0, 3) if total else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (
            "infinite" if gross_profit else None
        ),
        "max_drawdown_pct": round(max_drawdown * 100.0, 5),
        "max_drawdown_basis": "realized equity at closed-trade exits; excludes intra-trade unrealized mark-to-market drawdown",
        "max_positions": max_positions,
        "max_open_risk_pct": max_open_risk_pct,
        "risk_pct_per_trade": risk_pct,
        "max_leverage": max_leverage,
        "fee_bps_per_side": fee_bps,
        "slippage_bps_per_side": slippage_bps,
        "symbol_data_audit": symbol_reports,
        "equity_curve": equity_curve,
        "trades": accepted,
        "rejections": rejected,
        "limitations": [
            "Signals are generated independently per symbol, then portfolio entries are allocated chronologically.",
            "15m Price Action is only included when a validated lower_tf_by_symbol dataset is supplied.",
            "No cross-symbol correlation, liquidation engine, maintenance margin tiers or exchange-specific portfolio margin.",
            "Candidate trades are simulated with the same per-trade risk fraction; portfolio equity is shared at realized PnL accounting.",
            "Funding completeness must be audited against the exchange settlement schedule for every symbol."
        ],
    }
