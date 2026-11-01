"""Strict OHLCV validation and quarantine utilities; never repair market prices silently."""
from dataclasses import asdict, dataclass
import math
from app.models import Candle

@dataclass(frozen=True)
class CandleIssue:
    time_ms: int
    reasons: tuple[str, ...]

def candle_issues(c: Candle) -> list[str]:
    reasons=[]
    values={"open":c.open,"high":c.high,"low":c.low,"close":c.close,
            "quote_volume":c.quote_volume,"base_volume":c.base_volume}
    for name,value in values.items():
        if not math.isfinite(value): reasons.append(f"{name}_non_finite")
    if any(not math.isfinite(v) for v in (c.open,c.high,c.low,c.close,c.quote_volume,c.base_volume)):
        return reasons
    if min(c.open,c.high,c.low,c.close)<=0: reasons.append("non_positive_price")
    if c.high < max(c.open,c.close,c.low): reasons.append("high_below_ohlc_component")
    if c.low > min(c.open,c.close,c.high): reasons.append("low_above_ohlc_component")
    if c.quote_volume<0: reasons.append("negative_quote_volume")
    if c.base_volume<0: reasons.append("negative_base_volume")
    return reasons

def audit_candles(candles: list[Candle], interval_ms: int) -> dict:
    if interval_ms<=0: raise ValueError("interval_ms must be positive")
    ordered=sorted(candles,key=lambda x:x.time_ms)
    duplicate_times=set()
    seen=set()
    for c in ordered:
        if c.time_ms in seen: duplicate_times.add(c.time_ms)
        seen.add(c.time_ms)
    invalid=[CandleIssue(c.time_ms,tuple(candle_issues(c))) for c in ordered if candle_issues(c)]
    gaps=[]
    for a,b in zip(ordered,ordered[1:]):
        delta=b.time_ms-a.time_ms
        if delta!=interval_ms: gaps.append({"from_ms":a.time_ms,"to_ms":b.time_ms,"delta_ms":delta,
                                           "missing_intervals":max(0,delta//interval_ms-1)})
    return {"input_count":len(candles),"unique_count":len(seen),"duplicate_timestamps_ms":sorted(duplicate_times),
            "invalid_count":len(invalid),"invalid":[asdict(x) for x in invalid],"discontinuities":gaps,
            "accepted_count":len(ordered)-len(invalid)-len(duplicate_times),
            "policy":"quarantine invalid/duplicate rows; never normalize or interpolate OHLC"}

def validated_candles(candles: list[Candle], interval_ms: int) -> list[Candle]:
    report=audit_candles(candles,interval_ms)
    if report["invalid_count"] or report["duplicate_timestamps_ms"] or report["discontinuities"]:
        raise ValueError(f"Market data quality gate failed: invalid={report['invalid_count']}, "
                         f"duplicates={len(report['duplicate_timestamps_ms'])}, "
                         f"discontinuities={len(report['discontinuities'])}")
    return sorted(candles,key=lambda x:x.time_ms)
