"""Deterministic ICT-style execution model built from closed OHLC candles.

This is an explicit, testable interpretation of the ICT 2022 sequence:
liquidity sweep -> displacement/MSS -> FVG -> retracement/tap.
It does not infer institutional orders or guarantee an edge.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo
from app.models import Candle
from app.smc import analyse_smc

NY = ZoneInfo("America/New_York")

@dataclass(frozen=True)
class ICTSetup:
    direction: str
    sweep_index: int
    mss_index: int
    fvg_index: int
    tap_index: int
    sweep_extreme: float
    mss_level: float
    fvg_low: float
    fvg_high: float
    displacement_atr: float
    body_ratio: float
    ote_low: float | None
    ote_high: float | None
    in_ote: bool
    killzone: str | None
    premium_discount: str
    score: int

def killzone(timestamp_ms: int) -> str | None:
    """NY-local ICT observation windows; ZoneInfo handles DST transitions."""
    dt = datetime.fromtimestamp(timestamp_ms / 1000, NY).time()
    if time(2, 0) <= dt < time(5, 0):
        return "LONDON"
    if time(7, 0) <= dt < time(10, 0):
        return "NEW_YORK_AM"
    if time(13, 0) <= dt < time(16, 0):
        return "NEW_YORK_PM"
    return None

def _atr(rows: list[Candle], period: int = 14) -> float:
    if len(rows) < period + 1:
        return 0.0
    trs=[]
    for i in range(1,len(rows)):
        c,p=rows[i],rows[i-1]
        trs.append(max(c.high-c.low,abs(c.high-p.close),abs(c.low-p.close)))
    return sum(trs[-period:])/period

def _overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> bool:
    return a_low <= b_high and a_high >= b_low

def analyse_ict(candles: list[Candle], direction: str | None = None,
                max_sweep_to_mss: int = 8, max_mss_to_tap: int = 12,
                displacement_atr: float = 1.2, min_body_ratio: float = 0.60,
                require_killzone: bool = False) -> dict:
    if direction not in (None,"LONG","SHORT"):
        raise ValueError("direction must be LONG, SHORT or None")
    if max_sweep_to_mss<1 or max_mss_to_tap<1 or displacement_atr<=0 or not 0<min_body_ratio<=1:
        raise ValueError("Invalid ICT configuration")
    if len(candles)<40:
        return {"status":"UNAVAILABLE","setup":None,"reason":"Need at least 40 closed candles"}
    if any(not c.valid() for c in candles) or any(b.time_ms<=a.time_ms for a,b in zip(candles,candles[1:])):
        raise ValueError("ICT candles must be valid and strictly chronological")
    smc=analyse_smc(candles)
    swings=smc["swings"]; sweeps=smc["liquidity_sweeps"]
    events=smc["structure_events"]; gaps=smc["fair_value_gaps"]
    atrs=[_atr(candles[:i+1]) for i in range(len(candles))]
    candidates=[]
    for sw in sweeps:
        side="LONG" if sw["direction"]=="BULLISH" else "SHORT"
        if direction and side!=direction:
            continue
        for event in events:
            if event["direction"]!=sw["direction"] or not sw["index"]<event["index"]<=sw["index"]+max_sweep_to_mss:
                continue
            i=event["index"]; candle=candles[i]; atr=atrs[i]
            if atr<=0: continue
            body=abs(candle.close-candle.open); span=candle.high-candle.low
            ratio=body/span if span>0 else 0
            if body/atr<displacement_atr or ratio<min_body_ratio:
                continue
            gap=next((g for g in gaps if g["direction"]==sw["direction"] and abs(g["index"]-i)<=1),None)
            if gap is None: continue
            tap=None
            for j in range(i+1,min(len(candles),i+max_mss_to_tap+1)):
                bar=candles[j]
                if _overlap(bar.low,bar.high,gap["lower"],gap["upper"]):
                    # Invalidation before/at the tap disqualifies the setup.
                    if side=="LONG" and bar.close<sw["wick_extreme"]: break
                    if side=="SHORT" and bar.close>sw["wick_extreme"]: break
                    tap=j
                    break
            if tap is None or tap!=len(candles)-1:
                continue
            kz=killzone(candles[tap].time_ms)
            if require_killzone and kz is None:
                continue
            # OTE is measured on the displacement leg from sweep extreme to MSS close.
            if side=="LONG":
                leg_low=sw["wick_extreme"]; leg_high=candle.close
                ote_low=leg_high-(leg_high-leg_low)*0.786
                ote_high=leg_high-(leg_high-leg_low)*0.618
            else:
                leg_high=sw["wick_extreme"]; leg_low=candle.close
                ote_low=leg_low+(leg_high-leg_low)*0.618
                ote_high=leg_low+(leg_high-leg_low)*0.786
            last=candles[tap]
            in_ote=ote_low<=last.close<=ote_high
            pd=smc["premium_discount"]["zone"]
            aligned_pd=(pd=="DISCOUNT" if side=="LONG" else pd=="PREMIUM")
            score=60+10*int(in_ote)+10*int(aligned_pd)+10*int(kz is not None)
            candidates.append(ICTSetup(side,sw["index"],i,gap["index"],tap,
                sw["wick_extreme"],event["level"],gap["lower"],gap["upper"],
                round(body/atr,3),round(ratio,3),round(ote_low,10),round(ote_high,10),
                in_ote,kz,pd,min(score,100)))
    if not candidates:
        return {"status":"NO_SETUP","setup":None,
            "reason":"No complete closed-candle sequence: sweep -> displacement MSS -> FVG -> current-bar retracement"}
    best=max(candidates,key=lambda x:(x.score,x.tap_index,x.mss_index))
    return {"status":"ICT_CONFIRMED","setup":asdict(best),
        "methodology":"sweep_mss_displacement_fvg_retracement_ote_killzone_v1",
        "caveats":[
            "All detections are deterministic OHLC heuristics, not evidence of institutional activity.",
            "MSS requires a confirmed structure close and displacement body/ATR thresholds.",
            "FVG is the three-candle wick imbalance; entry requires a later retracement into the zone.",
            "OTE and New York killzones are confluence features; killzone filtering is optional because crypto trades 24/7.",
            "The current final candle is assumed closed by the caller; no future candle is used."
        ]}
