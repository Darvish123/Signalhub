# SignalHub — Bitunix Futures Research MVP 0.8

Read-only market research, multi-timeframe signal screening and paper risk sizing. No private credentials, order placement, withdrawals or automated execution.

## Integrated signal pipeline
- Bitunix public Futures tickers for universe selection; OKX USDT linear perpetual OHLCV for all 1D/4H/1H/15m analysis, matching the historical backtest price source.
- 1D directional bias (EMA20/EMA50).
- 4H confirmed structure plus nearby supply/demand candidate zone (non-invalidated 4H order-block heuristic).
- 1H refines the 4H zone by intersection with an aligned 1H order block or FVG; an aligned equal-high/low pool or recent sweep must be structurally located inside the parent 4H zone. Zone/liquidity proximity and stop invalidation use market structure, not ATR distance or ATR padding.
- 15m is Price Action only: the latest fully closed candle must close inside the 1H-refined zone and confirm an aligned candle pattern. 15m SMC/ICT structure is not used for entry.
- Structural invalidation stop, net reward/risk and rolling 24-closed-hour quote-volume gate.
- Fail-closed handling: insufficient, invalid, stale or incomplete inputs produce NO_TRADE / DATA_ERROR rather than a forced signal.

Structure, zone, liquidity and price-action detections are deterministic OHLC heuristics, not proof of resting orders, institutional activity, intent or predictive edge. The ICT sequence is no longer a mandatory entry gate in this zone-first pipeline.

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
- GET /v1/analysis/smc/{symbol}?interval=4h&limit=200 (SMC context only on 1D/4H/1H; 15m is PA-only)
- POST /v1/scan/{symbol}
- POST /v1/scan?limit=10
- GET /v1/signals
- GET /v1/signals/{id}

## Backtesting
The live scan and historical backtest now share the same OKX USDT linear perpetual OHLCV provider for 1D/4H/1H/15m analysis. Bitunix supplies the public ticker universe and historical funding/mark data. The 1H execution backtest uses the same 4H-zone → 1H-refinement/liquidity → 15m in-zone Price Action sequence as the live strategy, with only fully closed 15m candles, and a separate event-driven multi-symbol portfolio allocator. This remains a cross-venue benchmark, not exact Bitunix execution; inspect every data audit before interpreting results. The portfolio report also includes per-symbol hourly signal-rejection diagnostics so a zero-trade run can be traced to the exact strategy gate without weakening the live or backtest rules. The diagnostics are observational only and do not change trade selection.

## Validation and limitations
- Run `python -m unittest discover -s tests -v` and `python -m compileall -q app scripts`.
- CI passing verifies tests/compilation only; it does not prove profitability, live API correctness or deployment.
- No walk-forward/robust out-of-sample evidence or forward paper-trading track record is claimed.
- Fee/slippage assumptions must be calibrated to the actual account/market. Funding history completeness must be checked.
- Live scanner does not yet aggregate open positions, correlation, account margin, liquidation buffers or exchange-specific risk tiers. Portfolio maximum drawdown is currently realized-only at closed-trade exits and excludes intra-trade unrealized mark-to-market drawdown.
- No trade lifecycle tracker, authentication, user roles, alerting or production monitoring.
- Do not expose this unauthenticated API publicly. No order endpoint exists.

## Safety
SignalHub remains read-only. Risk outputs are paper estimates, not a promise of maximum realized loss: gaps, liquidity, slippage, fees, funding and exchange mechanics can increase losses. No automated execution without separate security, risk and explicit user approval.
