"""Bitunix public historical funding-rate downloader and deterministic settlement accounting."""
import asyncio,csv
from dataclasses import dataclass
from pathlib import Path
import httpx

@dataclass(frozen=True)
class FundingRate:
    funding_time_ms:int
    funding_rate:float
    mark_price:float

async def download_funding(symbol:str,start_ms:int,end_ms:int,base_url:str="https://fapi.bitunix.com",timeout:float=15.)->list[FundingRate]:
    if start_ms>=end_ms: raise ValueError("start_ms must be before end_ms")
    url=base_url.rstrip("/")+"/api/v1/futures/market/get_funding_rate_history"
    records={}
    async with httpx.AsyncClient(timeout=timeout) as client:
        async def fetch(a:int,b:int,depth:int=0):
            response=await client.get(url,params={"symbol":symbol.upper(),"startTime":a,"endTime":b,"limit":200})
            response.raise_for_status(); payload=response.json()
            await asyncio.sleep(.12)  # respect the documented public API request rate
            if not isinstance(payload,dict) or str(payload.get("code")) not in ("0","200"):
                raise RuntimeError(f"Bitunix funding API error: {payload}")
            rows=payload.get("data")
            if not isinstance(rows,list): raise RuntimeError("Funding response data is not a list")
            if len(rows)>=200:
                if depth>=24 or b-a<=1: raise RuntimeError("Funding endpoint pagination cannot safely split this interval")
                mid=(a+b)//2
                await fetch(a,mid,depth+1); await fetch(mid+1,b,depth+1); return
            for row in rows:
                t=int(row["fundingTime"]); rate=float(row["fundingRate"]); mark=float(row["markPrice"])
                if a<=t<=b and mark>0: records[t]=FundingRate(t,rate,mark)
        await fetch(start_ms,end_ms)
    return [records[t] for t in sorted(records)]

def load_funding_csv(path:str)->list[FundingRate]:
    rows=[]
    with open(path,newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f); required={"funding_time_ms","funding_rate","mark_price"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames): raise ValueError("Funding CSV requires funding_time_ms,funding_rate,mark_price")
        for row in reader:
            x=FundingRate(int(row["funding_time_ms"]),float(row["funding_rate"]),float(row["mark_price"]))
            if x.mark_price<=0: raise ValueError("Funding mark_price must be positive")
            rows.append(x)
    rows.sort(key=lambda x:x.funding_time_ms)
    if len({x.funding_time_ms for x in rows})!=len(rows): raise ValueError("Duplicate funding settlement timestamp")
    return rows

def save_funding_csv(rows:list[FundingRate],path:str)->None:
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["funding_time_ms","funding_rate","mark_price"]); w.writeheader()
        for x in rows: w.writerow({"funding_time_ms":x.funding_time_ms,"funding_rate":x.funding_rate,"mark_price":x.mark_price})

def funding_cashflow_pct(side:str,entry_price:float,position_notional_fraction:float,funding_rate:float,mark_price:float)->float:
    if side not in ("LONG","SHORT") or entry_price<=0 or mark_price<=0 or position_notional_fraction<0:
        raise ValueError("Invalid funding calculation inputs")
    sign=1. if side=="LONG" else -1.
    return -sign*funding_rate*(mark_price/entry_price)*position_notional_fraction*100.
