import asyncio
from fastapi import FastAPI,HTTPException,Query
from app.config import settings
from app.exchange import BitunixClient,ExchangeError
from app.storage import SignalStore
from app.strategy import analyse
from app.smc import analyse_smc
app=FastAPI(title="SignalHub",version="0.2.0",description="Read-only market analysis with deterministic SMC indicators; no order execution.")
client=BitunixClient(settings.bitunix_futures_base_url,settings.bitunix_spot_base_url,settings.request_timeout_seconds)
store=SignalStore(settings.database_path)

@app.get("/health")
async def health():
    return {"status":"ok","service":"signalhub","version":"0.2.0","mode":"signals_only"}

@app.get("/v1/market/tickers")
async def tickers(limit:int=Query(50,ge=1,le=200)):
    try:
        rows=await client.futures_tickers()
        return {"source":"bitunix_public_futures","count":min(limit,len(rows)),"data":rows[:limit]}
    except ExchangeError as exc:
        raise HTTPException(502,str(exc))

@app.get("/v1/market/klines/{symbol}")
async def klines(symbol:str,interval:str="15m",limit:int=Query(100,ge=20,le=200)):
    try:
        rows=await client.futures_klines(symbol.upper(),interval,limit)
        return {"source":"bitunix_public_futures","symbol":symbol.upper(),"interval":interval,"count":len(rows),"data":[c.__dict__ for c in rows]}
    except (ExchangeError,ValueError) as exc:
        raise HTTPException(502,str(exc))

@app.get("/v1/analysis/smc/{symbol}")
async def smc_analysis(symbol:str,interval:str="15m",limit:int=Query(200,ge=20,le=200)):
    """Return deterministic candle-based SMC indicators; this endpoint does not issue trade instructions."""
    try:
        candles=await client.futures_klines(symbol.upper(),interval,limit)
        result=analyse_smc(candles)
        return {"source":"bitunix_public_futures","symbol":symbol.upper(),"interval":interval,"candles":len(candles),**result}
    except (ExchangeError,ValueError) as exc:
        raise HTTPException(502,str(exc))

async def scan_one(symbol:str):
    regime,setup,entry=await asyncio.gather(
        client.futures_klines(symbol,"4h",100),
        client.futures_klines(symbol,"1h",100),
        client.futures_klines(symbol,"15m",100))
    result=analyse(symbol,"FUTURES",regime,setup,entry,settings.min_score,settings.min_net_rr,settings.min_quote_volume_24h)
    return {"id":store.save(result),**result.to_dict()}

@app.post("/v1/scan/{symbol}")
async def scan(symbol:str):
    try:
        return await scan_one(symbol.upper())
    except (ExchangeError,ValueError) as exc:
        raise HTTPException(502,str(exc))

@app.post("/v1/scan")
async def scan_universe(limit:int=Query(10,ge=1,le=20)):
    """Scan the most liquid USDT perpetuals by 24h quote turnover; bounded to 20 symbols."""
    try:
        tickers=await client.futures_tickers()
        ranked=[]
        for row in tickers:
            try:
                symbol=str(row["symbol"]).upper()
                turnover=float(row.get("quoteVol") or 0)
                if symbol.endswith("USDT") and turnover>=settings.min_quote_volume_24h:
                    ranked.append((turnover,symbol))
            except (KeyError,TypeError,ValueError):
                continue
        symbols=[s for _,s in sorted(ranked,reverse=True)[:limit]]
        semaphore=asyncio.Semaphore(3)
        async def bounded(symbol):
            async with semaphore:
                try:
                    return await scan_one(symbol)
                except (ExchangeError,ValueError) as exc:
                    return {"symbol":symbol,"status":"DATA_ERROR","error":str(exc)}
        results=await asyncio.gather(*(bounded(s) for s in symbols))
        return {"scanned":len(results),"candidates":sum(x.get("status")=="CANDIDATE" for x in results),"data_errors":sum(x.get("status")=="DATA_ERROR" for x in results),"data":results}
    except ExchangeError as exc:
        raise HTTPException(502,str(exc))

@app.get("/v1/signals")
async def signals(limit:int=Query(50,ge=1,le=200)):
    rows=store.latest(limit)
    return {"count":len(rows),"data":rows}

@app.get("/v1/signals/{signal_id}")
async def detail(signal_id:int):
    rows=[r for r in store.latest(200) if r["id"]==signal_id]
    if not rows:
        raise HTTPException(404,"Signal not found")
    return rows[0]
