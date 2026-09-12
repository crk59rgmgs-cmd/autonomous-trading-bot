# Changelog

## 2.0.0 — Repository audit and overhaul

A full audit found the bot was **non-functional**: it could not fetch market
data at all, so it had never placed a trade. Every finding below was verified
against the live Alpaca API before being fixed.

### Critical fixes

- **Crypto data endpoint.** `get_bars()` targets the *stock* endpoint
  (`/v2/stocks`), which returns HTTP 401 for crypto. Replaced with
  `get_crypto_bars()` against `/v1beta3/crypto`.
- **Symbol format.** The crypto endpoint rejects the compact `BTCUSD` form
  with **HTTP 400**; `BTC/USD` returns 200. Added `bot/symbols.py` to
  normalize between the data form (`BTC/USD`) and the form the trading API
  returns for positions (`BTCUSD`). This also fixes the sell branch, which
  compared `position.symbol == "BTCUSD"` and could silently never match.
- **Missing `start` parameter.** Verified against the live API: the bars
  endpoint returns **only one bar** when `start` is omitted, regardless of
  `limit`. The strategy would have permanently reported "insufficient
  history" and never traded. A lookback window is now always computed.
- **`TimeFrame` type.** The SDK expects a `TimeFrame` object; the old code
  passed the raw string `"1Hour"`.
- **Per-symbol fetching.** The SDK applies `limit` to the *total* bars across
  all requested symbols, which would starve the strategy's warm-up window.
- **Package structure.** Added `bot/__init__.py` and converted to relative
  imports. Entry point is now `python -m bot.run_once_and_exit`.

### Risk management (previously absent)

- Drawdown **kill switch** with peak equity persisted across ephemeral runs.
- Per-position **stop-loss and take-profit**, evaluated first and never
  blocked by the kill switch, so the bot can always flatten itself.
- `can_open_position` rewritten: guards zero equity, uses `abs(market_value)`
  so shorts no longer mask exposure, and accounts for the *pending* order.
- Equity-based **position sizing** replacing the hardcoded `QTY = 0.0001`.
- Per-symbol exposure cap in addition to the gross cap.
- **No position stacking** — an open position is never topped up.
- Live-trading interlock requiring two explicit environment variables.

### Strategy

- Replaced the price-vs-SMA20 rule, which emitted a buy or sell on *every*
  run, with a fast/slow crossover plus a **neutral band** and an RSI filter.
  Over 90 days this cut activity from ~8,600 signals to 27 round-trips.
- Defaults moved to 4-hour bars with a 20/60 crossover after a parameter
  sweep on real data; the 4-hour timeframe outperformed 1-hour across every
  parameter combination tested.
- Added `bot/backtest.py` for offline evaluation with fee modelling.

### Logging and observability

- Replaced ad-hoc file writes with the `logging` module, emitting to stdout
  *and* a file. Removed the workflow's `>` redirect, which created a second,
  truncating writer that could destroy error messages.
- Added `signal_log.csv` recording every decision, including `hold`, with the
  reasoning — so an idle bot can be distinguished from a broken one.
- Trade and equity CSVs gained headers and richer fields.
- Logs and state are committed back to the repo instead of being discarded.
- The job now **exits non-zero** on failure instead of always reporting green.

### Reliability

- Retry with exponential backoff on transient errors; permanent client errors
  (400/401/403/404/422) fail immediately instead of burning three attempts.
- Added a `concurrency` group so overlapping runs cannot double-submit orders.
- Order quantities are serialized as plain decimal strings — floats can
  render as `1e-05`, which the API rejects.
- Atomic state writes to avoid truncated files.
- Schedule moved from `*/15` to hourly at `:30`; the 15-minute cadence added
  no signal on 4-hour bars and is unreliable under GitHub's scheduler load.
- Replaced deprecated `datetime.utcnow()` with timezone-aware equivalents.

### Dependencies

- Pinned `alpaca-trade-api==3.2.0`.
- Pinned `pandas<3.0`: the SDK is incompatible with pandas 3.x, which pip
  otherwise resolves and installs without any apparent error.

### Testing and docs

- Added **96 tests** covering strategy, risk, symbols, config, data access,
  state, backtesting, and full trading cycles against a mock API.
- Added a CI workflow running tests on Python 3.11 and 3.12.
- Rewrote the README; added this changelog.
- Removed the duplicate root-level `Autonomous-Trading-Bot` workflow copy.
