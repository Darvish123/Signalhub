# SignalHub implementation status — integrated MVP 0.8.1

Last reviewed: 2026-11-02
Repository: Darvish123/Signalhub
Integration branch: integration/risk-signal-engine-v0.8

## Branch audit

The repository was reviewed across all extant branches and open/closed pull requests. The feature history forms a mostly sequential development chain:
- `mvp-v0.1-runtime`: initial read-only FastAPI/Bitunix runtime.
- `feature/smc-indicators-v0.2` and `feature/smc-hardening-v0.3`: SMC analysis, lifecycle/data-quality hardening.
- `feature/backtest-engine-v0.4`: event-driven backtesting.
- `feature/historical-data-fetch-v0.5`: historical candle downloader.
- `feature/risk-sizing-v0.6`: risk-budget sizing, funding accounting, ICT/Price Action and portfolio backtest.
- `feature/bitunix-connectivity-check-v0.7`: API validation and direct raw-candle workflow. This branch had six commits not present in the risk-sizing branch; their useful changes are explicitly ported into this integration branch.
- `audit-and-mvp-roadmap`: the prior implementation audit, superseded by this updated report.

## Integrated application

- Read-only Bitunix Futures client with retries, response/OHLCV validation, candle-type selection, duplicate checks and fixed-interval timestamp alignment.
- Closed-candle-only scan input across 1D, 4H, 1H and 15m. Forming candles are excluded before strategy evaluation.
- Multi-timeframe signal strategy: 1D EMA regime, 4H SMC structure, 1H SMC/ICT confluence and closed 15m Price Action trigger.
- Independent paper risk gate: directional entry/stop validation, position sizing from configured paper equity, stop distance, estimated round-trip friction, max leverage and optional absolute notional cap.
- Signal risk decision is attached to the signal and persisted.
- SQLite signal persistence, direct ID lookup and database health check.
- Historical downloader, event-driven single-symbol backtest, funding-rate accounting and shared-equity portfolio backtest.
- API remains read-only. No exchange order endpoints or private API credentials are used.

## Validation evidence

- GitHub Actions on the integration branch passed dependency installation, unittest discovery and compileall on the current branch head.
- Test success demonstrates the implemented unit/integration contracts only. It does not demonstrate profitable trading, live deployment, full exchange API correctness or live account risk controls.
- A previous public Bitunix connectivity workflow completed successfully on a different feature branch. A previous market-data audit observed invalid OHLC candles in LAST_PRICE data and zero volume across tested MARK_PRICE candles; MARK_PRICE volume must not be used for volume analysis. These observations are historical and must be rechecked before production.
- Direct raw-candle workflow is included for repeatable manual live API checks.

## Known gaps / release blockers

1. Live risk engine does not load actual account balances or aggregate current open positions, open-order risk, cross-symbol correlation, maintenance margin, liquidation tiers or portfolio margin.
2. Fee/slippage inputs are configurable estimates and need calibration to actual venue/account conditions.
3. No signal/trade lifecycle tracker for partial TP, stop-to-BE, trailing stop, expiry and final outcome.
4. No authenticated user model, API keys/roles, rate limiting or public API hardening.
5. No production scheduler, persistent hosted database guarantee, alerting, metrics or verified deployment.
6. Backtests require independent review of timestamp semantics, execution assumptions, fee/funding coverage and out-of-sample robustness. No profitability claim is made.
7. SMC/ICT/Price Action outputs are deterministic OHLC heuristics, not evidence of institutional intent or order flow.

## Operating safety

- Signals-only mode; order execution is disabled.
- Paper equity/risk values are defaults, not real exchange account facts.
- No secrets belong in Git.
- A passing CI run is not permission to trade live. Keep human review and paper trading before considering any future execution integration.
