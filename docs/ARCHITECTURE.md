# SignalHub architecture

## Scope and safety boundary

SignalHub is a read-only Bitunix Futures research and signal-screening application.
The runtime may retrieve public market data, evaluate deterministic OHLCV rules,
calculate paper-only risk plans, and persist research signals. It must not submit,
modify, or cancel exchange orders. Paper equity and cost assumptions are
configuration inputs, not verified account facts.

## Runtime dependency direction

```text
HTTP/API (app.main)
       |
       v
Application services (app.services)
       |
       +------> Market data adapter (app.exchange)
       |
       +------> Strategy facade (app.strategy)
       |             |
       |             +--> app.analysis
       |             +--> app.smc
       |             +--> app.ict
       |             +--> app.price_action
       |
       +------> Risk policy (app.risk)
       |
       +------> Persistence port (app.storage / SignalStore)
                         |
                         v
                       SQLite
```

Backtesting is an offline application path. It reuses domain/strategy logic but
loads historical files and must not depend on FastAPI or live exchange clients.

## Existing module responsibilities

| Module | Responsibility | Must not own |
|---|---|---|
| `models.py` | Candle and Signal domain data structures | HTTP, SQL, exchange calls |
| `analysis.py` | Pure indicator and pivot calculations | I/O |
| `smc.py`, `ict.py`, `price_action.py` | Deterministic OHLCV detectors | I/O, persistence |
| `strategy.py` | Multi-timeframe decision rules | HTTP, SQL, network |
| `exchange.py` | Bitunix public market-data adapter and validation | Strategy decisions, risk sizing |
| `risk.py` | Paper risk validation and position sizing | Exchange execution/account claims |
| `services/scan_service.py` | Orchestrate data -> strategy -> risk -> persistence | HTTP response formatting |
| `storage.py` | SQLite persistence and retrieval | Strategy decisions |
| `main.py` | FastAPI routes, request validation, HTTP error mapping, composition root | Strategy implementation |
| `backtest.py`, `portfolio.py` | Historical simulation and portfolio accounting | Live API runtime |
| `config.py` | Environment-backed settings | Runtime business logic |

## Canonical scan flow

1. API validates the request and calls the scan application service.
2. The service fetches 1D, 4H, 1H and 15m series concurrently from the public
   market-data adapter.
3. The adapter and service reject malformed, stale, misaligned, duplicate, or
   still-forming candles. Only fully closed candles enter the strategy.
4. The strategy evaluates 1D directional bias, 4H structure, 1H SMC/ICT
   confluence, and the closed 15m price-action trigger.
5. The independent risk policy converts a candidate to NO_TRADE when paper
   sizing constraints fail.
6. The service persists the final decision and returns a domain-derived result.
7. The API maps the result to HTTP without embedding trading rules.

## Contracts and invariants

- Domain/strategy code is deterministic for the same inputs and decision time.
- No strategy or detector module imports FastAPI, SQLite, or an exchange client.
- All timestamps are UTC epoch milliseconds.
- Candle series are strictly chronological; malformed or incomplete data fails
  closed. No silent interpolation or synthetic OHLC repair.
- Forming candles are excluded before strategy evaluation.
- A score is a rule score, not a probability of profit.
- Risk plans use configured paper equity only and never imply actual account
  exposure, margin, or liquidation distance.
- Persist the final risk-gated signal, not an unapproved pre-risk candidate.
- Network, strategy, risk, and storage failures remain distinguishable in logs
  and API errors; no failure should be converted into a trade.

## Data and persistence boundary

SQLite is the current local MVP repository for generated signals. It is not a
market-data warehouse or a production multi-instance database. The repository
interface should remain small (save/get/latest/check), allowing a future
PostgreSQL implementation without changing strategy or route behavior.

The SQLite schema should evolve through explicit, backward-compatible schema
versioning before adding trade lifecycle, users, or large historical candle
tables. Keep historical OHLCV and backtest artifacts in files/object storage
until a measured query requirement justifies a database migration.

## Target package layout

The current repository is kept intentionally small. New code should follow this
layout without moving stable modules prematurely:

```text
app/
  api/                 # future route modules when API grows
  services/            # application orchestration
  domain/              # future extraction of models and pure rules
  adapters/            # future exchange and persistence adapters
  main.py              # FastAPI composition root
  models.py            # current domain models
  strategy.py          # current strategy facade
  exchange.py          # current public Bitunix adapter
  risk.py              # current paper risk policy
  storage.py           # current SQLite repository
  backtest.py          # offline historical simulation
  portfolio.py         # offline shared-equity simulation
tests/
  test_services/       # service orchestration contracts
  ...                  # current module-level tests
docs/
  ARCHITECTURE.md
```

The future folders are organizational targets, not claims that those packages
already exist. Extract modules only when tests protect their public contracts.

## Immediate architecture roadmap

1. Keep PR #12's SQLite health/detail fix as a prerequisite; do not bypass it.
2. Move scan orchestration out of FastAPI into `app.services.ScanService`.
3. Add service-level tests with fake market-data and storage adapters.
4. Add structured logging and request/scan correlation IDs.
5. Add schema migrations and repository protocol before expanding persistence.
6. Add authentication, rate limiting, observability, and deployment hardening
   before exposing the API publicly.
7. Keep order execution out of scope until independent strategy validation,
   paper-trading evidence, account-level risk controls, and explicit approval.
