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

## Multi-symbol shared-equity portfolio mode

The portfolio runner accepts one continuous 1H LAST_PRICE CSV and one historical funding CSV per symbol. File names are `SYMBOL_1h.csv` and `SYMBOL_funding.csv` under `data/`. Each symbol must include at least 60 days of hourly warm-up before the requested test start, plus the full test interval. Missing funding files are a hard failure.

Example:
```bash
python -m scripts.run_portfolio_backtest \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --data-dir data \
  --start-ms <UTC_TEST_START_MS> --end-ms <UTC_TEST_END_MS> \
  --fee-bps 5 --slippage-bps 2 --initial-equity 100 \
  --risk-pct 0.5 --max-leverage 1 \
  --max-positions 5 --max-open-risk-pct 2 \
  --out reports/portfolio.json
```

The portfolio engine generates each symbol's closed-candle candidate trades, merges entries by timestamp, then allocates against one shared account. Default caps of five simultaneous positions and 2% aggregate open stop-risk are conservative engineering defaults, not user-validated optimal parameters. PnL is applied to the shared equity using the equity committed when each trade was opened. Positions rejected by the concurrency or open-risk cap are reported separately. This first portfolio version does not model cross-symbol correlation, liquidation, maintenance margin, exchange portfolio margin, or intrabar order contention; these remain explicit limitations and must be addressed before treating the simulation as production-grade.

## ICT integration

The ICT implementation is in `app/ict.py`. It is a native deterministic OHLC implementation, not copied third-party source. Its entry sequence is deliberately strict:

1. A confirmed swing liquidity level is swept and the candle closes back inside.
2. Within eight bars, price closes through the relevant confirmed structure level.
3. The MSS candle must meet the displacement thresholds (body at least 1.2 ATR and body/range at least 0.60).
4. A same-direction three-candle FVG must form at/adjacent to the MSS.
5. Price must subsequently retrace into the FVG, and the latest closed candle must be that tap.
6. The stop is placed beyond the sweep extreme and a 0.10 ATR buffer; the existing minimum 3R net cost gate remains in force.

OTE, premium/discount and NY killzone are confluence metadata rather than mandatory gates by default. Enable `ict_require_killzone=True` only for a separately tested session-specific experiment. London is 02:00-05:00 New York time, NY AM 07:00-10:00, NY PM 13:00-16:00; DST is handled by the standard timezone database. Crypto is 24/7, so off-session trades are not automatically rejected.

The public scan now requests 1D/4H/1H candles to match the strategy contract; the former 4H/1H/15m request did not match the strategy's declared 1D/4H/1H input semantics.

ICT terminology is not a claim that institutional orders can be identified from OHLC. See the concept references used for the rule definitions: https://github.com/SrsBlack/ict-knowledge-library and https://ictradingconcepts.com/ict/market-structure-shift/.
