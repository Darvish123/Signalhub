# SignalHub — Bitunix Futures Signal SaaS

Signals-only service (no order execution). Implements the 5-layer analyst spec:
Regime (BTC) -> Structure (1D/4H) -> Liquidity/SMC (1H) -> Price Action (15m/5m) -> Risk/Score.
Long and short use **one code path**: shorts mirror prices (`mirror_bundle`), get evaluated as
long, then levels are flipped back — this is enforced by `test_mirror_symmetry` and
`test_short_signal_is_the_mirror`.

## Architecture

```
app/
  config.py         all settings, from .env
  models.py         Bundle / Setup dataclasses, timeframe constants
  data/
    bitunix.py       public REST client (kline only — no API key needed for signals)
    synthetic.py      deterministic fake market for sandbox testing
    provider.py       turns raw candles into a clean multi-timeframe Bundle
                       (drops forming candles, rejects NaN/stale/corrupt data)
  analysis/
    indicators.py     ATR, EMA, RSI, efficiency ratio, ATR percentile rank
    structure.py       swing pivots, HH/HL vs LH/LL trend
    smc.py              equal highs/lows, liquidity sweep, FVG, order block
    setup.py            Layers 2-4 combined -> Setup (zone/SL/targets/score parts)
  engine/
    regime.py           Layer 1 — market regime gate from BTC
    risk.py              Layer 5 — deterministic SL/TP/RR/size/leverage/margin math
    tracker.py            walks 5m candles forward, applies TP1/TP2/TP3 + trailing SL
    formatter.py           renders the exact FUTURES SIGNAL / NO TRADE text blocks
    engine.py                ties it together: scan_once(), track_all()
  storage.py            SQLite: signals, scans, hashed subscriber API keys
  notifier.py            optional Telegram broadcast
  worker.py               background loop: track open signals, scan on interval
  main.py                  FastAPI app (subscriber endpoints + admin key issuance)
scripts/
  check_api.py           run FIRST against the real exchange — validates payload shape
  scan_once.py             one manual scan, printed (live or --synthetic)
  create_key.py             issue a subscriber API key from the CLI
tests/
  scenario.py               engineered sweep+OB market (proves the positive path exists)
  test_engine.py            16 tests: tracker, risk math, gates, positive path, API glue
```

## Install

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` needs **no API key** for signals — kline/ticker endpoints are public. Fill in
`ADMIN_TOKEN` (random string, used to mint subscriber keys) and, optionally, a Telegram
bot token if you want push notifications.

## Before going live

```bash
python -m scripts.check_api BTCUSDT
```

This hits the real Bitunix endpoint and prints, per timeframe: whether the newest candle is
still forming (the code assumes `time` = candle **open** time — if the exchange instead
returns close time, `provider.py`'s staleness check will reject data and you'll see it
immediately, not silently trade on the wrong bar), and whether `quoteVol`/`baseVol` came back
in the order documented (flip `BITUNIX_SWAP_VOL_FIELDS=true` in `.env` if not — the script
tells you which).

## Run

```bash
# one-off, no server:
python -m scripts.scan_once --synthetic     # sandbox
python -m scripts.scan_once                 # live (public data only)

# full service:
uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
# or: docker build -t signalhub . && docker run -p 8000:8000 --env-file .env signalhub
```

Issue a subscriber key:
```bash
python -m scripts.create_key alice pro     # or: basic
curl -H "X-API-Key: sk_..." localhost:8000/v1/signals
```

`PLANS=basic:15,pro:0` in `.env` means `basic` sees signals 15 minutes delayed,
`pro` sees them in real time — this is the free/paid gate. Signals are computed once and
served to every plan; delay is applied at read time in `main.py`, not by running the engine
twice.

## Endpoints

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /health` | none | |
| `GET /v1/signals?status=ACTIVE\|CLOSED\|ALL` | `X-API-Key` | plan delay applied |
| `GET /v1/signals/{id}` | `X-API-Key` | |
| `GET /v1/scan/latest` | `X-API-Key` | last scan incl. `NO TRADE` text |
| `GET /v1/stats` | `X-API-Key` | win/loss/avg-R of closed signals |
| `POST /admin/keys` | `X-Admin-Token` | `{"label":"alice","plan":"pro"}` |

## What was tested (sandbox, no exchange access)

`python -m unittest discover -s tests -v` — 16 tests, all passing:
- **Tracker** (5): SL-first-on-ambiguous-bar, TP1→breakeven, TP2→trail, full TP3, short mirrors
  long, expiry, forming-bar-not-touched.
- **Risk math** (2): position size solves exactly `qty × (SL_dist + costs) = risk_budget`;
  rejects when RR<3, SL too tight vs ATR, 5 positions already open, total-risk cap breached,
  insufficient free margin.
- **Random-market invariants** (1, 180 symbol×seed×drift combos): every signal ever produced
  satisfies SL<entry<targets ordering, RR≥3 net of fees, score≥75, margin≤equity,
  leverage∈[3,7], duration≤12h, SL inside a safe liquidation buffer, and the printed text
  contains every required field from the spec's template.
- **Positive path** (4, engineered sweep→order-block scenario): proves a LONG signal *is*
  produced when the setup is genuinely there, that SHORT is a true mirror of LONG (same score,
  RR within float tolerance), that raising `min_score` or `min_quote_volume` correctly blocks
  it, and that `scan_once` issues one signal then returns `NO TRADE` on the next scan (no
  duplicate).
- **Data layer** (2): stale/frozen feed raises `DataError` instead of running on old candles;
  mirroring is involutive (`mirror(mirror(x)) == x`).
- **Storage** (1): API key hashing/verification, closed-trade stats aggregation.

The synthetic market (`app/data/synthetic.py`) is a stochastic-volatility random walk with
BTC-correlated alts — useful for exercising the pipeline and finding bugs, but it has **no
real edge**, and the 180-combo run above found **zero organic signals** at the default
strict thresholds (that's expected: real edge/backtesting was out of scope — I built and
tested the *pipeline*, not a profitable strategy. The engineered scenario in `scenario.py`
exists specifically to prove signal generation works at all).

## Known limitations / what I'd want checked against the real API before trusting output

1. **Candle time semantics** (`open` vs `close` time) — `check_api.py` flags this; I read the
   docs as "time = open time" but the field isn't documented explicitly.
2. **`quoteVol`/`baseVol` field order** — same script checks this.
3. No live run against Bitunix yet (network is disabled in my sandbox) — run `check_api.py`
   and one `scan_once.py` (non-`--synthetic`) before trusting the first real signal.
4. Rate limits aren't in the docs I could reach — the client retries 3x with backoff on
   failure but has no explicit throttle; watch logs for 429s and I'll add one.
5. No backtest of the strategy itself — thresholds (min RR 1:3, score≥75, SL 0.35–1.4×ATR)
   come straight from your spec, not from historical validation.
