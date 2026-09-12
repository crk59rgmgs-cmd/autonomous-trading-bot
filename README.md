# Autonomous Trading Bot

An automated **paper** crypto trading bot for Alpaca (BTC/USD, ETH/USD) that
runs on a schedule in GitHub Actions.

> **This is paper-trading software provided for educational purposes. It is not
> financial advice. The bundled strategy is not proven profitable — see
> [Strategy performance](#strategy-performance) below. Do not point this at a
> live account without doing your own work.**

---

## How it works

Each scheduled run executes exactly one cycle and exits:

1. Load and validate configuration and credentials (fail fast if invalid).
2. Read account equity, buying power, and open positions.
3. Update the persisted peak-equity high-water mark and evaluate the
   **drawdown kill switch**.
4. For each symbol:
   - Fetch 4-hour bars from the crypto market-data API.
   - Evaluate the moving-average strategy.
   - Apply protective exits (stop-loss / take-profit) — *always* allowed.
   - Apply the strategy entry/exit, subject to risk limits.
5. Record an equity snapshot and persist state.
6. Commit logs back to the repository so history survives the runner.

## Layout

```
bot/
  __init__.py
  config.py              Environment-driven configuration + validation
  symbols.py             BTC/USD <-> BTCUSD normalization
  brokers/
    base.py              Broker interface + vendor-neutral data models
    alpaca.py            Alpaca adapter (the ONLY file importing the SDK)
    __init__.py          Registry: pick a venue via the BROKER env var
  strategy.py            MA crossover + neutral band + RSI filter
  risk.py                Exposure, sizing, stops, drawdown kill switch
  execution.py           Order submission, dry-run support
  state.py               Persistent peak equity / halt state
  logger.py              Logging + CSV trade/equity/signal records
  backtest.py            Offline strategy evaluation
  run_once_and_exit.py   Entry point
tests/                   108 unit and integration tests
logs/                    Committed run history
```

## Setup

Add these repository secrets (**Settings → Secrets and variables → Actions**):

| Secret | Description |
| --- | --- |
| `ALPACA_API_KEY` | Alpaca **paper** API key ID |
| `ALPACA_SECRET_KEY` | Alpaca **paper** API secret |

The workflow runs hourly at `:30` and can also be triggered manually via
**Actions → Autonomous Trading Bot → Run workflow**, where you can tick
**dry run** to simulate without sending orders.

## Configuration

Every parameter is an environment variable, so behaviour can be changed from
the workflow without touching code.

| Variable | Default | Description |
| --- | --- | --- |
| `BROKER` | `alpaca` | Trading venue (see [Adding a broker](#adding-a-broker)) |
| `SYMBOLS` | `BTC/USD,ETH/USD` | Comma-separated symbols |
| `TIMEFRAME` | `4Hour` | Bar size (`15Min`, `1Hour`, `4Hour`, `1Day`, ...) |
| `BAR_LIMIT` | `200` | Bars to fetch per symbol |
| `FAST_WINDOW` | `20` | Fast moving-average period |
| `SLOW_WINDOW` | `60` | Slow moving-average period |
| `NEUTRAL_BAND_PCT` | `0.15` | MA spread (%) required before acting |
| `RSI_PERIOD` | `14` | RSI lookback |
| `RSI_OVERBOUGHT` | `75` | Suppress buys above this RSI |
| `RSI_OVERSOLD` | `25` | Suppress sells below this RSI |
| `MAX_EXPOSURE_PCT` | `0.50` | Max gross exposure as a fraction of equity |
| `MAX_POSITION_PCT` | `0.25` | Max single-symbol exposure |
| `PER_TRADE_PCT` | `0.02` | Equity fraction committed per entry |
| `STOP_LOSS_PCT` | `0.05` | Per-position stop loss |
| `TAKE_PROFIT_PCT` | `0.10` | Per-position take profit |
| `MAX_DRAWDOWN_PCT` | `0.15` | Kill-switch drawdown threshold |
| `MIN_NOTIONAL` | `1.0` | Skip orders smaller than this (USD) |
| `DRY_RUN` | `false` | Log orders without sending them |
| `ALPACA_PAPER` | `true` | Paper vs live endpoint |
| `ALPACA_ALLOW_LIVE` | `false` | Required to permit live trading |

## Safety mechanisms

- **Paper by default.** Live trading requires *both* `ALPACA_PAPER=false` and
  `ALPACA_ALLOW_LIVE=true`; otherwise startup aborts.
- **Drawdown kill switch.** Once equity falls `MAX_DRAWDOWN_PCT` below its
  all-time peak, new entries stop. Exits stay enabled so the bot can always
  flatten itself.
- **Stop-loss / take-profit** on every open position, checked before anything
  else and never blocked by the kill switch.
- **Layered exposure caps**, accounting for the pending order — not just
  current holdings.
- **No position stacking.** An existing position is never topped up.
- **Concurrency group** prevents overlapping runs from double-submitting.
- **Dry-run mode** for safe end-to-end verification.
- **Non-zero exit codes** on failure, so a broken bot does not show green.

## Adding a broker

The strategy, risk, execution, and logging layers depend only on the interface
in `bot/brokers/base.py` -- never on a vendor SDK. A test enforces this, so
coupling cannot creep back in.

To add a venue:

1. Create `bot/brokers/<name>.py` with a class implementing `Broker`:
   `get_bars`, `get_account`, `get_positions`, `submit_market_order`.
2. Register it in `bot/brokers/__init__.py`.
3. Set `BROKER=<name>`.

Keep every venue quirk inside the adapter. Alpaca's, for reference: crypto
needs the slash symbol form, `start` is mandatory, and `limit` must not be
sent because the API paginates forward and would return the oldest bars.
Expect any new venue to have its own equivalents -- validate against live
prices before trusting it.

## Local use

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

pytest tests/ -v                       # run the test suite

export ALPACA_API_KEY=...  ALPACA_SECRET_KEY=...
DRY_RUN=true python -m bot.run_once_and_exit   # simulate a full cycle

python -m bot.backtest --symbol BTC/USD --timeframe 4Hour --limit 1000
```

## Why Alpaca

Alpaca provides a real paper-trading account that mirrors the live API, which
most crypto venues do not. For an unattended bot that matters more than API
ergonomics. Its notable downside is fees, which are higher than several
exchanges -- relevant given the strategy has no demonstrated edge.

The broker abstraction exists so this choice stays cheap to revisit.

## Strategy performance

Backtested on 90 days of real 1-hour Alpaca data (0.25% per-side fees):

| Symbol | Strategy | Buy & hold | Trades | Win rate | Max DD |
| --- | --- | --- | --- | --- | --- |
| BTC/USD | +2.77% | +16.49% | 27 | 29.6% | 12.9% |
| ETH/USD | −10.15% | +40.38% | 28 | 21.4% | 18.6% |

Moving to 4-hour bars with a 20/60 crossover improved the two-asset average to
roughly +15% over the same window, which is why those are the defaults. Be
aware this is a **single 90-day in-sample window**: it is evidence that the
plumbing works and that churn is under control, **not** evidence of a
profitable edge. Re-run `bot.backtest` over your own windows before changing
parameters.

## Logs

| File | Contents |
| --- | --- |
| `logs/trading-bot-log.txt` | Human-readable run log |
| `logs/trade_log.csv` | Every order: side, qty, notional, price, status |
| `logs/equity_log.csv` | Equity, P&L, peak, drawdown, exposure |
| `logs/signal_log.csv` | Every decision, including `hold`, with reasoning |
| `logs/state.json` | Peak equity and halt state across runs |

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Cycle completed |
| `1` | Runtime error (API unreachable, symbol failure) |
| `2` | Configuration or credential error |
