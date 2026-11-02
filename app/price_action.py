"""Independent lower-timeframe Price Action trigger engine."""
from dataclasses import asdict, dataclass
from app.models import Candle

@dataclass(frozen=True)
class PriceActionTrigger:
    direction: str
    pattern: str
    index: int
    time_ms: int
    trigger_level: float
    invalidation: float
    body_ratio: float
    close_location: float
    score: int

def analyse_price_action(candles: list[Candle], direction: str | None = None,
                         lookback: int = 8, min_body_ratio: float = 0.45,
                         min_close_location: float = 0.65) -> dict:
    if direction not in (None, "LONG", "SHORT"): raise ValueError("direction must be LONG, SHORT or None")
    if lookback < 3 or not 0 < min_body_ratio <= 1 or not 0.5 <= min_close_location <= 1: raise ValueError("Invalid price-action parameters")
    if len(candles) < max(lookback + 2, 6): return {"status":"UNAVAILABLE","trigger":None,"reason":"Insufficient 15m candles"}
    if any(not c.valid() for c in candles) or any(b.time_ms<=a.time_ms for a,b in zip(candles,candles[1:])): raise ValueError("Price-action candles must be valid and chronological")
    c,p=candles[-1],candles[-2]; span=c.high-c.low
    if span<=0: return {"status":"NO_TRIGGER","trigger":None,"reason":"Zero-range latest candle"}
    body=abs(c.close-c.open); ratio=body/span; location=(c.close-c.low)/span
    prior=candles[-lookback-1:-1]; prior_low=min(x.low for x in prior); prior_high=max(x.high for x in prior)
    prev3=candles[-4:-1]; bull=c.close>c.open; bear=c.close<c.open; candidates=[]
    if bull and c.low<prior_low and c.close>prior_low and location>=min_close_location: candidates.append(("LONG","SWEEP_RECLAIM",prior_low,c.low,80))
    if bear and c.high>prior_high and c.close<prior_high and location<=1-min_close_location: candidates.append(("SHORT","SWEEP_RECLAIM",prior_high,c.high,80))
    if bull and p.close<p.open and c.open<=p.close and c.close>=p.open and ratio>=min_body_ratio: candidates.append(("LONG","BULLISH_ENGULFING",p.open,c.low,70))
    if bear and p.close>p.open and c.open>=p.close and c.close<=p.open and ratio>=min_body_ratio: candidates.append(("SHORT","BEARISH_ENGULFING",p.open,c.high,70))
    if bull and c.close>max(x.high for x in prev3) and ratio>=min_body_ratio and location>=min_close_location: candidates.append(("LONG","MICRO_BREAKOUT",max(x.high for x in prev3),c.low,75))
    if bear and c.close<min(x.low for x in prev3) and ratio>=min_body_ratio and location<=1-min_close_location: candidates.append(("SHORT","MICRO_BREAKDOWN",min(x.low for x in prev3),c.high,75))
    candidates=[x for x in candidates if direction is None or x[0]==direction]
    if not candidates: return {"status":"NO_TRIGGER","trigger":None,"reason":"No aligned 15m sweep-reclaim, engulfing or micro-break"}
    side,pattern,level,invalidation,score=max(candidates,key=lambda x:x[4])
    result=PriceActionTrigger(side,pattern,len(candles)-1,c.time_ms,level,invalidation,round(ratio,4),round(location,4),score)
    return {"status":"TRIGGER_CONFIRMED","trigger":asdict(result),"methodology":"closed_15m_sweep_reclaim_engulfing_microbreak_v1","caveats":["OHLC pattern heuristic, not proof of order flow.","Caller must exclude the forming candle."]}
