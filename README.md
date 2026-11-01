# SignalHub — Bitunix Market Intelligence MVP 0.2

Read-only Bitunix Futures market analysis. Version 0.2 adds a deterministic Smart Money Concepts (SMC) indicator layer alongside the original 4h/1h/15m EMA/ATR screening engine.

**No live order placement, private API keys, or withdrawal/trading permissions.** This is an engineering/research tool, not a proven profitable strategy or investment advice.

## SMC indicator definitions

- **Confirmed swing high/low:** local extremum with configurable left/right candles. A pivot is only known after the right-side confirmation candles close.
- **HH / LH / HL / LL:** each confirmed swing high is compared with the previous confirmed high; each swing low with the previous confirmed low.
- **BOS:** candle close beyond the latest eligible confirmed swing level in the current/initial direction.
- **CHoCH:** close-based break against the previously detected structure direction. The first detected break is labelled BOS because no prior trend is known.
- **Liquidity sweep:** wick trades beyond a prior confirmed swing level and the candle closes back inside that level.
- **FVG:** three-candle gap; bullish when candle 3 low is above candle 1 high, bearish when candle 3 high is below candle 1 low.
- **Order block:** last opposite-colour candle within a configurable lookback before a detected BOS/CHoCH. This is a heuristic; mitigation lifecycle is not yet tracked.
- **Premium / Discount:** current close compared with the midpoint of the latest available confirmed swing high/low range.

These are explicit candle-derived heuristics. They do not identify actual institutional participants, resting orders, intent, or guaranteed support/resistance. SMC outputs are context for human review, not standalone entry instructions.

## Included
- Public Futures tickers and historical candles.
- Bounded universe scan of up to 20 liquid USDT perpetuals (default 10).
- 4h regime, 1h alignment, 15m momentum confirmation.
- EMA trend, ATR volatility guard, confirmed swing pivots, structural SL/TP candidates.
- SMC indicator module: structure labels/events, sweeps, FVGs, order-block candidates, premium/discount.
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
- GET /v1/analysis/smc/BTCUSDT?interval=15m&limit=200 — SMC indicator snapshot
- POST /v1/scan/BTCUSDT — scan one contract
- POST /v1/scan?limit=10 — scan most liquid eligible USDT perpetuals
- GET /v1/signals
- GET /v1/signals/{id}

Run read-only live API smoke test: `python -m scripts.smoke`.
Tests: `python -m unittest discover -s tests -v`.

## Known limitations / safety
- Live exchange requests have not yet been executed from this environment; run smoke test and inspect CI before relying on output.
- Strategy is a screening heuristic, not validated alpha. No historical backtest or forward paper-trading evidence.
- Fee allowance is a placeholder; calibrate actual fees, spread and slippage. Funding is excluded.
- No OI/funding/liquidation/order-book filters, portfolio risk sizing, dashboard, alerts, authentication, or trade lifecycle.
- Spot is not integrated into scanner. No order endpoint exists.
- SMC rules are initial, deterministic definitions. They need replay/backtest validation, edge-case review and market/timeframe calibration.
- **Do not expose this unauthenticated API publicly.** Run locally or behind a trusted private network until authentication and deployment hardening are added.

## Next milestones
1. Validate live API payloads, timestamps and rate limits.
2. Add SMC confluence scoring only after objective definitions and tests are reviewed.
3. Add walk-forward backtest with fees/spread/slippage/funding.
4. Add forward paper trading, sizing and portfolio exposure.
5. Add auth, dashboard, alerts, monitoring and deployment.
6. Add a separately validated Spot engine.

Never enable automated execution without separate review and explicit approval.
