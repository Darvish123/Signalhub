"""Zone-first strategy: 1D bias, 4H zone, 1H refinement/liquidity, 15m PA."""
import math
import time
from app.analysis import atr,ema
from app.models import Candle,Signal
from app.smc import analyse_smc
from app.price_action import analyse_price_action
from app.zones import build_zone_context


def meets_minimum_rr(net_rr: float, minimum_rr: float, tolerance: float = 1e-9) -> bool:
    """Accept a mathematically boundary-equal RR despite floating point representation."""
    return net_rr >= minimum_rr or math.isclose(
        net_rr, minimum_rr, rel_tol=tolerance, abs_tol=tolerance
    )


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
        score+=20; reasons.append("4H directional structure aligned; zone discovery enabled")
        if lower_tf is None:
            return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                          risks=["15m Price Action confirmation is mandatory; no lower timeframe supplied"],**base)
        zone_result=build_zone_context(setup[-160:],entry_tf[-200:],side,h4_analysis=h4)
        if zone_result["status"]!="CONFIRMED":
            return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                          risks=[zone_result.get("reason","No confirmed 4H/1H zone and liquidity confluence")],**base)
        zone=zone_result["zone"]
        score+=25
        reasons.append(f"1H refined 4H zone confirmed ({zone['refined_by']}); nearby liquidity verified")
        if len(lower_tf)<20 or any(not c.valid() for c in lower_tf) or any(y.time_ms<=x.time_ms for x,y in zip(lower_tf,lower_tf[1:])):
            raise ValueError("15m Price Action input is insufficient, invalid or non-chronological")
        if lower_tf[-1].time_ms+900000>now_ms:
            raise ValueError("Latest 15m Price Action candle is not fully closed")
        pa=analyse_price_action(lower_tf[-200:],direction=side,zone=zone)
        if pa["status"]!="TRIGGER_CONFIRMED":
            return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                          risks=[pa.get("reason","No aligned 15m Price Action trigger inside refined zone")],**base)
        pa_setup=pa["trigger"]
        score+=25; reasons.append(f"15m in-zone Price Action confirmed: {pa_setup['pattern']}")
        reasons.append(f"4H zone [{zone['lower']}, {zone['upper']}] refined on 1H; liquidity evidence={len(zone['liquidity_evidence'])}")
        entry=lower_tf[-1].close; vol=atr(entry_tf,14); round_trip_cost=entry*(round_trip_cost_bps/10_000)
        swings=zone_result["h1_swings"]
        if side=="LONG":
            structural=[x["price"] for x in swings if x["kind"]=="LOW" and x["index"]<len(entry_tf)-1 and x["price"]<entry]
            if not structural: raise ValueError("No confirmed 1H swing low for structural invalidation")
            stop=min(min(structural[-3:]),zone["invalidation"],pa_setup["invalidation"])-.10*vol
            if not stop<entry: raise ValueError("Long structural stop is not below entry")
            risk=entry-stop; target=entry+(3*risk+4*round_trip_cost)
        else:
            structural=[x["price"] for x in swings if x["kind"]=="HIGH" and x["index"]<len(entry_tf)-1 and x["price"]>entry]
            if not structural: raise ValueError("No confirmed 1H swing high for structural invalidation")
            stop=max(max(structural[-3:]),zone["invalidation"],pa_setup["invalidation"])+.10*vol
            if not stop>entry: raise ValueError("Short structural stop is not above entry")
            risk=stop-entry; target=entry-(3*risk+4*round_trip_cost)
        net_loss=risk+round_trip_cost; net_gain=3*risk+3*round_trip_cost
        rr=net_gain/net_loss if net_loss>0 else 0
        if not meets_minimum_rr(rr,min_rr):
            return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                          risks=[f"Net RR {rr:.6f} below required {min_rr:.6f}"],**base)
        score+=10; reasons.append("Structural invalidation stop and minimum net RR passed")
        if len(entry_tf)<24 or sum(x.quote_volume for x in entry_tf[-24:])<min_quote_volume:
            return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                          risks=["Rolling 24-closed-hour quote volume below liquidity threshold"],**base)
        score+=10
        if score<min_score: return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                                          risks=["Minimum score not reached"],**base)
        return Signal(symbol=symbol,market=market,side=side,status="CANDIDATE",score=min(score,100),
            entry=entry,stop_loss=stop,take_profit_1=target,take_profit_2=target,net_rr=round(rr,3),
            reasons=reasons,risks=["Paper-only; OHLC structure, zone and candle-pattern labels are heuristics, not proof of institutional activity"],created_at_ms=now_ms)
    except ValueError as exc:
        return Signal(side="NONE",status="NO_TRADE",score=0,reasons=[],risks=[str(exc)],**base)
