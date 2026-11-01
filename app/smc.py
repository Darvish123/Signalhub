"""Causal, deterministic SMC context derived from closed OHLC candles.

These are price-action classifications, not observations of institutional orders.
All returned event indices refer to the supplied candle sequence.
"""
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
@dataclass(frozen=True)
class LiquidityPool:
    kind:Literal["BSL","SSL"]; level:float; member_indices:tuple[int,...]; tolerance:float; status:str
@dataclass(frozen=True)
class Inducement:
    index:int; time_ms:int; direction:Literal["BULLISH","BEARISH"]; level:float; swing_index:int; taken:bool
@dataclass(frozen=True)
class BreakerBlock:
    source_ob_index:int; time_ms:int; direction:Literal["BULLISH","BEARISH"]; lower:float; upper:float; break_index:int; retest_index:int|None

def _validate(candles):
    if len(candles)<3: raise ValueError("Insufficient candles for SMC analysis")
    if not all(c.valid() for c in candles): raise ValueError("Invalid candle in SMC input")
    if any(b.time_ms<=a.time_ms for a,b in zip(candles,candles[1:])):
        raise ValueError("Candles must be strictly chronological")

def confirmed_swings(candles:list[Candle],left:int=3,right:int=3)->list[Swing]:
    if left<1 or right<1: raise ValueError("left and right must be >= 1")
    raw=[]
    for i in range(left,len(candles)-right):
        c=candles[i]
        if all(c.high>candles[j].high for j in range(i-left,i)) and all(c.high>=candles[j].high for j in range(i+1,i+right+1)):
            raw.append((i,"HIGH",c.high))
        if all(c.low<candles[j].low for j in range(i-left,i)) and all(c.low<=candles[j].low for j in range(i+1,i+right+1)):
            raw.append((i,"LOW",c.low))
    raw.sort(); last={"HIGH":None,"LOW":None}; out=[]
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

def equal_level_pools(swings:list[Swing],tolerance:float)->list[LiquidityPool]:
    """Cluster confirmed highs/lows within an absolute price tolerance."""
    if tolerance<0: raise ValueError("tolerance must be >= 0")
    pools=[]
    for kind,pool_kind in (("HIGH","BSL"),("LOW","SSL")):
        levels=[]
        for s in (x for x in swings if x.kind==kind):
            match=next((g for g in levels if abs(s.price-sum(g[1])/len(g[1]))<=tolerance),None)
            if match is None: levels.append([s.index,[s.price]])
            else: match[0]=s.index; match[1].append(s.price)
        for last_index,prices in levels:
            if len(prices)>=2:
                pools.append(LiquidityPool(pool_kind,sum(prices)/len(prices),tuple(
                    s.index for s in swings if s.kind==kind and any(abs(s.price-p)<=tolerance for p in prices)
                ),tolerance,"RESTING"))
    return pools

def liquidity_pools(candles:list[Candle],swings:list[Swing],tolerance:float)->list[LiquidityPool]:
    pools=equal_level_pools(swings,tolerance)
    result=[]
    for p in pools:
        later=[i for i,c in enumerate(candles) if i>max(p.member_indices) and
               (c.high>p.level if p.kind=="BSL" else c.low<p.level)]
        result.append(LiquidityPool(p.kind,p.level,p.member_indices,p.tolerance,"RAIDED" if later else "RESTING"))
    return result

def fair_value_gaps(candles:list[Candle],min_gap:float=0.0)->list[FairValueGap]:
    if min_gap<0: raise ValueError("min_gap must be >= 0")
    out=[]
    for i in range(2,len(candles)):
        a,c=candles[i-2],candles[i]
        if c.low>a.high and c.low-a.high>=min_gap: out.append(FairValueGap(i,c.time_ms,"BULLISH",a.high,c.low,c.low-a.high))
        elif c.high<a.low and a.low-c.high>=min_gap: out.append(FairValueGap(i,c.time_ms,"BEARISH",c.high,a.low,a.low-c.high))
    return out

def fvg_lifecycle(candles:list[Candle],gaps:list[FairValueGap])->list[dict]:
    """Causal post-formation lifecycle: untouched, partial, filled, or invalidated."""
    out=[]
    for g in gaps:
        state="UNMITIGATED"; first_touch=None; fill_index=None; invalid_index=None
        for i in range(g.index+1,len(candles)):
            c=candles[i]
            touched=c.low<=g.upper and c.high>=g.lower
            if touched and first_touch is None: first_touch=i
            if g.direction=="BULLISH":
                if c.close<g.lower: state="INVALIDATED"; invalid_index=i; break
                if c.low<=g.lower: state="FILLED"; fill_index=i; break
                if touched: state="PARTIAL"; 
            else:
                if c.close>g.upper: state="INVALIDATED"; invalid_index=i; break
                if c.high>=g.upper: state="FILLED"; fill_index=i; break
                if touched: state="PARTIAL"
        out.append({"index":g.index,"direction":g.direction,"lower":g.lower,"upper":g.upper,
                    "state":state,"first_touch_index":first_touch,"fill_index":fill_index,"invalidation_index":invalid_index})
    return out

def order_blocks(candles:list[Candle],events:list[StructureEvent]|None=None,lookback:int=10)->list[OrderBlock]:
    """Last opposing candle before a confirmed close-break; only subsequent bars mitigate."""
    if lookback<1: raise ValueError("lookback must be >= 1")
    events=events if events is not None else structure_events(candles)
    out=[]
    for event in events:
        start=max(0,event.index-lookback)
        j=next((j for j in range(event.index-1,start-1,-1) if
            (candles[j].close<candles[j].open if event.direction=="BULLISH" else candles[j].close>candles[j].open)),None)
        if j is None: continue
        origin=candles[j]; status="UNMITIGATED"; mitigation_index=None
        for k in range(event.index+1,len(candles)):
            x=candles[k]
            invalid=(event.direction=="BULLISH" and x.close<origin.low) or (event.direction=="BEARISH" and x.close>origin.high)
            touched=x.low<=origin.high and x.high>=origin.low
            if invalid: status="INVALIDATED"; mitigation_index=k; break
            if touched: status="MITIGATED"; mitigation_index=k; break
        out.append(OrderBlock(j,origin.time_ms,event.direction,origin.low,origin.high,status,mitigation_index))
    return out

def breaker_blocks(candles:list[Candle],blocks:list[OrderBlock])->list[BreakerBlock]:
    """An OB becomes a breaker only after close-through; later retest is reported separately."""
    out=[]
    for ob in blocks:
        if ob.mitigation!="INVALIDATED" or ob.mitigation_index is None: continue
        break_i=ob.mitigation_index; direction="BEARISH" if ob.direction=="BULLISH" else "BULLISH"
        retest=next((i for i in range(break_i+1,len(candles)) if
                     candles[i].low<=ob.upper and candles[i].high>=ob.lower),None)
        out.append(BreakerBlock(ob.index,ob.time_ms,direction,ob.lower,ob.upper,break_i,retest))
    return out

def inducements(candles:list[Candle],swings:list[Swing],events:list[StructureEvent])->list[Inducement]:
    """Last confirmed counter-swing before a BOS/CHoCH; marked taken only by later wick."""
    out=[]
    for e in events:
        candidates=[s for s in swings if s.index<e.index and
                    ((e.direction=="BULLISH" and s.kind=="LOW") or (e.direction=="BEARISH" and s.kind=="HIGH"))]
        if not candidates: continue
        s=candidates[-1]
        later=next((i for i in range(e.index+1,len(candles)) if
                    (candles[i].low<s.price if e.direction=="BULLISH" else candles[i].high>s.price)),None)
        out.append(Inducement(e.index,e.time_ms,e.direction,s.price,s.index,later is not None))
    return out

def premium_discount(candles:list[Candle],swings:list[Swing]|None=None)->dict:
    swings=swings if swings is not None else confirmed_swings(candles)
    ordered=sorted(swings,key=lambda s:s.index); pairs=[]
    for a,b in zip(ordered,ordered[1:]):
        if a.kind!=b.kind:
            hi=a if a.kind=="HIGH" else b; lo=a if a.kind=="LOW" else b
            if hi.price>lo.price: pairs.append((max(a.index,b.index),hi,lo))
    if not pairs: return {"status":"UNAVAILABLE","range_high":None,"range_low":None,"equilibrium":None,"zone":"UNKNOWN","range_indices":None}
    _,hi,lo=max(pairs,key=lambda p:p[0]); eq=(hi.price+lo.price)/2; price=candles[-1].close
    return {"status":"OK","range_high":hi.price,"range_low":lo.price,"equilibrium":eq,
            "zone":"PREMIUM" if price>eq else "DISCOUNT" if price<eq else "EQUILIBRIUM","range_indices":[lo.index,hi.index]}

def dealing_range(candles:list[Candle],events:list[StructureEvent],swings:list[Swing])->dict:
    """Most recent confirmed displacement break and its prior opposing swing anchors."""
    for e in reversed(events):
        if e.direction=="BULLISH":
            lows=[s for s in swings if s.kind=="LOW" and s.index<e.index]
            highs=[s for s in swings if s.kind=="HIGH" and s.index<e.index]
            if lows and highs:
                lo=lows[-1]; hi=next((s for s in reversed(highs) if s.index>lo.index),None)
                if hi and hi.price>lo.price: return {"status":"OK","direction":e.direction,"high":hi.price,"low":lo.price,"equilibrium":(hi.price+lo.price)/2,"start_index":lo.index,"end_index":e.index}
        else:
            highs=[s for s in swings if s.kind=="HIGH" and s.index<e.index]
            lows=[s for s in swings if s.kind=="LOW" and s.index<e.index]
            if highs and lows:
                hi=highs[-1]; lo=next((s for s in reversed(lows) if s.index>hi.index),None)
                if lo and hi.price>lo.price: return {"status":"OK","direction":e.direction,"high":hi.price,"low":lo.price,"equilibrium":(hi.price+lo.price)/2,"start_index":hi.index,"end_index":e.index}
    return {"status":"UNAVAILABLE","direction":None,"high":None,"low":None,"equilibrium":None,"start_index":None,"end_index":None}

def smt_divergence(primary:list[Candle],comparison:list[Candle],left:int=3,right:int=3)->dict:
    """Timestamp-aligned swing divergence; caller must supply comparable correlated markets."""
    _validate(primary); _validate(comparison)
    a={c.time_ms:c for c in primary}; b={c.time_ms:c for c in comparison}; common=sorted(set(a)&set(b))
    if len(common)<left+right+5: return {"status":"UNAVAILABLE","direction":None,"reason":"Insufficient aligned candles"}
    pa=[a[t] for t in common]; pb=[b[t] for t in common]
    sa=confirmed_swings(pa,left,right); sb=confirmed_swings(pb,left,right)
    def last_two(rows,kind): return [s for s in rows if s.kind==kind][-2:]
    ah,al=last_two(sa,"HIGH"),last_two(sa,"LOW"); bh,bl=last_two(sb,"HIGH"),last_two(sb,"LOW")
    if len(ah)==2 and len(bh)==2 and ah[1].price>ah[0].price and bh[1].price<=bh[0].price:
        return {"status":"DIVERGENCE","direction":"BEARISH","kind":"BSL_SMT","timestamps":[common[ah[0].index],common[ah[1].index]]}
    if len(al)==2 and len(bl)==2 and al[1].price<al[0].price and bl[1].price>=bl[0].price:
        return {"status":"DIVERGENCE","direction":"BULLISH","kind":"SSL_SMT","timestamps":[common[al[0].index],common[al[1].index]]}
    return {"status":"NONE","direction":None,"kind":None,"timestamps":[]}

def analyse_smc(candles:list[Candle],left:int=3,right:int=3,min_fvg:float=0.0,
                equal_tolerance:float|None=None)->dict:
    if left<1 or right<1: raise ValueError("left and right must be >= 1")
    _validate(candles)
    swings=confirmed_swings(candles,left,right); events=structure_events(candles,swings,right)
    sweeps=liquidity_sweeps(candles,swings,right); gaps=fair_value_gaps(candles,min_fvg)
    blocks=order_blocks(candles,events); pools=liquidity_pools(candles,swings,equal_tolerance if equal_tolerance is not None else min(c.high-c.low for c in candles[-20:])*0.1)
    inducement_rows=inducements(candles,swings,events); breakers=breaker_blocks(candles,blocks)
    return {"methodology":"causal_deterministic_ohlc_smc_v3","swings":[asdict(x) for x in swings],
      "structure_events":[asdict(x) for x in events],"liquidity_sweeps":[asdict(x) for x in sweeps],
      "liquidity_pools":[asdict(x) for x in pools],"fair_value_gaps":[asdict(x) for x in gaps],
      "fvg_lifecycle":fvg_lifecycle(candles,gaps),"order_blocks":[asdict(x) for x in blocks],
      "breaker_blocks":[asdict(x) for x in breakers],"inducements":[asdict(x) for x in inducement_rows],
      "dealing_range":dealing_range(candles,events,swings),"premium_discount":premium_discount(candles,swings),
      "caveats":["OHLC heuristics cannot identify institutional participants, resting orders, or intent.",
      "Pivots are usable only after right-hand confirmation candles close; indices are causal.",
      "Equal highs/lows use an explicit tolerance and are candidate liquidity pools, not confirmed stop orders.",
      "OBs are the last opposing candle before a close-confirmed structure break; mitigation is first later overlap and invalidation is a close beyond the distal edge.",
      "Breaker blocks require an invalidated OB and are not entry signals by themselves.",
      "SMT requires aligned timestamps and a genuinely correlated comparison market; correlation is not inferred.",
      "Dealing range is an algorithmic swing anchor and may differ from discretionary ICT dealing-range selection.",
      "No single SMC feature independently creates a trade recommendation."]}
