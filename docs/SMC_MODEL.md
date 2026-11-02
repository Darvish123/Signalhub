# SMC / ICT model specification

## Purpose and epistemic limits

SignalHub uses reproducible OHLCV price-action heuristics. The words “smart money”, “liquidity”, “order block” and “inducement” are methodology labels; OHLCV cannot identify the participant, resting stop orders, intent, or actual institutional execution. Every detector therefore returns observable/derived levels and timestamps, not claims about who traded.

## Multi-timeframe contract

- 1D: directional bias; no lower-timeframe signal may reverse this bias.
- 4H: confirmed BOS/CHoCH context in the 1D direction.
- 1H: liquidity raid, displacement/MSS, FVG retracement, and OB confluence.
- A pivot is usable only after the configured right-hand confirmation bars close. Decisions use closed bars only.
- Execution simulation enters at the next 1H open; a live signal's close is a reference price, not a guaranteed fill.

## Implemented SMC inventory

| Concept | Operational definition | Use |
|---|---|---|
| Swing structure | Left/right confirmed pivot; HH/HL/LH/LL labels | Structure and liquidity references |
| BOS / CHoCH | Candle close beyond an unconsumed confirmed swing; direction change labels CHoCH | 4H context and 1H trigger |
| BSL / SSL pools | Two or more confirmed highs/lows clustered within explicit price tolerance | Candidate liquidity objectives |
| Liquidity sweep | Wick crosses a confirmed swing and candle closes back inside; level consumed once | ICT sequence |
| Inducement | Last confirmed counter-swing before a structure break; later wick raid is separately marked | Context only; not a standalone trigger |
| FVG | Three-candle wick imbalance | Entry zone and lifecycle |
| FVG lifecycle | UNMITIGATED / PARTIAL / FILLED / INVALIDATED based only on later candles | Prevent stale-gap entries |
| Order Block | Last opposing candle before a close-confirmed BOS/CHoCH; first later overlap mitigates; close beyond distal edge invalidates | Required 1H FVG confluence in strategy |
| Breaker Block | Invalidated OB polarity flips; later zone revisit is recorded | Context only, not standalone entry |
| Dealing range | Latest eligible confirmed opposing swing anchors around a structure break | Range / equilibrium context |
| Premium / Discount | Current close relative to latest adjacent confirmed swing pair equilibrium | Confluence context |
| SMT | Timestamp-aligned relative swing divergence across caller-supplied correlated markets | Research API only; not enabled as a trade gate |

## ICT entry sequence

1. Confirmed swing liquidity is swept and the sweep candle closes back inside.
2. Within the configured bar limit, a same-direction close-confirmed MSS occurs.
3. MSS displacement body is at least 1.2 ATR and body/range at least 0.60.
4. A same-direction 3-candle FVG forms at or adjacent to MSS.
5. A later closed candle retraces into the FVG; current final candle must be the tap.
6. Strategy additionally requires a same-direction, non-invalidated OB overlapping the ICT FVG.
7. Structural stop is beyond the sweep extreme and confirmed swing invalidation with 0.10 ATR buffer. Net RR gate and execution costs remain mandatory.

OTE, premium/discount, killzone, inducement, breaker, and SMT are contextual features, not automatic signals. SMT must only compare genuinely related instruments (for example, a validated pair); it is not safe to compare arbitrary altcoins. NY session times use DST-aware New York time. Crypto trades 24/7, so killzone is optional and requires separate validation.

## Explicit exclusions / future research

Not implemented as production gates: Judas Swing, PO3/AMD phase classification, Turtle Soup, rejection blocks, volume imbalance, VWAP deviation, news/event context, correlated-universe auto-selection, and advanced internal/external structure taxonomy. They should not be added by name alone: each needs a precise rule, causal detector, unit tests, ablation test, and out-of-sample comparison.

## Validation requirements

- Truncation invariance: adding future candles must not change earlier event values or timestamps.
- No lookahead: pivots are not available until right bars close; OB/FVG mitigation is evaluated only after formation.
- Test both directions, equal-level tolerance boundaries, gaps, invalidation, DST, missing timestamps, and malformed OHLC.
- Backtest with fees, slippage, funding, next-bar entry, conservative same-bar stop-first handling, and shared portfolio capital.
- Compare each feature ablation (baseline, +OB, +liquidity pools, +SMT only where paired data exists) against matched/random-entry baselines and out-of-sample windows. Do not interpret a high heuristic score as probability of profit.

SMC/ICT research background is not proof of a trading edge. A large empirical study reported that its tested concepts did not beat a matched random-entry baseline after correcting its methodology; SignalHub must therefore validate every gate empirically rather than assume efficacy: https://github.com/harshatangirala/smc-ict-research
