import time
from fastapi import FastAPI, HTTPException, Query
from app.config import settings
from app.exchange import BitunixClient, ExchangeError, validate_fresh_candles, INTERVAL_MS
from app.storage import SignalStore
from app.smc import analyse_smc
from app.services.scan_service import ScanService

app = FastAPI(
    title="SignalHub",
    version="0.8.1",
    description="Read-only market analysis and paper risk sizing; no order execution.",
)

# Composition root: concrete adapters are wired here, not inside domain rules.
client = BitunixClient(
    settings.bitunix_futures_base_url,
    settings.bitunix_spot_base_url,
    settings.request_timeout_seconds,
)
store = SignalStore(settings.database_path)
scan_service = ScanService(client, store, settings)


@app.get("/health")
async def health():
    try:
        store.check()
        return {
            "status": "ok",
            "service": "signalhub",
            "version": "0.8.1",
            "mode": "signals_only",
            "database": "ok",
            "execution": "disabled",
        }
    except Exception as exc:
        raise HTTPException(503, f"Storage unavailable: {exc}")


@app.get("/v1/market/tickers")
async def tickers(limit: int = Query(50, ge=1, le=200)):
    try:
        rows = await client.futures_tickers()
        return {
            "source": "bitunix_public_futures",
            "count": min(limit, len(rows)),
            "data": rows[:limit],
        }
    except ExchangeError as exc:
        raise HTTPException(502, str(exc))


@app.get("/v1/market/klines/{symbol}")
async def klines(
    symbol: str,
    interval: str = "15m",
    limit: int = Query(100, ge=1, le=200),
):
    try:
        rows = await client.futures_klines(symbol.upper(), interval, limit)
        return {
            "source": "bitunix_public_futures",
            "symbol": symbol.upper(),
            "interval": interval,
            "count": len(rows),
            "data": [c.__dict__ for c in rows],
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except ExchangeError as exc:
        raise HTTPException(502, str(exc))


@app.get("/v1/analysis/smc/{symbol}")
async def smc_analysis(
    symbol: str,
    interval: str = "15m",
    limit: int = Query(200, ge=1, le=200),
):
    try:
        candles = await client.futures_klines(symbol.upper(), interval, limit)
        now_ms = time.time_ns() // 1_000_000
        validate_fresh_candles(candles, interval, now_ms)
        step = INTERVAL_MS[interval]
        closed = [c for c in candles if c.time_ms + step <= now_ms]
        validate_fresh_candles(closed, interval, now_ms)
        result = analyse_smc(closed)
        return {
            "source": "bitunix_public_futures",
            "symbol": symbol.upper(),
            "interval": interval,
            "candles": len(closed),
            **result,
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except ExchangeError as exc:
        raise HTTPException(502, str(exc))


@app.post("/v1/scan/{symbol}")
async def scan(symbol: str):
    try:
        return await scan_service.scan_one(symbol)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except ExchangeError as exc:
        raise HTTPException(502, str(exc))


@app.post("/v1/scan")
async def scan_universe(limit: int = Query(10, ge=1, le=20)):
    try:
        return await scan_service.scan_universe(limit)
    except ExchangeError as exc:
        raise HTTPException(502, str(exc))


@app.get("/v1/signals")
async def signals(limit: int = Query(50, ge=1, le=200)):
    rows = store.latest(limit)
    return {"count": len(rows), "data": rows}


@app.get("/v1/signals/{signal_id}")
async def detail(signal_id: int):
    if signal_id <= 0:
        raise HTTPException(400, "Signal ID must be positive")
    row = store.get(signal_id)
    if row is None:
        raise HTTPException(404, "Signal not found")
    return row
