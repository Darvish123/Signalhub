"""Application service for multi-timeframe scans.

This layer coordinates market-data retrieval, strategy evaluation, paper risk
checks, and persistence. HTTP concerns stay in app.main; strategy modules stay
independent of network, storage, and FastAPI.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Any

from app.exchange import (
    BitunixClient,
    ExchangeError,
    INTERVAL_MS,
    validate_fresh_candles,
)
from app.risk import evaluate_signal_risk
from app.storage import SignalStore
from app.strategy import analyse


class ScanService:
    """Coordinate one-symbol and bounded-universe read-only scans."""

    def __init__(self, client: BitunixClient, store: SignalStore, settings: Any):
        self.client = client
        self.store = store
        self.settings = settings

    def apply_risk_gate(self, signal):
        plan = evaluate_signal_risk(
            signal,
            self.settings.paper_equity_quote,
            self.settings.risk_per_trade_pct,
            self.settings.max_leverage,
            self.settings.max_notional_quote,
            self.settings.round_trip_cost_bps,
        )
        if not plan.allowed:
            return replace(
                signal,
                status="NO_TRADE",
                risks=[*signal.risks, "Risk gate: " + plan.reason],
                risk_plan=plan.to_dict(),
            )
        return replace(signal, risk_plan=plan.to_dict())

    async def _closed_series(
        self, symbol: str, interval: str, limit: int, now_ms: int
    ):
        candles = await self.client.futures_klines(symbol, interval, limit)
        validate_fresh_candles(candles, interval, now_ms)
        step = INTERVAL_MS[interval]
        closed = [c for c in candles if c.time_ms + step <= now_ms]
        validate_fresh_candles(closed, interval, now_ms)
        return closed

    async def scan_one(self, symbol: str) -> dict:
        symbol = symbol.upper()
        now_ms = time.time_ns() // 1_000_000
        regime, setup, entry, lower = await asyncio.gather(
            self._closed_series(symbol, "1d", 100, now_ms),
            self._closed_series(symbol, "4h", 100, now_ms),
            self._closed_series(symbol, "1h", 200, now_ms),
            self._closed_series(symbol, "15m", 200, now_ms),
        )
        signal = analyse(
            symbol,
            "FUTURES",
            regime,
            setup,
            entry,
            self.settings.min_score,
            self.settings.min_net_rr,
            self.settings.min_quote_volume_24h,
            round_trip_cost_bps=self.settings.round_trip_cost_bps,
            now_ms=now_ms,
            lower_tf=lower,
        )
        signal = self.apply_risk_gate(signal)
        signal_id = self.store.save(signal)
        return {"id": signal_id, **signal.to_dict()}

    async def scan_universe(self, limit: int = 10) -> dict:
        tickers_data = await self.client.futures_tickers()
        ranked = []
        for row in tickers_data:
            try:
                symbol = str(row["symbol"]).upper()
                turnover = float(row.get("quoteVol") or 0)
                if symbol.endswith("USDT") and turnover >= self.settings.min_quote_volume_24h:
                    ranked.append((turnover, symbol))
            except (KeyError, TypeError, ValueError):
                continue

        symbols = [symbol for _, symbol in sorted(ranked, reverse=True)[:limit]]
        semaphore = asyncio.Semaphore(3)

        async def bounded(symbol: str) -> dict:
            async with semaphore:
                try:
                    return await self.scan_one(symbol)
                except (ValueError, ExchangeError) as exc:
                    return {"symbol": symbol, "status": "DATA_ERROR", "error": str(exc)}

        results = await asyncio.gather(*(bounded(symbol) for symbol in symbols))
        return {
            "scanned": len(results),
            "candidates": sum(row.get("status") == "CANDIDATE" for row in results),
            "risk_rejected": sum(
                row.get("status") == "NO_TRADE"
                and any(str(reason).startswith("Risk gate:") for reason in row.get("risks", []))
                for row in results
            ),
            "data_errors": sum(row.get("status") == "DATA_ERROR" for row in results),
            "data": results,
        }
