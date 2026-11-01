# SignalHub — Bitunix Futures Research MVP 0.3

Read-only market research and signal-candidate screening. No private credentials, order placement, withdrawals or automated execution.

## Capabilities
- Public Bitunix Futures tickers and OHLCV candles.
- Bounded scan of up to 20 liquid USDT perpetuals.
- Multi-timeframe filter: 4h EMA regime, 1h alignment, 15m momentum and ATR volatility guard.
- Structural pivot-based stop/target candidates and estimated RR.
- SMC context: confirmed swings/HH-HL-LH-LL, BOS/CHoCH, single-consumption liquidity sweep events, three-candle FVG, Order Block candidate with mitigation/invalidation lifecycle, and Premium/Discount from the latest adjacent confirmed opposite swing pair.
- SQLite signal history, FastAPI docs, Docker and CI.

## SMC definitions and limitations
All SMC labels are deterministic candle heuristics, not proof of institutional orders or intent. Pivots become available only after right-side confirmation candles. BOS/CHoCH are close-based breaks without displacement validation. Sweeps consume a pivot after first sweep. FVGs are geometric gaps, not automatic entries. OB mitigation means a later candle overlaps the zone; invalidation means a close beyond its distal boundary. OB selection remains heuristic and does not yet require displacement/FVG confluence. Premium/Discount uses an adjacent confirmed high/low pair and is not a fully modelled dealing-range/leg algorithm.

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

## Data quality controls
- OHLCV values must be finite and valid; timestamps must be unique and ordered.
- Scan/SMC analysis rejects stale/future candle series and gaps larger than 1.5 timeframe intervals.
- Freshness thresholds are conservative engineering guards, not guarantees that the exchange feed is correct. Historical kline endpoint is intentionally not freshness-filtered.

## Validation and known limitations
- Run `python -m unittest discover -s tests -v` and `python -m scripts.smoke` (read-only) before local use.
- CI passing only verifies tests/compilation; it does not prove profitability or validate live Bitunix compatibility.
- Strategy remains a screening heuristic. No historical backtest, walk-forward test or forward paper-trading evidence.
- Fee model is still a placeholder; spread, slippage, actual fee tier and funding are not modelled.
- No OI, funding, liquidation, order-book, portfolio risk sizing, aggregate exposure, dashboard, alerts, authentication or trade lifecycle.
- Spot is not integrated. No order endpoint exists.
- Do not expose this unauthenticated API publicly; use locally or behind a trusted private network.

## Next gates before any trading consideration
1. Verify live public API payloads, candle timestamp semantics, rate limits and reconnect behaviour.
2. Add OB displacement/imbalance validation and coherent external/internal dealing ranges.
3. Integrate SMC confluence only after objective definitions and out-of-sample tests.
4. Build event-driven backtest with fees, spread, slippage and funding.
5. Run forward paper trading, track signal lifecycle and report drawdown/expectancy.
6. Add sizing, portfolio exposure/correlation limits, auth, monitoring, alerts and UI.
7. Validate Spot in a separate engine.
No automated execution without separate security, risk and user approval.
