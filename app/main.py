import asyncio
import time
from dataclasses import replace
from fastapi import FastAPI, HTTPException, Query
from app.config import settings
from app.exchange import BitunixClient, OKXClient, ExchangeError, validate_fresh_candles, INTERVAL_MS
from app.storage import SignalStore
from app.strategy import analyse
from app.smc import analyse_smc
from app.risk import evaluate_signal_risk

app = FastAPI(title="SignalHub", version="0.8.1",
    description="Read-only market analysis and paper risk sizing; no order execution.")
client = BitunixClient(settings.bitunix_futures_base_url, settings.bitunix_spot_base_url,
                       settings.request_timeout_seconds)
market_client = OKXClient(timeout=settings.request_timeout_seconds)
store = SignalStore(settings.database_path)

@app.get("/health")
async def health():
    try:
        store.check()
        return {"status": "ok", "service": "signalhub", "version": "0.8.1",
                "mode": "signals_only", "database": "ok", "execution": "disabled"}
    except Exception as exc:
        raise HTTPException(503, f"Storage unavailable: {exc}")

@app.get("/v1/market/tickers")
async def tickers(limit: int = Query(50, ge=1, le=200)):
    try:
        rows = await client.futures_tickers()
        return {"source": "bitunix_public_futures", "count": min(limit, len(rows)), "data": rows[:limit]}
    except ExchangeError as exc:
        raise HTTPException(502, str(exc))

@app.get("/v1/market/klines/{symbol}")
async def klines(symbol: str, interval: str = "15m", limit: int = Query(100, ge=1, le=200)):
    try:
        rows = await market_client.futures_klines(symbol.upper(), interval, limit)
        return {"source": "okx_usdt_linear_perpetual", "symbol": symbol.upper(),
                "interval": interval, "count": len(rows), "data": [c.__dict__ for c in rows]}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except ExchangeError as exc:
        raise HTTPException(502, str(exc))

@app.get("/v1/analysis/smc/{symbol}")
async def smc_analysis(symbol: str, interval: str = "1h", limit: int = Query(200, ge=1, le=200)):
    if interval == "15m":
        raise HTTPException(400, "15m is reserved for zone-gated Price Action confirmation; SMC analysis is only used on 4H/1H context.")
    if interval not in ("1d", "4h", "1h"):
        raise HTTPException(400, "SMC interval must be one of: 1d, 4h, 1h")
    try:
        candles = await market_client.futures_klines(symbol.upper(), interval, limit)
        now_ms = time.time_ns() // 1_000_000
        validate_fresh_candles(candles, interval, now_ms)
        step = INTERVAL_MS[interval]
        closed = [c for c in candles if c.time_ms + step <= now_ms]
        validate_fresh_candles(closed, interval, now_ms)
        result = analyse_smc(closed)
        return {"source": "okx_usdt_linear_perpetual", "symbol": symbol.upper(),
                "interval": interval, "candles": len(closed), **result}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except ExchangeError as exc:
        raise HTTPException(502, str(exc))

def apply_risk_gate(signal):
    plan = evaluate_signal_risk(signal, settings.paper_equity_quote,
        settings.risk_per_trade_pct, settings.max_leverage,
        settings.max_notional_quote, settings.round_trip_cost_bps)
    if not plan.allowed:
        return replace(signal, status="NO_TRADE",
            risks=[*signal.risks, "Risk gate: " + plan.reason], risk_plan=plan.to_dict())
    return replace(signal, risk_plan=plan.to_dict())

async def _closed_series(symbol: str, interval: str, limit: int, now_ms: int):
    candles = await market_client.futures_klines(symbol, interval, limit)
    validate_fresh_candles(candles, interval, now_ms)
    step = INTERVAL_MS[interval]
    closed = [c for c in candles if c.time_ms + step <= now_ms]
    validate_fresh_candles(closed, interval, now_ms)
    return closed

async def scan_one(symbol: str):
    now_ms = time.time_ns() // 1_000_000
    regime, setup, entry, lower = await asyncio.gather(
        _closed_series(symbol, "1d", 100, now_ms),
        _closed_series(symbol, "4h", 100, now_ms),
        _closed_series(symbol, "1h", 200, now_ms),
        _closed_series(symbol, "15m", 200, now_ms))
    result = analyse(symbol, "FUTURES", regime, setup, entry,
        settings.min_score, settings.min_net_rr, settings.min_quote_volume_24h,
        round_trip_cost_bps=settings.round_trip_cost_bps,
        now_ms=now_ms, lower_tf=lower)
    result = apply_risk_gate(result)
    signal_id = store.save(result)
    return {"id": signal_id, **result.to_dict(),
            "market_data_source": "okx_usdt_linear_perpetual",
            "universe_source": "bitunix_public_futures_tickers"}

@app.post("/v1/scan/{symbol}")
async def scan(symbol: str):
    try:
        return await scan_one(symbol.upper())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except ExchangeError as exc:
        raise HTTPException(502, str(exc))

@app.post("/v1/scan")
async def scan_universe(limit: int = Query(10, ge=1, le=20)):
    try:
        tickers_data = await client.futures_tickers()
        ranked = []
        for row in tickers_data:
            try:
                symbol = str(row["symbol"]).upper()
                turnover = float(row.get("quoteVol") or 0)
                if symbol.endswith("USDT") and turnover >= settings.min_quote_volume_24h:
                    ranked.append((turnover, symbol))
            except (KeyError, TypeError, ValueError):
                continue
        symbols = [s for _, s in sorted(ranked, reverse=True)[:limit]]
        semaphore = asyncio.Semaphore(3)
        async def bounded(symbol):
            async with semaphore:
                try:
                    return await scan_one(symbol)
                except ValueError as exc:
                    return {"symbol": symbol, "status": "DATA_ERROR", "error": str(exc)}
                except ExchangeError as exc:
                    return {"symbol": symbol, "status": "DATA_ERROR", "error": str(exc)}
        results = await asyncio.gather(*(bounded(s) for s in symbols))
        return {"scanned": len(results),
            "ticker_source": "bitunix_public_futures_tickers",
            "market_data_source": "okx_usdt_linear_perpetual",
            "candidates": sum(x.get("status") == "CANDIDATE" for x in results),
            "risk_rejected": sum(x.get("status") == "NO_TRADE" and
                any(str(r).startswith("Risk gate:") for r in x.get("risks", [])) for x in results),
            "data_errors": sum(x.get("status") == "DATA_ERROR" for x in results),
            "data": results}
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
