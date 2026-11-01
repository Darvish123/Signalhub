"""Multi-timeframe SMC strategy: 1D bias, 4H structure, 1H trigger; closed candles only."""
import time
from app.analysis import atr,ema
from app.models import Candle,Signal
from app.smc import analyse_smc

def analyse(symbol:str,market:str,regime:list[Candle],setup:list[Candle],entry_tf:list[Candle],
            min_score:int=70,min_rr:float=3.,min_quote_volume:float=1_000_000,
            now_ms:int|None=None)->Signal:
    now_ms=now_ms or int(time.time()*1000)
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
        h4=analyse_smc(setup[-160:])
        h4_events=h4["structure_events"]
        aligned=[x for x in h4_events[-8:] if x["direction"]==("BULLISH" if side=="LONG" else "BEARISH")]
        if not aligned: return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                                      risks=["No recent aligned 4H BOS/CHoCH"],**base)
        score+=20; reasons.append("4H confirmed SMC structure aligned")
        h1=analyse_smc(entry_tf[-200:])
        direction="BULLISH" if side=="LONG" else "BEARISH"
        events=[x for x in h1["structure_events"][-6:] if x["direction"]==direction]
        sweeps=[x for x in h1["liquidity_sweeps"][-6:] if x["direction"]==direction]
        gaps=[x for x in h1["fair_value_gaps"][-6:] if x["direction"]==direction]
        if not events or not (sweeps or gaps):
            return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                          risks=["1H trigger needs aligned BOS/CHoCH plus liquidity sweep or FVG"],**base)
        score+=20; reasons.append("1H SMC entry confirmation: structure + sweep/FVG")
        entry=entry_tf[-1].close
        vol=atr(entry_tf,14)
        swings=h1["swings"]
        if side=="LONG":
            structural=[x["price"] for x in swings if x["kind"]=="LOW" and x["index"]<len(entry_tf)-1 and x["price"]<entry]
            if not structural: raise ValueError("No confirmed 1H swing low for structural invalidation")
            stop=min(structural[-3:])-.10*vol
            if not stop<entry: raise ValueError("Long structural stop is not below entry")
            risk=entry-stop; target=entry+3*risk
        else:
            structural=[x["price"] for x in swings if x["kind"]=="HIGH" and x["index"]<len(entry_tf)-1 and x["price"]>entry]
            if not structural: raise ValueError("No confirmed 1H swing high for structural invalidation")
            stop=max(structural[-3:])+.10*vol
            if not stop>entry: raise ValueError("Short structural stop is not above entry")
            risk=stop-entry; target=entry-3*risk
        # Conservative placeholder round-trip cost; configure actual fee/slippage in backtest execution.
        round_trip_cost=entry*.0014
        net_loss=risk+round_trip_cost
        net_gain=3*risk-round_trip_cost
        rr=net_gain/net_loss if net_loss>0 else 0
        if rr<min_rr: return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                                    risks=[f"Net RR {rr:.3f} below required {min_rr:.2f}"],**base)
        score+=20; reasons.append("Structural invalidation stop and minimum net RR passed")
        if entry_tf[-1].quote_volume>=min_quote_volume/24: score+=10
        else: return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                            risks=["1H quote volume below liquidity threshold"],**base)
        if score<min_score: return Signal(side="NONE",status="NO_TRADE",score=score,reasons=reasons,
                                          risks=["Minimum score not reached"],**base)
        return Signal(symbol=symbol,market=market,side=side,status="CANDIDATE",score=min(score,100),
            entry=entry,stop_loss=stop,take_profit_1=target,take_profit_2=target,net_rr=round(rr,3),
            reasons=reasons,risks=["Paper-only; verify exchange candle quality and fee tier before use"],created_at_ms=now_ms)
    except ValueError as exc:
        return Signal(side="NONE",status="NO_TRADE",score=0,reasons=[],risks=[str(exc)],**base)
