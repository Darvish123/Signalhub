"""Pre-trade risk gate and deterministic position sizing for paper signals.

This module is advisory only: it never submits orders or reads exchange account balances.
All monetary sizing uses an explicitly configured paper equity amount.
"""
from dataclasses import asdict, dataclass
from math import isfinite
from app.models import Signal

@dataclass(frozen=True)
class RiskPlan:
    allowed: bool
    reason: str
    equity_quote: float
    risk_budget_quote: float
    entry: float | None
    stop_loss: float | None
    stop_distance_pct: float | None
    position_fraction: float
    notional_quote: float
    quantity: float
    gross_leverage: float
    estimated_stop_loss_quote: float
    estimated_round_trip_cost_quote: float
    estimated_total_loss_quote: float
    effective_risk_pct: float
    max_leverage: float

    def to_dict(self):
        return asdict(self)


def evaluate_signal_risk(signal: Signal, equity_quote: float = 1000.0,
                         risk_pct: float = 0.5, max_leverage: float = 1.0,
                         max_notional_quote: float = 0.0,
                         round_trip_cost_bps: float = 14.0) -> RiskPlan:
    """Fail closed unless signal geometry and all sizing constraints are valid.

    max_notional_quote=0 disables the absolute notional cap. Fees/slippage are
    estimated as an additional round-trip cost and included in the risk budget.
    """
    values = (equity_quote, risk_pct, max_leverage, max_notional_quote, round_trip_cost_bps)
    if not all(isfinite(float(x)) for x in values):
        raise ValueError("Risk configuration must contain finite numbers")
    if equity_quote <= 0 or not 0 < risk_pct <= 2 or not 0 < max_leverage <= 5:
        raise ValueError("Invalid equity, risk percentage or leverage cap")
    if max_notional_quote < 0 or round_trip_cost_bps < 0:
        raise ValueError("Notional cap and costs cannot be negative")
    base = dict(equity_quote=equity_quote, risk_budget_quote=equity_quote*risk_pct/100,
                entry=signal.entry, stop_loss=signal.stop_loss, stop_distance_pct=None,
                position_fraction=0.0, notional_quote=0.0, quantity=0.0,
                gross_leverage=0.0, estimated_stop_loss_quote=0.0,
                estimated_round_trip_cost_quote=0.0, estimated_total_loss_quote=0.0,
                effective_risk_pct=0.0, max_leverage=max_leverage)
    def reject(reason):
        return RiskPlan(False, reason, **base)
    if signal.status != "CANDIDATE" or signal.side not in ("LONG", "SHORT"):
        return reject("Signal is not an actionable directional candidate")
    entry, stop = signal.entry, signal.stop_loss
    if entry is None or stop is None or not isfinite(entry) or not isfinite(stop) or entry <= 0:
        return reject("Missing or invalid entry/stop")
    distance = (entry-stop)/entry if signal.side == "LONG" else (stop-entry)/entry
    if distance <= 0:
        return reject("Stop must be below LONG entry or above SHORT entry")
    risk_budget = equity_quote*risk_pct/100
    # Size against stop loss plus estimated round-trip friction, not stop distance alone.
    friction = round_trip_cost_bps/10000
    per_unit_loss = entry*(distance+friction)
    notional = min(risk_budget/(distance+friction), equity_quote*max_leverage)
    if max_notional_quote > 0:
        notional = min(notional, max_notional_quote)
    if notional <= 0:
        return reject("Calculated notional is zero")
    stop_loss_quote = notional*distance
    costs_quote = notional*friction
    total_loss = stop_loss_quote+costs_quote
    quantity = notional/entry
    fraction = notional/equity_quote
    effective = total_loss/equity_quote*100
    if total_loss > risk_budget+1e-8:
        return reject("Risk budget exceeded after costs")
    if fraction > max_leverage+1e-9:
        return reject("Maximum leverage exceeded")
    return RiskPlan(True, "Risk checks passed; paper sizing only", equity_quote,
        risk_budget, entry, stop, round(distance*100,6), round(fraction,8),
        round(notional,8), round(quantity,10), round(fraction,8),
        round(stop_loss_quote,8), round(costs_quote,8), round(total_loss,8),
        round(effective,6), max_leverage)
