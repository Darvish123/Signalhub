"""Single-position 1H execution backtest with 1D/4H/1H SMC and historical funding."""
import argparse,csv,json
from dataclasses import asdict,dataclass
from datetime import datetime,timezone
from pathlib import Path
from app.models import Candle
from app.strategy import analyse
from app.funding import FundingRate,load_funding_csv,funding_cashflow_pct
from app.data_quality import validated_candles

@dataclass
class Trade:
    symbol:str; side:str; signal_time_ms:int; entry_time_ms:int; exit_time_ms:int
    entry:float; exit:float; stop:float; target:float; gross_pnl_pct:float; net_pnl_pct:float
    funding_pnl_pct_equity:float; exit_reason:str; bars_held:int; position_fraction:float; equity_pnl_pct:float

def load_csv(path:str,interval_ms:int=3600000)->list[Candle]:
    out=[]
    with open(path,newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f); required={"timestamp_ms","open","high","low","close"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames): raise ValueError("CSV requires timestamp_ms,open,high,low,close")
        for row in reader:
            out.append(Candle(int(row["timestamp_ms"]),float(row["open"]),float(row["high"]),float(row["low"]),float(row["close"]),float(row.get("quote_volume") or 0),float(row.get("base_volume") or 0)))
    out.sort(key=lambda x:x.time_ms)
    if len(out)<1500: raise ValueError("At least 1500 hourly candles are required for 1D/4H/1H warm-up")
    return validated_candles(out,interval_ms)

def aggregate(candles:list[Candle],period_ms:int,source_interval_ms:int=3600000)->list[Candle]:
    buckets={}
    for c in candles:
        key=c.time_ms//period_ms*period_ms
        if key+period_ms>candles[-1].time_ms+source_interval_ms: continue
        if key not in buckets: buckets[key]=[c.open,c.high,c.low,c.close,c.quote_volume,c.base_volume,1]
        else:
            x=buckets[key]; x[1]=max(x[1],c.high); x[2]=min(x[2],c.low); x[3]=c.close; x[4]+=c.quote_volume; x[5]+=c.base_volume; x[6]+=1
    expected=period_ms//source_interval_ms
    return [Candle(t,*v[:6]) for t,v in sorted(buckets.items()) if v[6]==expected]

def stats(trades:list[Trade],start_ms:int,end_ms:int,initial_equity:float=100.)->dict:
    wins=[t for t in trades if t.equity_pnl_pct>0]; losses=[t for t in trades if t.equity_pnl_pct<=0]
    equity=initial_equity; peak=equity; max_dd=0.
    for t in trades:
        equity*=1+t.equity_pnl_pct/100; peak=max(peak,equity); max_dd=max(max_dd,(peak-equity)/peak if peak else 0)
    gw=sum(t.equity_pnl_pct for t in wins); gl=abs(sum(t.equity_pnl_pct for t in losses))
    return {"period_start_utc":datetime.fromtimestamp(start_ms/1000,timezone.utc).isoformat(),
      "period_end_utc":datetime.fromtimestamp(end_ms/1000,timezone.utc).isoformat(),"initial_equity":initial_equity,
      "trades":len(trades),"wins":len(wins),"losses":len(losses),"win_rate_pct":round(100*len(wins)/len(trades),2) if trades else 0,
      "net_return_pct":round((equity/initial_equity-1)*100,3),"final_equity":round(equity,2),
      "max_drawdown_pct":round(max_dd*100,3),"profit_factor":round(gw/gl,3) if gl else (None if not gw else "infinite"),
      "average_win_equity_pct":round(sum(t.equity_pnl_pct for t in wins)/len(wins),4) if wins else 0,
      "average_loss_equity_pct":round(sum(t.equity_pnl_pct for t in losses)/len(losses),4) if losses else 0,
      "longs":sum(t.side=="LONG" for t in trades),"shorts":sum(t.side=="SHORT" for t in trades),
      "funding_pnl_equity_pct":round(sum(t.funding_pnl_pct_equity for t in trades),5),
      "exit_reasons":{k:sum(t.exit_reason==k for t in trades) for k in ("STOP","TARGET","TIME")}}

def position_fraction_for_risk(entry:float,stop:float,risk_pct:float,max_leverage:float=1.)->float:
    if entry<=0 or not 0<risk_pct<=2 or not 0<max_leverage<=5: raise ValueError("Invalid entry/risk/leverage")
    distance=abs(entry-stop)/entry
    if distance<=0: raise ValueError("Entry and stop must differ")
    return min(max_leverage,(risk_pct/100)/distance)

def run_backtest(candles:list[Candle],symbol:str,start_ms:int,end_ms:int,fee_bps:float=5.,slippage_bps:float=2.,
                 risk_pct:float=.5,max_hold_bars:int=48,max_leverage:float=1.,
                 funding_rates:list[FundingRate]|None=None,initial_equity:float=100.)->dict:
    if fee_bps<0 or slippage_bps<0 or not 0<risk_pct<=2 or max_hold_bars<1 or not 0<max_leverage<=5 or initial_equity<=0:
        raise ValueError("Invalid backtest configuration")
    candles=validated_candles(candles,3600000)
    h4=aggregate(candles,14400000); d1=aggregate(candles,86400000)
    funding=sorted(funding_rates or [],key=lambda x:x.funding_time_ms)
    trades=[]; i=0; cost=(fee_bps+slippage_bps)/10000
    while i<len(candles)-1:
        decision=candles[i].time_ms+3600000
        if decision<start_ms or decision>end_ms: i+=1; continue
        closed4=[x for x in h4 if x.time_ms+14400000<=decision]
        closed1d=[x for x in d1 if x.time_ms+86400000<=decision]
        closed1h=candles[:i+1]
        if min(len(closed4),len(closed1d),len(closed1h))<60: i+=1; continue
        sig=analyse(symbol,"FUTURES",closed1d[-160:],closed4[-200:],closed1h[-200:],
                    min_score=70,min_rr=3.,min_quote_volume=0,now_ms=decision)
        if sig.status!="CANDIDATE" or sig.side not in ("LONG","SHORT") or None in (sig.stop_loss,sig.take_profit_1):
            i+=1; continue
        entry_bar=candles[i+1]; side=sig.side
        entry=entry_bar.open*(1+cost if side=="LONG" else 1-cost)
        stop=sig.stop_loss; target=sig.take_profit_1
        if (side=="LONG" and not stop<entry<target) or (side=="SHORT" and not target<entry<stop): i+=1; continue
        # Re-check minimum 3R using the actual next-open fill after any price gap.
        actual_round_trip_cost=2*entry*cost
        actual_net_risk=abs(entry-stop)+actual_round_trip_cost
        actual_net_reward=abs(target-entry)-actual_round_trip_cost
        if actual_net_reward<=0 or actual_net_reward/actual_net_risk<3.: i+=1; continue
        exit_idx=min(len(candles)-1,i+max_hold_bars); exit_price=None; reason="TIME"
        for j in range(i+1,exit_idx+1):
            bar=candles[j]
            hs=bar.low<=stop if side=="LONG" else bar.high>=stop
            ht=bar.high>=target if side=="LONG" else bar.low<=target
            if hs: exit_price=stop; reason="STOP"; exit_idx=j; break
            if ht: exit_price=target; reason="TARGET"; exit_idx=j; break
        if exit_price is None: exit_price=candles[exit_idx].close
        exit_time=candles[exit_idx].time_ms+3600000
        exit_price*=1-cost if side=="LONG" else 1+cost
        gross=((exit_price-entry)/entry*100) if side=="LONG" else ((entry-exit_price)/entry*100)
        fraction=position_fraction_for_risk(entry,stop,risk_pct,max_leverage)
        # Settlement is charged only while position is open: entry <= fundingTime <= exit.
        funding_equity=sum(funding_cashflow_pct(side,entry,fraction,x.funding_rate,x.mark_price)
                           for x in funding if entry_bar.time_ms<=x.funding_time_ms<=exit_time)
        equity_pnl=gross*fraction+funding_equity
        net_position=gross+(funding_equity/fraction if fraction else 0.)
        trades.append(Trade(symbol,side,decision,entry_bar.time_ms,exit_time,round(entry,10),round(exit_price,10),
            stop,target,round(gross,5),round(net_position,5),round(funding_equity,6),reason,exit_idx-i,
            round(fraction,6),round(equity_pnl,6)))
        i=exit_idx+1
    report=stats(trades,start_ms,end_ms,initial_equity)
    expected_settlements=sum(start_ms<=x.funding_time_ms<=end_ms for x in funding)
    report.update({"symbol":symbol,"timeframe":"1H execution; 1D/4H/1H SMC","strategy":"SMC: 1D bias + 4H BOS/CHoCH + 1H BOS/CHoCH and sweep/FVG; structural swing invalidation stop; 3R target",
      "fee_bps_per_side":fee_bps,"slippage_bps_per_side":slippage_bps,"risk_pct_per_trade":risk_pct,"max_leverage":max_leverage,
      "initial_equity":initial_equity,"funding_records_loaded":len(funding),"funding_settlements_in_test_window":expected_settlements,
      "funding":"HISTORICAL rates applied at settlements while position open" if funding else "MISSING - do not treat as full-cost futures result",
      "execution":"next 1H open; adverse costs; stop first if stop and target touched in same candle",
      "trades":[asdict(t) for t in trades]})
    return report

def main():
    p=argparse.ArgumentParser(description="SignalHub 1D/4H/1H SMC futures backtest")
    p.add_argument("--csv",required=True); p.add_argument("--funding-csv",required=True)
    p.add_argument("--symbol",default="BTCUSDT"); p.add_argument("--start",required=True); p.add_argument("--end",required=True)
    p.add_argument("--fee-bps",type=float,default=5.); p.add_argument("--slippage-bps",type=float,default=2.)
    p.add_argument("--risk-pct",type=float,default=.5); p.add_argument("--max-leverage",type=float,default=1.)
    p.add_argument("--initial-equity",type=float,default=100.); p.add_argument("--out",default="backtest-report.json")
    a=p.parse_args(); data=load_csv(a.csv); rates=load_funding_csv(a.funding_csv)
    start=int(datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc).timestamp()*1000)
    end=int(datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc).timestamp()*1000)+86400000-1
    result=run_backtest(data,a.symbol,start,end,a.fee_bps,a.slippage_bps,a.risk_pct,
                        max_leverage=a.max_leverage,funding_rates=rates,initial_equity=a.initial_equity)
    Path(a.out).write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="trades"},indent=2))
if __name__=="__main__": main()
