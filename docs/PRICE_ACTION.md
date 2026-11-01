# Lower-timeframe Price Action trigger

## Independent detector
`app/price_action.py` evaluates the latest completed 15-minute candle independently of SMC and ICT. It detects:
- Sweep and reclaim of the previous 8-bar extreme, with a directional close near the far end of the candle.
- Directional body engulfing of the previous candle.
- Three-bar micro breakout/breakdown with an impulse body.

The output contains pattern, direction, trigger level, invalidation extreme, body ratio, close location and score. It is not a standalone trade signal.

## Integrated live flow
1. 1D directional bias.
2. 4H aligned SMC BOS/CHoCH.
3. 1H SMC liquidity context, ICT sweep/displacement/MSS/FVG retracement and matching OB.
4. 15m aligned Price Action trigger.
5. Combine 1H structural invalidation with 15m trigger invalidation; preserve net RR and cost checks.

OHLC patterns are heuristics, not tape/order-flow evidence. Backtests must use genuine 15m history; synthesizing 15m candles from 1H bars is invalid. Existing 1H-only backtests do not validate this added trigger.
