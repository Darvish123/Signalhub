# Backtesting protocol

The current SMC backtest consumes a continuous 1-hour LAST_PRICE OHLCV CSV. Required headers: `timestamp_ms,open,high,low,close`; optional `quote_volume,base_volume`. Provide at least 60 days of warm-up for the 1D trend context. Invalid OHLC, duplicate timestamps, and missing/non-hourly intervals are hard failures; data is never silently repaired or interpolated. Use LAST_PRICE for trade execution. MARK_PRICE candles are not trade-volume data and should not be mixed into OHLC execution history.

Download hourly candles:
```bash
python -m scripts.download_history --symbol BTCUSDT --interval 1h --start-ms <UTC_ALIGNED_START_MS> --end-ms <UTC_ALIGNED_END_MS> --out data/BTCUSDT_1h.csv
```

Download historical funding settlements:
```bash
python -m scripts.download_funding --symbol BTCUSDT --start-ms <UTC_START_MS> --end-ms <UTC_END_MS> --out data/BTCUSDT_funding.csv
```

Run the backtest (funding CSV is required):
```bash
python -m app.backtest --csv data/BTCUSDT_1h.csv --funding-csv data/BTCUSDT_funding.csv --symbol BTCUSDT --start 2026-10-01 --end 2026-10-31 --fee-bps 5 --slippage-bps 2 --initial-equity 100 --risk-pct 0.5 --max-leverage 1 --out reports/BTCUSDT_october_2026.json
```

## Execution and accounting

- Directional bias: 1D EMA trend; structure context: 4H confirmed SMC BOS/CHoCH; 1H trigger requires aligned BOS/CHoCH plus a liquidity sweep or FVG.
- All decisions use closed candles only. Entry is next 1H open. No intrabar lookahead; if stop and target are both touched in one candle, stop is assumed first.
- Structural stop is placed beyond confirmed 1H swing invalidation with a 0.10 ATR buffer. Target distance is sized to clear at least 3:1 net reward/risk after the strategy's conservative cost estimate. Backtest execution costs are charged on both entry and exit.
- Position fraction is risk budget divided by entry-to-stop distance, capped by configured maximum leverage. Default starting equity is $100 and risk budget is 0.5% per trade.
- Historical funding is charged/credited only at recorded settlement timestamps while the position is open. Positive funding rates mean longs pay and shorts receive; negative rates reverse the cashflow. Funding is calculated using the settlement mark price and position notional.
- Funding API returns at most 200 records per request; downloader recursively splits time windows to avoid silently truncating dense histories. Compare expected settlement cadence and coverage before trusting results. Missing historical records cannot be reconstructed from the current funding rate.
- This is a single-symbol, one-position-at-a-time model. It does not simulate cross-symbol portfolio correlation, simultaneous exposure, liquidation, or exchange-specific margin tiers. A successful unit-test run is not evidence of profitability.

The Bitunix historical funding endpoint is documented at https://www.bitunix.com/api-docs/futures/market/get_funding_rate_history.html.
