import asyncio
from fastapi import FastAPI,HTTPException,Query
from app.config import settings
from app.exchange import BitunixClient,ExchangeError
from app.storage import SignalStore
from app.strategy import analyse
app=FastAPI(title="SignalHub",version="0.1.0",description="Read-only market analysis; no order execution.")
client=BitunixClient(settings.bitunix_futures_base_url,settings.bitunix_spot_base_url,settings.request_timeout_seconds)
store=SignalStore(settings.database_path)
@app.get("/health")
async def health(): return {"status":"ok","service":"signalhub","version":"0.1.0","mode":"signals_only"}
@app.get("/v1/market/tickers")
async def tickers(limit:int=Query(50,ge=1,le=200)):
    try:
        x=await client.futures_tickers(); return {"source":"bitunix_public_futures","count":min(limit,len(x)),"data":x[:limit]}
    except ExchangeError as e: raise HTTPException(502,str(e))
@app.get("/v1/market/klines/{symbol}")
async def klines(symbol:str,interval:str="15m",limit:int=Query(100,ge=20,le=200)):
    try:
        x=await client.futures_klines(symbol.upper(),interval,limit); return {"source":"bitunix_public_futures","symbol":symbol.upper(),"interval":interval,"count":len(x),"data":[c.__dict__ for c in x]}
    except (ExchangeError,ValueError) as e: raise HTTPException(502,str(e))
@app.post("/v1/scan/{symbol}")
async def scan(symbol:str):
    try:
        r,s,e=await asyncio.gather(client.futures_klines(symbol.upper(),"4h",100),client.futures_klines(symbol.upper(),"1h",100),client.futures_klines(symbol.upper(),"15m",100))
        out=analyse(symbol.upper(),"FUTURES",r,s,e,settings.min_score,settings.min_net_rr,settings.min_quote_volume_24h)
        return {"id":store.save(out),**out.to_dict()}
    except (ExchangeError,ValueError) as ex: raise HTTPException(502,str(ex))
@app.get("/v1/signals")
async def signals(limit:int=Query(50,ge=1,le=200)):
    x=store.latest(limit); return {"count":len(x),"data":x}
@app.get("/v1/signals/{signal_id}")
async def detail(signal_id:int):
    x=[r for r in store.latest(200) if r["id"]==signal_id]
    if not x: raise HTTPException(404,"Signal not found")
    return x[0]
