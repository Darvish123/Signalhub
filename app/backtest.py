"""Event-driven, single-position OHLCV backtest. Conservative same-bar stop/target handling."""
import argparse,csv,json,math
from dataclasses import asdict,dataclass
from datetime import datetime,timezone
from pathlib import Path
from app.models import Candle
from app.strategy import analyse

@dataclass
class Trade:
    symbol:str; side:str; signal_time_ms:int; entry_time_ms:int; exit_time_ms:int
    entry:float; exit:float; stop:float; target:float; gross_pnl_pct:float; net_pnl_pct:float
    exit_reason:str; bars_held:int; position_fraction:float; equity_pnl_pct:float

def load_csv(path:str)->list[Candle]:
    out=[]
    with open(path,newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f)
        required={"timestamp_ms","open","high","low","close"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames): raise ValueError("CSV requires timestamp_ms,open,high,low,close columns")
        for row in reader:
            c=Candle(int(row["timestamp_ms"]),float(row["open"]),float(row["high"]),float(row["low"]),float(row["close"]),float(row.get("quote_volume") or 0),float(row.get("base_volume") or 0))
            if not c.valid(): raise ValueError(f"Invalid candle at {c.time_ms}")
            out.append(c)
    out.sort(key=lambda x:x.time_ms)
    if len(out)<500: raise ValueError("At least 500 15m candles (including warm-up) are required")
    if len({x.time_ms for x in out})!=len(out): raise ValueError("Duplicate candle timestamps")
    if any(b.time_ms-a.time_ms!=900000 for a,b in zip(out,out[1:])): raise ValueError("15m CSV must be continuous without missing intervals")
    return out

def aggregate(candles:list[Candle],period_ms:int)->list[Candle]:
    buckets={}
    for c in candles:
        key=c.time_ms//period_ms*period_ms
        if key+period_ms>candles[-1].time_ms+900000: continue
        if key not in buckets: buckets[key]=[c.open,c.high,c.low,c.close,c.quote_volume,c.base_volume]
        else:
            x=buckets[key]; x[1]=max(x[1],c.high); x[2]=min(x[2],c.low); x[3]=c.close; x[4]+=c.quote_volume; x[5]+=c.base_volume
    return [Candle(t,*v) for t,v in sorted(buckets.items())]

def stats(trades:list[Trade],start_ms:int,end_ms:int,initial_equity:float=10000)->dict:
    wins=[t for t in trades if t.net_pnl_pct>0]; losses=[t for t in trades if t.net_pnl_pct<=0]
    equity=initial_equity; peak=equity; max_dd=0.; curve=[]
    for t in trades:
        equity*=1+t.equity_pnl_pct/100; peak=max(peak,equity); max_dd=max(max_dd,(peak-equity)/peak if peak else 0); curve.append(equity)
    returns=[t.net_pnl_pct for t in trades]
    gross_win=sum(t.net_pnl_pct for t in wins); gross_loss=abs(sum(t.net_pnl_pct for t in losses))
    return {"period_start_utc":datetime.fromtimestamp(start_ms/1000,timezone.utc).isoformat(),
      "period_end_utc":datetime.fromtimestamp(end_ms/1000,timezone.utc).isoformat(),
      "trades":len(trades),"wins":len(wins),"losses":len(losses),"win_rate_pct":round(100*len(wins)/len(trades),2) if trades else 0,
      "net_return_pct":round((equity/initial_equity-1)*100,3),"final_equity":round(equity,2),
      "max_drawdown_pct":round(max_dd*100,3),"profit_factor":round(gross_win/gross_loss,3) if gross_loss else (None if not gross_win else "infinite"),
      "average_trade_pct":round(sum(returns)/len(returns),4) if returns else 0,
      "average_win_pct":round(sum(t.net_pnl_pct for t in wins)/len(wins),4) if wins else 0,
      "average_loss_pct":round(sum(t.net_pnl_pct for t in losses)/len(losses),4) if losses else 0,
      "longs":sum(t.side=="LONG" for t in trades),"shorts":sum(t.side=="SHORT" for t in trades),
      "exit_reasons":{k:sum(t.exit_reason==k for t in trades) for k in ("STOP","TARGET","TIME")}}

def run_backtest(candles:list[Candle],symbol:str,start_ms:int,end_ms:int,fee_bps:float=5.,slippage_bps:float=2.,risk_pct:float=0.5,max_hold_bars:int=192,max_leverage:float=1.0)->dict:
    if fee_bps<0 or slippage_bps<0 or not 0<risk_pct<=2 or max_hold_bars<1 or not 0<max_leverage<=5: raise ValueError("Invalid cost/risk/holding configuration")
    h1=aggregate(candles,3600000); h4=aggregate(candles,14400000)
    trades=[]; i=0; cost_rate=(fee_bps+slippage_bps)/10000
    # The strategy is evaluated using only bars closed before the decision bar.
    while i<len(candles)-1:
        now=candles[i].time_ms
        if now<start_ms or now>end_ms or now//900000*900000!=now: i+=1; continue
        r4=[x for x in h4 if x.time_ms+14400000<=now+900000]
        r1=[x for x in h1 if x.time_ms+3600000<=now+900000]
        m15=candles[:i+1]
        if len(r4)<50 or len(r1)<50 or len(m15)<50: i+=1; continue
        sig=analyse(symbol,"FUTURES",r4[-100:],r1[-100:],m15[-100:],min_score=70,min_rr=2.,min_quote_volume=0,now_ms=now)
        if sig.status!="CANDIDATE" or sig.side not in ("LONG","SHORT") or sig.entry is None or sig.stop_loss is None or sig.take_profit_1 is None: i+=1; continue
        entry_bar=candles[i+1]; side=sig.side
        entry=entry_bar.open*(1+cost_rate if side=="LONG" else 1-cost_rate)
        stop=sig.stop_loss; target=sig.take_profit_1
        if (side=="LONG" and not stop<entry<target) or (side=="SHORT" and not target<entry<stop): i+=1; continue
        exit_price=None; reason="TIME"; exit_idx=min(len(candles)-1,i+max_hold_bars)
        for j in range(i+1,exit_idx+1):
            bar=candles[j]
            if side=="LONG":
                hit_stop=bar.low<=stop; hit_target=bar.high>=target
            else:
                hit_stop=bar.high>=stop; hit_target=bar.low<=target
            if hit_stop: exit_price=stop; reason="STOP"; exit_idx=j; break
            if hit_target: exit_price=target; reason="TARGET"; exit_idx=j; break
        if exit_price is None: exit_price=candles[exit_idx].close
        exit_price*=1-cost_rate if side=="LONG" else 1+cost_rate
        gross=((exit_price-entry)/entry*100) if side=="LONG" else ((entry-exit_price)/entry*100)
        net=gross
        stop_distance=abs(entry-stop)/entry
        # Risk-budget sizing: notional fraction is capped by max_leverage (1.0 = unlevered).
        position_fraction=min(max_leverage,(risk_pct/100)/stop_distance) if stop_distance>0 else 0.0
        equity_pnl_pct=net*position_fraction
        trades.append(Trade(symbol,side,now,entry_bar.time_ms,candles[exit_idx].time_ms,round(entry,10),round(exit_price,10),stop,target,round(gross,5),round(net,5),reason,exit_idx-i,round(position_fraction,6),round(equity_pnl_pct,6)))
        i=exit_idx+1
    report=stats(trades,start_ms,end_ms)
    report.update({"symbol":symbol,"timeframe":"15m","strategy":"existing 4h/1h/15m EMA+ATR+pivot strategy; SMC is not wired into entry decisions",
      "fee_bps_per_side":fee_bps,"slippage_bps_per_side":slippage_bps,"risk_pct_per_trade":risk_pct,"max_leverage":max_leverage,
      "max_holding_hours":max_hold_bars*.25,"execution":"next 15m open; adverse costs; stop wins if stop and target touch same candle",
      "funding":"NOT_MODELLED","position_sizing":"risk-budget sizing by stop distance; position fraction capped by max_leverage; equity curve compounds position-weighted returns",
      "trades":[asdict(t) for t in trades]})
    return report

def main():
    p=argparse.ArgumentParser(description="SignalHub conservative OHLCV backtest")
    p.add_argument("--csv",required=True); p.add_argument("--symbol",default="BTCUSDT")
    p.add_argument("--start",required=True,help="UTC ISO date, e.g. 2026-10-01")
    p.add_argument("--end",required=True,help="UTC ISO date inclusive, e.g. 2026-10-31")
    p.add_argument("--fee-bps",type=float,default=5.); p.add_argument("--slippage-bps",type=float,default=2.)
    p.add_argument("--risk-pct",type=float,default=0.5); p.add_argument("--max-leverage",type=float,default=1.0)
    p.add_argument("--out",default="backtest-report.json")
    a=p.parse_args(); data=load_csv(a.csv)
    start=int(datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc).timestamp()*1000)
    end=int(datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc).timestamp()*1000)+86400000-1
    result=run_backtest(data,a.symbol,start,end,a.fee_bps,a.slippage_bps,a.risk_pct,max_leverage=a.max_leverage)
    Path(a.out).write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="trades"},indent=2))
if __name__=="__main__": main()
