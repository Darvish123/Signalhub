# SignalHub — Bitunix Market Intelligence MVP 0.1

Read-only market analysis for Bitunix Futures. Fetches public market data, applies a transparent 4h/1h/15m screening model, stores candidate/NO_TRADE results in SQLite and exposes a FastAPI interface.

**No live order placement, private API keys, or withdrawal/trading permissions.** This is an engineering MVP, not a proven profitable strategy or investment advice.

## Included
- Public Futures tickers and historical candles.
- 4h regime, 1h alignment, 15m momentum confirmation.
- EMA trend, ATR volatility guard, confirmed swing pivots, structural SL/TP candidates.
- Estimated net reward/risk and score gates; explicit NO_TRADE.
- SQLite history, FastAPI, Docker and CI unit tests.

## Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000/docs and /health.

## Endpoints
- GET /health
- GET /v1/market/tickers
- GET /v1/market/klines/BTCUSDT?interval=15m&limit=100
- POST /v1/scan/BTCUSDT
- GET /v1/signals
- GET /v1/signals/{id}

Run read-only live API smoke test: `python -m scripts.smoke`.
Tests: `python -m unittest discover -s tests -v`.

## Known limitations
- Live exchange requests have not yet been executed from this environment; run smoke test and check CI before relying on output.
- Strategy is a screening heuristic, not validated alpha. No historical backtest or forward paper-trading evidence.
- Fee allowance is a placeholder; calibrate actual fees, spread and slippage. Funding is excluded.
- No OI/funding/liquidation/order-book filters, portfolio risk sizing, dashboard, alerts, auth, or trade lifecycle.
- Spot is not integrated into scanner. No order endpoint exists.

## Next milestones
1. Validate live API payloads, timestamps and rate limits.
2. Implement and test BOS/CHoCH, liquidity sweeps, FVG and order blocks.
3. Add walk-forward backtest with fees/spread/slippage/funding.
4. Add forward paper trading, sizing and portfolio exposure.
5. Add dashboard, alerts, monitoring and deployment.
6. Add a separately validated Spot engine.

Never enable automated execution without separate review and explicit approval.
