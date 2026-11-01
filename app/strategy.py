import time
from app.analysis import atr,ema,pivots
from app.models import Candle,Signal
def analyse(symbol:str,market:str,regime:list[Candle],setup:list[Candle],entry_tf:list[Candle],min_score:int=70,min_rr:float=2.,min_quote_volume:float=1_000_000,now_ms:int|None=None)->Signal:
    now_ms=now_ms or int(time.time()*1000)
    base=dict(symbol=symbol,market=market,entry=None,stop_loss=None,take_profit_1=None,take_profit_2=None,net_rr=None,created_at_ms=now_ms)
    if min(len(regime),len(setup),len(entry_tf))<50: return Signal(side="NONE",status="NO_TRADE",score=0,reasons=["Insufficient history"],risks=["Need 50 candles per timeframe"],**base)
    rs=[]; risk_notes=[]; score=0
    try:
        r=[c.close for c in regime]; s=[c.close for c in setup]; p=[c.close for c in entry_tf]
        f,sl=ema(r,20),ema(r,50)
        if f>sl and r[-1]>f: side="LONG"; score+=20; rs.append("4h bullish regime")
        elif f<sl and r[-1]<f: side="SHORT"; score+=20; rs.append("4h bearish regime")
        else: return Signal(side="NONE",status="NO_TRADE",score=0,reasons=["4h regime mixed"],risks=["No directional bias"],**base)
        sf,ss=ema(s,20),ema(s,50)
        if (side=="LONG" and sf>ss) or (side=="SHORT" and sf<ss): score+=15; rs.append("1h aligned")
        else: risk_notes.append("1h not aligned")
        vol=atr(entry_tf,14)
        if vol<=0 or vol/p[-1]>.08: return Signal(side="NONE",status="NO_TRADE",score=score,reasons=rs,risks=risk_notes+["ATR safety gate"],**base)
        e=ema(p,20)
        if (side=="LONG" and p[-1]<=e) or (side=="SHORT" and p[-1]>=e): return Signal(side="NONE",status="NO_TRADE",score=score,reasons=rs,risks=risk_notes+["15m momentum not confirmed"],**base)
        score+=15; rs.append("15m momentum confirmed")
        highs,lows=pivots(entry_tf,3,3); entry=p[-1]
        if side=="LONG":
            sup=[x for x in lows if x<entry]; tgt=sorted(x for x in highs if x>entry)
            if not sup or not tgt: raise ValueError("No confirmed support/resistance")
            stop=max(sup)-.15*vol; tp=tgt[0]; tp2=tgt[1] if len(tgt)>1 else tp
            loss=entry-stop; gain=tp-entry
        else:
            res=[x for x in highs if x>entry]; tgt=sorted((x for x in lows if x<entry),reverse=True)
            if not res or not tgt: raise ValueError("No confirmed support/resistance")
            stop=min(res)+.15*vol; tp=tgt[0]; tp2=tgt[1] if len(tgt)>1 else tp
            loss=stop-entry; gain=entry-tp
        if loss<=0 or gain<=0: raise ValueError("Invalid structure geometry")
        # Placeholder cost only; replace with account fee tier + measured spread/slippage before use.
        cost=entry*.001; rr=max(0.,gain-cost)/(loss+cost)
        if rr>=min_rr: score+=20; rs.append("Structural target clears estimated net RR")
        else: risk_notes.append(f"Net RR {rr:.2f} below {min_rr:.2f}")
        if entry_tf[-1].quote_volume>=min_quote_volume/96: score+=10
        else: risk_notes.append("15m quote volume below liquidity threshold")
        if score<min_score or rr<min_rr: return Signal(side="NONE",status="NO_TRADE",score=score,reasons=rs,risks=risk_notes+["Score/RR gate failed"],**base)
        return Signal(symbol=symbol,market=market,side=side,status="CANDIDATE",score=min(score,100),entry=entry,stop_loss=stop,take_profit_1=tp,take_profit_2=tp2,net_rr=round(rr,3),reasons=rs,risks=risk_notes+["Paper-only; cost model requires calibration"],created_at_ms=now_ms)
    except ValueError as e: return Signal(side="NONE",status="NO_TRADE",score=score,reasons=rs,risks=risk_notes+[str(e)],**base)
