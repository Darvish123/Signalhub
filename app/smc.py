"""Deterministic, candle-based Smart Money Concepts (SMC) indicators.

These are descriptive heuristics, not proof of institutional activity or trade signals.
Only confirmed pivots are used for structure; FVGs and sweeps are candle-pattern rules.
"""
from dataclasses import asdict, dataclass
from typing import Literal
from app.models import Candle
from app.analysis import pivots

@dataclass(frozen=True)
class Swing:
    index: int
    time_ms: int
    price: float
    kind: Literal["HIGH", "LOW"]
    label: str

@dataclass(frozen=True)
class StructureEvent:
    index: int
    time_ms: int
    kind: Literal["BOS", "CHoCH"]
    direction: Literal["BULLISH", "BEARISH"]
    level: float
    close: float

@dataclass(frozen=True)
class LiquiditySweep:
    index: int
    time_ms: int
    direction: Literal["BULLISH", "BEARISH"]
    swept_level: float
    wick_extreme: float
    close: float
    reference_index: int

@dataclass(frozen=True)
class FairValueGap:
    index: int
    time_ms: int
    direction: Literal["BULLISH", "BEARISH"]
    lower: float
    upper: float
    size: float

@dataclass(frozen=True)
class OrderBlock:
    index: int
    time_ms: int
    direction: Literal["BULLISH", "BEARISH"]
    lower: float
    upper: float
    mitigation: str

def confirmed_swings(candles: list[Candle], left: int = 3, right: int = 3) -> list[Swing]:
    if left < 1 or right < 1:
        raise ValueError("left and right must be >= 1")
    highs, lows = pivots(candles, left, right)
    # Map pivot prices back to their candle indices; preserve chronological order.
    result: list[Swing] = []
    for i in range(left, len(candles) - right):
        c = candles[i]
        if c.high in highs:
            result.append(Swing(i, c.time_ms, c.high, "HIGH", ""))
        if c.low in lows:
            result.append(Swing(i, c.time_ms, c.low, "LOW", ""))
    result.sort(key=lambda x: (x.index, x.kind))
    last_high = last_low = None
    labelled = []
    for s in result:
        if s.kind == "HIGH":
            label = "HH" if last_high is not None and s.price > last_high else "LH" if last_high is not None else "H"
            last_high = s.price
        else:
            label = "HL" if last_low is not None and s.price > last_low else "LL" if last_low is not None else "L"
            last_low = s.price
        labelled.append(Swing(s.index, s.time_ms, s.price, s.kind, label))
    return labelled

def structure_events(candles: list[Candle], swings: list[Swing] | None = None, confirmation_bars: int = 3) -> list[StructureEvent]:
    if confirmation_bars < 0: raise ValueError("confirmation_bars must be >= 0")
    swings = swings if swings is not None else confirmed_swings(candles, right=confirmation_bars)
    highs = [s for s in swings if s.kind == "HIGH"]
    lows = [s for s in swings if s.kind == "LOW"]
    events: list[StructureEvent] = []
    trend: str | None = None
    broken_highs: set[int] = set()
    broken_lows: set[int] = set()
    for i, c in enumerate(candles):
        eligible_highs = [s for s in highs if s.index + confirmation_bars < i and s.index not in broken_highs]
        eligible_lows = [s for s in lows if s.index + confirmation_bars < i and s.index not in broken_lows]
        h = eligible_highs[-1] if eligible_highs else None
        l = eligible_lows[-1] if eligible_lows else None
        up = h is not None and c.close > h.price
        down = l is not None and c.close < l.price
        if up:
            kind = "CHoCH" if trend == "BEARISH" else "BOS"
            events.append(StructureEvent(i, c.time_ms, kind, "BULLISH", h.price, c.close))
            broken_highs.add(h.index); trend = "BULLISH"
        elif down:
            kind = "CHoCH" if trend == "BULLISH" else "BOS"
            events.append(StructureEvent(i, c.time_ms, kind, "BEARISH", l.price, c.close))
            broken_lows.add(l.index); trend = "BEARISH"
    return events

def liquidity_sweeps(candles: list[Candle], swings: list[Swing] | None = None, confirmation_bars: int = 3) -> list[LiquiditySweep]:
    if confirmation_bars < 0: raise ValueError("confirmation_bars must be >= 0")
    swings = swings if swings is not None else confirmed_swings(candles, right=confirmation_bars)
    out = []
    for i, c in enumerate(candles):
        prior = [s for s in swings if s.index + confirmation_bars < i]
        highs = [s for s in prior if s.kind == "HIGH" and c.high > s.price and c.close < s.price]
        lows = [s for s in prior if s.kind == "LOW" and c.low < s.price and c.close > s.price]
        if highs:
            s = highs[-1]
            out.append(LiquiditySweep(i,c.time_ms,"BEARISH",s.price,c.high,c.close,s.index))
        if lows:
            s = lows[-1]
            out.append(LiquiditySweep(i,c.time_ms,"BULLISH",s.price,c.low,c.close,s.index))
    return out

def fair_value_gaps(candles: list[Candle], min_gap: float = 0.0) -> list[FairValueGap]:
    if min_gap < 0: raise ValueError("min_gap must be >= 0")
    out = []
    for i in range(2, len(candles)):
        a, c = candles[i-2], candles[i]
        if c.low > a.high and c.low-a.high >= min_gap:
            out.append(FairValueGap(i,c.time_ms,"BULLISH",a.high,c.low,c.low-a.high))
        elif c.high < a.low and a.low-c.high >= min_gap:
            out.append(FairValueGap(i,c.time_ms,"BEARISH",c.high,a.low,a.low-c.high))
    return out

def order_blocks(candles: list[Candle], events: list[StructureEvent] | None = None, lookback: int = 10) -> list[OrderBlock]:
    if lookback < 1: raise ValueError("lookback must be >= 1")
    events = events if events is not None else structure_events(candles)
    out = []
    for event in events:
        start = max(0, event.index-lookback)
        candidates = range(event.index-1, start-1, -1)
        opposite = next((j for j in candidates if
            (candles[j].close < candles[j].open if event.direction == "BULLISH" else candles[j].close > candles[j].open)), None)
        if opposite is None: continue
        c = candles[opposite]
        out.append(OrderBlock(opposite,c.time_ms,event.direction,c.low,c.high,"UNMITIGATED"))
    return out

def premium_discount(candles: list[Candle], swings: list[Swing] | None = None) -> dict:
    swings = swings if swings is not None else confirmed_swings(candles)
    if not swings: return {"status":"UNAVAILABLE","range_high":None,"range_low":None,"equilibrium":None,"zone":"UNKNOWN"}
    high = next((s.price for s in reversed(swings) if s.kind=="HIGH"),None)
    low = next((s.price for s in reversed(swings) if s.kind=="LOW"),None)
    if high is None or low is None or high <= low:
        return {"status":"UNAVAILABLE","range_high":high,"range_low":low,"equilibrium":None,"zone":"UNKNOWN"}
    eq = (high+low)/2
    price = candles[-1].close
    return {"status":"OK","range_high":high,"range_low":low,"equilibrium":eq,
            "zone":"PREMIUM" if price>eq else "DISCOUNT" if price<eq else "EQUILIBRIUM"}

def analyse_smc(candles: list[Candle], left: int = 3, right: int = 3, min_fvg: float = 0.0) -> dict:
    if len(candles) < left+right+3: raise ValueError("Insufficient candles for SMC analysis")
    if not all(c.valid() for c in candles): raise ValueError("Invalid candle in SMC input")
    swings = confirmed_swings(candles,left,right)
    events = structure_events(candles,swings,confirmation_bars=right)
    sweeps = liquidity_sweeps(candles,swings,right)
    gaps = fair_value_gaps(candles,min_fvg)
    blocks = order_blocks(candles,events)
    return {"methodology":"deterministic_candle_heuristics_v1",
            "swings":[asdict(x) for x in swings],
            "structure_events":[asdict(x) for x in events],
            "liquidity_sweeps":[asdict(x) for x in sweeps],
            "fair_value_gaps":[asdict(x) for x in gaps],
            "order_blocks":[asdict(x) for x in blocks],
            "premium_discount":premium_discount(candles,swings),
            "caveats":["SMC labels are rule-based interpretations, not evidence of institutional orders.",
                       "Pivots are confirmed only after right-hand candles; historical labels are not real-time guarantees.",
                       "FVGs are three-candle price gaps and are not automatically valid entry zones.",
                       "Order blocks are the last opposite candle before a detected structure break; mitigation tracking is not yet implemented."]}
