# Backtesting protocol

Input is a continuous 15-minute OHLCV CSV. Required headers: `timestamp_ms,open,high,low,close`; optional `quote_volume,base_volume`. Include at least 9 days of warm-up before the evaluation period; the loader requires 500+ bars. For a full October 2026 test, provide data from at least 2026-09-22 through 2026-11-01 UTC, preferably with several extra days.

Example:
```bash
python -m app.backtest --csv data/BTCUSDT_15m.csv --symbol BTCUSDT --start 2026-10-01 --end 2026-10-31 --fee-bps 5 --slippage-bps 2 --out reports/BTCUSDT_october_2026.json
```

Methodology: strategy is evaluated at each completed 15m close using only closed 1h and 4h bars; execution is next 15m open; one position at a time; stop is assumed hit before target when both are touched in one OHLC bar (conservative); maximum holding is 192 bars (48h); fee and slippage are charged on both sides. Funding is still not modelled and must be added from the exchange's historical funding-rate endpoint before this report can represent full futures carrying costs. Position sizing uses a risk budget per trade: notional/equity fraction = risk fraction / entry-to-stop distance, capped by `--max-leverage` (default 1.0). The equity curve compounds position-weighted returns; the per-trade `net_pnl_pct` remains the underlying position return. This is a simplified single-position model and does not simulate portfolio correlation or simultaneous exposure.

Report includes trade count, win rate, net return, max drawdown, profit factor, average win/loss and exit reasons. A single-symbol one-month backtest is not enough to establish robustness; repeat across symbols, regimes and out-of-sample windows. This harness tests the current EMA/ATR/pivot strategy; SMC indicators are context-only and are not part of entry decisions yet. Do not infer profitability from CI tests.
