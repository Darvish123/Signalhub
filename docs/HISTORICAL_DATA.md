# Historical Bitunix Futures data

The repository's public market client limits each kline request to 200 candles.
For longer test windows, use `scripts/download_history.py`, which paginates
backwards with Bitunix's exclusive `endTime` parameter and validates that the
requested interval-aligned range is complete before writing CSV.

Bitunix's current official documentation states:
- `endTime` is an exclusive candle-open-time bound.
- At most 200 candles are returned per request.
- `startTime` is not supported; use `endTime` plus `limit`.
- Only closed candles are returned, and `time` is the candle open time.

Reference: https://www.bitunix.com/api-docs/futures/market/get_kline
Change log: https://www.bitunix.com/api-docs/futures/log/change_log.html

Example for the October 2026 BTCUSDT 15m test, with warm-up from 22 September
through 1 November UTC (replace the timestamps with UTC-aligned epoch-ms values):

```bash
python -m scripts.download_history \
  --symbol BTCUSDT --interval 15m \
  --start-ms 1790035200000 --end-ms 1793576700000 \
  --out data/BTCUSDT_15m.csv
```

Then run:

```bash
python -m app.backtest --csv data/BTCUSDT_15m.csv \
  --symbol BTCUSDT --start 2026-10-01 --end 2026-10-31 \
  --fee-bps 5 --slippage-bps 2 --out reports/BTCUSDT_october_2026.json
```

The downloader deliberately fails rather than silently producing a partial
dataset if the returned number of candles does not equal the requested
continuous interval count. This is a data-completeness guard, not a guarantee
that exchange history is economically correct. Funding is not downloaded by
this script; the current backtest still does not model funding or position
sizing. Do not interpret its output as a live-trading recommendation.
