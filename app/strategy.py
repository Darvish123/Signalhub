"""Multi-timeframe SMC strategy: 1D bias, 4H structure, 1H trigger."""
import time
from app.analysis import atr,ema
from app.models import Candle,Signal
from app.smc import analyse_smc
from app.ict import analyse_ict
from app.price_action import analyse_price_action

def analyse(symbol:str,market:str,regime:list[Candle],setup:list[Candle],entry_tf:list[Candle],
            min_score:int=70,min_rr:float=3.,min_quote_volume:float=1_000_000,
            round_trip_cost_bps:float=14., ict_require_killzone:bool=False, now_ms:int|None=None, lower_tf:list[Candle]|None=None)->Signal:
    now_ms=now_ms or int(time.time()*1000)
    if min_quote_volume<0 or round_trip_cost_bps<0 or min_rr<=0:
        raise ValueError("Invalid strategy cost, volume or RR configuration")
    base=dict(symbol=symbol,market=market,entry=None,stop_loss=None,take_profit_1=None,
              take_profit_2=None,net_rr=None,created_at_ms=now_ms)
    if min(len(regime),len(setup),len(entry_tf))<60:
        return Signal(side="NONE",status="NO_TRADE",score=0,reasons=["Insufficient history"],
                       risks=["Need at least 60 closed candles on 1D, 4H and 1H"],**base)
    try:
        for name,rows in (("1D",regime),("4H",setup),("1H",entry_tf)):
            if any(not c.valid() for c in rows) or any(b.time_ms<=a.time_ms for a,b in zip(rows,rows[1:])):
                raise ValueError(f"{name} candles invalid or non-chronological")
            if rows[-1].time_ms>=now_ms:
                raise ValueError(f"{name} latest candle is not closed before decision time")
        d=[c.close for c in regime]; d20,d50=ema(d,20),ema(d,50)
        if d[-1]>d20>d50: side="LONG"; score=20; reasons=["1D bullish directional bias"]
        elif d[-1]<d20<d50: side="SHORT"; score=20; reasons=["1D bearish directional bias"]
        else: return Signal(side="NONE",status="NO_TRADE",score=0,reasons=["1D trend is not aligned"],
                            risks=["No directional edge"],**base)
        h4=analyse_smc(setup[-160:]); h4_events=h4["structure_events"]
        aligned=[x for x in h4_events[-8:] if x["direction"]==("BULLISH" if side=="LONG" else "BEARISH")]
        if not aligned: return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                                      risks=["No recent aligned 4H BOS/CHoCH"],**base)
        score+=20; reasons.append("4H confirmed SMC structure aligned")
        h1=analyse_smc(entry_tf[-200:]); direction="BULLISH" if side=="LONG" else "BEARISH"
        events=[x for x in h1["structure_events"][-6:] if x["direction"]==direction]
        sweeps=[x for x in h1["liquidity_sweeps"][-6:] if x["direction"]==direction]
        gaps=[x for x in h1["fair_value_gaps"][-6:] if x["direction"]==direction]
        if not events or not (sweeps or gaps):
            return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                          risks=["1H trigger needs aligned BOS/CHoCH plus liquidity sweep or FVG"],**base)
        ict=analyse_ict(entry_tf[-200:],direction=side,require_killzone=ict_require_killzone)
        if ict["status"]!="ICT_CONFIRMED":
            return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                          risks=[ict.get("reason","ICT sequence not confirmed")],**base)
        ict_setup=ict["setup"]; tap=entry_tf[-1]
        pa_setup=None
        if lower_tf is not None:
            if len(lower_tf)<20 or any(not c.valid() for c in lower_tf) or any(y.time_ms<=x.time_ms for x,y in zip(lower_tf,lower_tf[1:])):
                raise ValueError("15m Price Action input is insufficient, invalid or non-chronological")
            if lower_tf[-1].time_ms+900000>now_ms:
                raise ValueError("Latest 15m Price Action candle is not fully closed")
            pa=analyse_price_action(lower_tf[-200:],direction=side)
            if pa["status"]!="TRIGGER_CONFIRMED":
                return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                              risks=[pa.get("reason","No aligned 15m Price Action trigger")],**base)
            pa_setup=pa["trigger"]
            score+=10; reasons.append(f"15m Price Action trigger confirmed: {pa_setup['pattern']}")
        # A valid OB is a confluence zone only when it overlaps the actual ICT retracement.
        matching_obs=[ob for ob in h1["order_blocks"] if ob["direction"]==direction and
                      ob["mitigation"]!="INVALIDATED" and ob["index"]<ict_setup["tap_index"] and
                      ob["lower"]<=ict_setup["fvg_high"] and ob["upper"]>=ict_setup["fvg_low"]]
        if not matching_obs:
            return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                          risks=["ICT FVG tap lacks a matching, non-invalidated 1H order block"],**base)
        score+=10; reasons.append("1H SMC: aligned structure, liquidity event and valid OB/FVG confluence")
        score+=20; reasons.append("ICT sequence confirmed: sweep -> displacement MSS -> FVG retracement")
        reasons.append(f"ICT confluence: OTE={ict_setup['in_ote']}, PD={ict_setup['premium_discount']}, killzone={ict_setup['killzone'] or 'outside'}")
        entry=lower_tf[-1].close if pa_setup else tap.close; vol=atr(entry_tf,14); round_trip_cost=entry*(round_trip_cost_bps/10_000)
        swings=h1["swings"]
        if side=="LONG":
            structural=[x["price"] for x in swings if x["kind"]=="LOW" and x["index"]<len(entry_tf)-1 and x["price"]<entry]
            if not structural: raise ValueError("No confirmed 1H swing low for structural invalidation")
            stop=min(min(structural[-3:]),ict_setup["sweep_extreme"],pa_setup["invalidation"] if pa_setup else float("inf"))-.10*vol
            if not stop<entry: raise ValueError("Long structural stop is not below entry")
            risk=entry-stop; target=entry+(3*risk+4*round_trip_cost)
        else:
            structural=[x["price"] for x in swings if x["kind"]=="HIGH" and x["index"]<len(entry_tf)-1 and x["price"]>entry]
            if not structural: raise ValueError("No confirmed 1H swing high for structural invalidation")
            stop=max(max(structural[-3:]),ict_setup["sweep_extreme"],pa_setup["invalidation"] if pa_setup else float("-inf"))+.10*vol
            if not stop>entry: raise ValueError("Short structural stop is not above entry")
            risk=stop-entry; target=entry-(3*risk+4*round_trip_cost)
        net_loss=risk+round_trip_cost; net_gain=3*risk+3*round_trip_cost
        rr=net_gain/net_loss if net_loss>0 else 0
        if rr<min_rr: return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                                    risks=[f"Net RR {rr:.3f} below required {min_rr:.2f}"],**base)
        score+=10; reasons.append("Structural invalidation stop and minimum net RR passed")
        # Sum 24 completed 1H quote-volume candles; never approximate 24h turnover from one bar.
        if len(entry_tf)<24 or sum(x.quote_volume for x in entry_tf[-24:])<min_quote_volume:
            return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                          risks=["Rolling 24-closed-hour quote volume below liquidity threshold"],**base)
        score+=10
        if score<min_score: return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                                          risks=["Minimum score not reached"],**base)
        return Signal(symbol=symbol,market=market,side=side,status="CANDIDATE",score=min(score,100),
            entry=entry,stop_loss=stop,take_profit_1=target,take_profit_2=target,net_rr=round(rr,3),
            reasons=reasons,risks=["Paper-only; OHLC SMC/ICT labels are heuristic, not proof of institutional activity"],created_at_ms=now_ms)
    except ValueError as exc:
        return Signal(side="NONE",status="NO_TRADE",score=0,reasons=[],risks=[str(exc)],**base)
