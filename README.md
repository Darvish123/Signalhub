# SignalHub — Bitunix Futures Research MVP 0.8

Read-only market research, multi-timeframe signal screening and paper risk sizing. No private credentials, order placement, withdrawals or automated execution.

## Integrated signal pipeline
- Public Bitunix Futures ticker and OHLCV retrieval.
- 1D directional bias (EMA20/EMA50).
- 4H confirmed SMC structure alignment.
- 1H BOS/CHoCH, liquidity sweep/FVG and ICT-style sweep → displacement/MSS → FVG retracement confluence.
- 15m closed-candle price-action trigger.
- Structural invalidation stop, net reward/risk and rolling 24-closed-hour quote-volume gate.
- Fail-closed handling: insufficient, invalid, stale or incomplete inputs produce NO_TRADE / DATA_ERROR rather than a forced signal.

SMC/ICT/price-action detections are deterministic OHLC heuristics, not proof of institutional orders, intent or predictive edge.

## Risk engine
Every scan candidate passes through `app.risk.evaluate_signal_risk` before storage/return:
- Validates direction, entry and stop geometry.
- Sizes notional and quantity from configured paper equity and risk budget.
- Includes configured estimated round-trip friction in the risk budget.
- Enforces maximum leverage and optional absolute notional cap.
- Converts failed risk checks into NO_TRADE and stores the risk decision with the signal.

Defaults are paper assumptions, not account facts: PAPER_EQUITY_QUOTE=1000, RISK_PER_TRADE_PCT=0.5, MAX_LEVERAGE=1.0, ROUND_TRIP_COST_BPS=14. No exchange balance is queried. No portfolio open-position exposure is available to the live scanner yet. The separate event-driven portfolio backtest applies shared equity, max concurrent positions and aggregate open-risk limits, but does not model correlation or liquidation tiers.

## Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000/docs.

## Endpoints
- GET /health
- GET /v1/market/tickers
- GET /v1/market/klines/{symbol}?interval=15m&limit=100
- GET /v1/analysis/smc/{symbol}?interval=15m&limit=200
- POST /v1/scan/{symbol}
- POST /v1/scan?limit=10
- GET /v1/signals
- GET /v1/signals/{id}

## Backtesting
The repository includes a single-position 1H execution backtest with 1D/4H/1H SMC strategy, risk-budget sizing and historical funding accounting, plus a separate event-driven multi-symbol portfolio allocator. These are research tools; run them on verified historical datasets and inspect funding coverage before interpreting results.

## Validation and limitations
- Run `python -m unittest discover -s tests -v` and `python -m compileall -q app scripts`.
- CI passing verifies tests/compilation only; it does not prove profitability, live API correctness or deployment.
- No walk-forward/robust out-of-sample evidence or forward paper-trading track record is claimed.
- Fee/slippage assumptions must be calibrated to the actual account/market. Funding history completeness must be checked.
- Live scanner does not yet aggregate open positions, correlation, account margin, liquidation buffers or exchange-specific risk tiers.
- No trade lifecycle tracker, authentication, user roles, alerting or production monitoring.
- Do not expose this unauthenticated API publicly. No order endpoint exists.

## Safety
SignalHub remains read-only. Risk outputs are paper estimates, not a promise of maximum realized loss: gaps, liquidity, slippage, fees, funding and exchange mechanics can increase losses. No automated execution without separate security, risk and explicit user approval.


## Architecture

The FastAPI layer delegates scan orchestration to `app.services.ScanService`.
The service coordinates the public market-data adapter, pure strategy facade,
paper risk gate, and SQLite signal repository. Strategy and detector modules
remain independent of HTTP, network, and persistence concerns.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the dependency direction,
module ownership, data contracts, safety boundaries, and staged package layout.
