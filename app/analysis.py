from statistics import mean
from app.models import Candle
def ema(v:list[float],n:int)->float:
    if len(v)<n: raise ValueError(f"Need {n} values for EMA")
    a=2/(n+1); x=mean(v[:n])
    for y in v[n:]: x=a*y+(1-a)*x
    return x
def atr(cs:list[Candle],n:int=14)->float:
    if len(cs)<n+1: raise ValueError(f"Need {n+1} candles for ATR")
    return mean(max(c.high-c.low,abs(c.high-p.close),abs(c.low-p.close)) for p,c in zip(cs[-n-1:-1],cs[-n:]))
def pivots(cs:list[Candle],left:int=3,right:int=3)->tuple[list[float],list[float]]:
    hs=[]; ls=[]
    for i in range(left,len(cs)-right):
        h,l=cs[i].high,cs[i].low
        if all(h>cs[j].high for j in range(i-left,i)) and all(h>=cs[j].high for j in range(i+1,i+right+1)): hs.append(h)
        if all(l<cs[j].low for j in range(i-left,i)) and all(l<=cs[j].low for j in range(i+1,i+right+1)): ls.append(l)
    return hs,ls
