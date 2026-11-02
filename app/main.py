import asyncio
import time
from dataclasses import replace
from fastapi import FastAPI,HTTPException,Query
from app.config import settings
from app.exchange import BitunixClient,ExchangeError,validate_fresh_candles
from app.storage import SignalStore
from app.strategy import analyse
from app.smc import analyse_smc
from app.risk import evaluate_signal_risk
app=FastAPI(title="SignalHub",version="0.8.0",description="Read-only market analysis and paper risk sizing; no order execution.")
client=BitunixClient(settings.bitunix_futures_base_url,settings.bitunix_spot_base_url,settings.request_timeout_seconds)
store=SignalStore(settings.database_path)

@app.get("/health")
async def health():
    db_ok=store.check() if hasattr(store,"check") else True
    return {"status":"ok" if db_ok else "degraded","service":"signalhub","version":"0.8.0","mode":"signals_only","database":"ok" if db_ok else "error","execution":"disabled"}

@app.get("/v1/market/tickers")
async def tickers(limit:int=Query(50,ge=1,le=200)):
    try:
        rows=await client.futures_tickers()
        return {"source":"bitunix_public_futures","count":min(limit,len(rows)),"data":rows[:limit]}
    except ExchangeError as exc: raise HTTPException(502,str(exc))

@app.get("/v1/market/klines/{symbol}")
async def klines(symbol:str,interval:str="15m",limit:int=Query(100,ge=20,le=200)):
    try:
        rows=await client.futures_klines(symbol.upper(),interval,limit)
        return {"source":"bitunix_public_futures","symbol":symbol.upper(),"interval":interval,"count":len(rows),"data":[c.__dict__ for c in rows]}
    except (ExchangeError,ValueError) as exc: raise HTTPException(502,str(exc))

@app.get("/v1/analysis/smc/{symbol}")
async def smc_analysis(symbol:str,interval:str="15m",limit:int=Query(200,ge=20,le=200)):
    try:
        candles=await client.futures_klines(symbol.upper(),interval,limit)
        validate_fresh_candles(candles,interval)
        result=analyse_smc(candles)
        return {"source":"bitunix_public_futures","symbol":symbol.upper(),"interval":interval,"candles":len(candles),**result}
    except (ExchangeError,ValueError) as exc: raise HTTPException(502,str(exc))

def apply_risk_gate(signal):
    plan=evaluate_signal_risk(signal,settings.paper_equity_quote,settings.risk_per_trade_pct,
        settings.max_leverage,settings.max_notional_quote,settings.round_trip_cost_bps)
    if not plan.allowed:
        return replace(signal,status="NO_TRADE",risks=[*signal.risks,"Risk gate: "+plan.reason],
                       risk_plan=plan.to_dict())
    return replace(signal,risk_plan=plan.to_dict())

async def scan_one(symbol:str):
    regime,setup,entry,lower=await asyncio.gather(
        client.futures_klines(symbol,"1d",100),
        client.futures_klines(symbol,"4h",100),
        client.futures_klines(symbol,"1h",200),
        client.futures_klines(symbol,"15m",200))
    for candles,tf in ((regime,"1d"),(setup,"4h"),(entry,"1h")): validate_fresh_candles(candles,tf)
    validate_fresh_candles(lower,"15m")
    now_ms=time.time_ns()//1_000_000
    lower=[c for c in lower if c.time_ms+900000<=now_ms]
    result=analyse(symbol,"FUTURES",regime,setup,entry,settings.min_score,settings.min_net_rr,
        settings.min_quote_volume_24h,round_trip_cost_bps=settings.round_trip_cost_bps,
        now_ms=now_ms,lower_tf=lower)
    result=apply_risk_gate(result)
    return {"id":store.save(result),**result.to_dict()}

@app.post("/v1/scan/{symbol}")
async def scan(symbol:str):
    try: return await scan_one(symbol.upper())
    except (ExchangeError,ValueError) as exc: raise HTTPException(502,str(exc))

@app.post("/v1/scan")
async def scan_universe(limit:int=Query(10,ge=1,le=20)):
    try:
        tickers=await client.futures_tickers(); ranked=[]
        for row in tickers:
            try:
                symbol=str(row["symbol"]).upper(); turnover=float(row.get("quoteVol") or 0)
                if symbol.endswith("USDT") and turnover>=settings.min_quote_volume_24h: ranked.append((turnover,symbol))
            except (KeyError,TypeError,ValueError): continue
        symbols=[s for _,s in sorted(ranked,reverse=True)[:limit]]; semaphore=asyncio.Semaphore(3)
        async def bounded(symbol):
            async with semaphore:
                try: return await scan_one(symbol)
                except (ExchangeError,ValueError) as exc: return {"symbol":symbol,"status":"DATA_ERROR","error":str(exc)}
        results=await asyncio.gather(*(bounded(s) for s in symbols))
        return {"scanned":len(results),"candidates":sum(x.get("status")=="CANDIDATE" for x in results),
            "risk_rejected":sum(x.get("status")=="NO_TRADE" and any(str(r).startswith("Risk gate:") for r in x.get("risks",[])) for x in results),
            "data_errors":sum(x.get("status")=="DATA_ERROR" for x in results),"data":results}
    except ExchangeError as exc: raise HTTPException(502,str(exc))

@app.get("/v1/signals")
async def signals(limit:int=Query(50,ge=1,le=200)):
    rows=store.latest(limit); return {"count":len(rows),"data":rows}

@app.get("/v1/signals/{signal_id}")
async def detail(signal_id:int):
    if signal_id<=0: raise HTTPException(400,"Signal ID must be positive")
    rows=[r for r in store.latest(200) if r["id"]==signal_id]
    if not rows: raise HTTPException(404,"Signal not found")
    return rows[0]
