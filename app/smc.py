"""Deterministic candle-based SMC heuristics. Not evidence of institutional orders."""
from dataclasses import asdict, dataclass
from typing import Literal
from app.models import Candle

@dataclass(frozen=True)
class Swing:
    index:int; time_ms:int; price:float; kind:Literal["HIGH","LOW"]; label:str
@dataclass(frozen=True)
class StructureEvent:
    index:int; time_ms:int; kind:Literal["BOS","CHoCH"]; direction:Literal["BULLISH","BEARISH"]; level:float; close:float
@dataclass(frozen=True)
class LiquiditySweep:
    index:int; time_ms:int; direction:Literal["BULLISH","BEARISH"]; swept_level:float; wick_extreme:float; close:float; reference_index:int
@dataclass(frozen=True)
class FairValueGap:
    index:int; time_ms:int; direction:Literal["BULLISH","BEARISH"]; lower:float; upper:float; size:float
@dataclass(frozen=True)
class OrderBlock:
    index:int; time_ms:int; direction:Literal["BULLISH","BEARISH"]; lower:float; upper:float; mitigation:str; mitigation_index:int|None=None

def confirmed_swings(candles:list[Candle],left:int=3,right:int=3)->list[Swing]:
    if left<1 or right<1: raise ValueError("left and right must be >= 1")
    raw=[]
    for i in range(left,len(candles)-right):
        c=candles[i]
        if all(c.high>candles[j].high for j in range(i-left,i)) and all(c.high>=candles[j].high for j in range(i+1,i+right+1)):
            raw.append((i,"HIGH",c.high))
        if all(c.low<candles[j].low for j in range(i-left,i)) and all(c.low<=candles[j].low for j in range(i+1,i+right+1)):
            raw.append((i,"LOW",c.low))
    raw.sort()
    last={"HIGH":None,"LOW":None}; out=[]
    for i,kind,price in raw:
        prev=last[kind]
        label=("HH" if price>prev else "LH") if kind=="HIGH" and prev is not None else ("HL" if price>prev else "LL") if kind=="LOW" and prev is not None else ("H" if kind=="HIGH" else "L")
        last[kind]=price; out.append(Swing(i,candles[i].time_ms,price,kind,label))
    return out

def structure_events(candles:list[Candle],swings:list[Swing]|None=None,confirmation_bars:int=3)->list[StructureEvent]:
    if confirmation_bars<0: raise ValueError("confirmation_bars must be >= 0")
    swings=swings if swings is not None else confirmed_swings(candles,right=confirmation_bars)
    highs=[s for s in swings if s.kind=="HIGH"]; lows=[s for s in swings if s.kind=="LOW"]
    events=[]; trend=None; broken=set()
    for i,c in enumerate(candles):
        eh=[s for s in highs if s.index+confirmation_bars<i and ("HIGH",s.index) not in broken]
        el=[s for s in lows if s.index+confirmation_bars<i and ("LOW",s.index) not in broken]
        h=eh[-1] if eh else None; l=el[-1] if el else None
        up=h is not None and c.close>h.price; down=l is not None and c.close<l.price
        if up and not down:
            events.append(StructureEvent(i,c.time_ms,"CHoCH" if trend=="BEARISH" else "BOS","BULLISH",h.price,c.close)); broken.add(("HIGH",h.index)); trend="BULLISH"
        elif down and not up:
            events.append(StructureEvent(i,c.time_ms,"CHoCH" if trend=="BULLISH" else "BOS","BEARISH",l.price,c.close)); broken.add(("LOW",l.index)); trend="BEARISH"
    return events

def liquidity_sweeps(candles:list[Candle],swings:list[Swing]|None=None,confirmation_bars:int=3)->list[LiquiditySweep]:
    if confirmation_bars<0: raise ValueError("confirmation_bars must be >= 0")
    swings=swings if swings is not None else confirmed_swings(candles,right=confirmation_bars)
    out=[]; consumed=set()
    for i,c in enumerate(candles):
        prior=[s for s in swings if s.index+confirmation_bars<i and (s.kind,s.index) not in consumed]
        highs=[s for s in prior if s.kind=="HIGH" and c.high>s.price and c.close<s.price]
        lows=[s for s in prior if s.kind=="LOW" and c.low<s.price and c.close>s.price]
        for s,direction,wick in ((highs[-1] if highs else None,"BEARISH",c.high),(lows[-1] if lows else None,"BULLISH",c.low)):
            if s:
                out.append(LiquiditySweep(i,c.time_ms,direction,s.price,wick,c.close,s.index)); consumed.add((s.kind,s.index))
    return out

def fair_value_gaps(candles:list[Candle],min_gap:float=0.0)->list[FairValueGap]:
    if min_gap<0: raise ValueError("min_gap must be >= 0")
    out=[]
    for i in range(2,len(candles)):
        a,c=candles[i-2],candles[i]
        if c.low>a.high and c.low-a.high>=min_gap: out.append(FairValueGap(i,c.time_ms,"BULLISH",a.high,c.low,c.low-a.high))
        elif c.high<a.low and a.low-c.high>=min_gap: out.append(FairValueGap(i,c.time_ms,"BEARISH",c.high,a.low,a.low-c.high))
    return out

def order_blocks(candles:list[Candle],events:list[StructureEvent]|None=None,lookback:int=10)->list[OrderBlock]:
    if lookback<1: raise ValueError("lookback must be >= 1")
    events=events if events is not None else structure_events(candles)
    out=[]
    for event in events:
        start=max(0,event.index-lookback)
        j=next((j for j in range(event.index-1,start-1,-1) if
            (candles[j].close<candles[j].open if event.direction=="BULLISH" else candles[j].close>candles[j].open)),None)
        if j is None: continue
        origin=candles[j]; status="UNMITIGATED"; mitigation_index=None
        for k in range(j+1,len(candles)):
            x=candles[k]
            # A close through the distal edge invalidates the block; otherwise a revisit mitigates it.
            invalid=(event.direction=="BULLISH" and x.close<origin.low) or (event.direction=="BEARISH" and x.close>origin.high)
            touched=x.low<=origin.high and x.high>=origin.low
            if invalid: status="INVALIDATED"; mitigation_index=k; break
            if touched and status=="UNMITIGATED": status="MITIGATED"; mitigation_index=k
        out.append(OrderBlock(j,origin.time_ms,event.direction,origin.low,origin.high,status,mitigation_index))
    return out

def premium_discount(candles:list[Candle],swings:list[Swing]|None=None)->dict:
    swings=swings if swings is not None else confirmed_swings(candles)
    # Select the most recent chronologically adjacent opposite-type confirmed pair.
    ordered=sorted(swings,key=lambda s:s.index); pairs=[]
    for a,b in zip(ordered,ordered[1:]):
        if a.kind!=b.kind:
            hi=a if a.kind=="HIGH" else b; lo=a if a.kind=="LOW" else b
            if hi.price>lo.price: pairs.append((max(a.index,b.index),hi,lo))
    if not pairs: return {"status":"UNAVAILABLE","range_high":None,"range_low":None,"equilibrium":None,"zone":"UNKNOWN","range_indices":None}
    _,hi,lo=max(pairs,key=lambda p:p[0]); eq=(hi.price+lo.price)/2; price=candles[-1].close
    return {"status":"OK","range_high":hi.price,"range_low":lo.price,"equilibrium":eq,
            "zone":"PREMIUM" if price>eq else "DISCOUNT" if price<eq else "EQUILIBRIUM","range_indices":[lo.index,hi.index]}

def analyse_smc(candles:list[Candle],left:int=3,right:int=3,min_fvg:float=0.0)->dict:
    if left<1 or right<1: raise ValueError("left and right must be >= 1")
    if len(candles)<left+right+3: raise ValueError("Insufficient candles for SMC analysis")
    if not all(c.valid() for c in candles): raise ValueError("Invalid candle in SMC input")
    if any(b.time_ms<=a.time_ms for a,b in zip(candles,candles[1:])): raise ValueError("Candles must be strictly chronological")
    swings=confirmed_swings(candles,left,right); events=structure_events(candles,swings,right)
    sweeps=liquidity_sweeps(candles,swings,right); gaps=fair_value_gaps(candles,min_fvg); blocks=order_blocks(candles,events)
    return {"methodology":"deterministic_candle_heuristics_v2","swings":[asdict(x) for x in swings],
      "structure_events":[asdict(x) for x in events],"liquidity_sweeps":[asdict(x) for x in sweeps],
      "fair_value_gaps":[asdict(x) for x in gaps],"order_blocks":[asdict(x) for x in blocks],
      "premium_discount":premium_discount(candles,swings),
      "caveats":["Candle heuristics do not identify institutional participants or resting orders.",
      "Pivots are usable only after right-hand confirmation candles close.",
      "Order blocks are candidate zones; mitigation is first later overlap and invalidation is a close beyond the distal edge.",
      "Premium/discount uses the latest adjacent confirmed opposite-type swing pair; it is not a complete dealing-range model.",
      "No SMC result is independently a trade recommendation."]}
