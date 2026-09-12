"""End-to-end cycle tests against a mock Alpaca API.

These exercise the full orchestration path without touching the network.
"""

import json
import math

import pytest

import bot.logger as logger_mod
import bot.state as state_mod
from bot.broker import submit_market_order
from bot.config import Config
from bot.run_once_and_exit import process_symbol
from bot.risk import AccountState


class FakeOrder:
    def __init__(self, symbol, qty, side):
        self.id = "order-1"
        self.symbol = symbol
        self.qty = qty
        self.side = side
        self.status = "accepted"


class FakePosition:
    def __init__(self, symbol, qty, market_value, avg_entry_price,
                 current_price, side="long"):
        self.symbol = symbol
        self.qty = qty
        self.market_value = market_value
        self.avg_entry_price = avg_entry_price
        self.current_price = current_price
        self.side = side


class FakeBar:
    def __init__(self, close, symbol="BTC/USD"):
        self.close = close
        self.symbol = symbol


class FakeAPI:
    def __init__(self, closes, positions=None):
        self._closes = closes
        self.positions = positions or []
        self.orders = []

    def get_crypto_bars(self, symbol, timeframe, start=None, end=None,
                        limit=None, **kwargs):
        return [FakeBar(c, symbol) for c in self._closes]

    def list_positions(self):
        return self.positions

    def submit_order(self, **kwargs):
        self.orders.append(kwargs)
        return FakeOrder(kwargs["symbol"], kwargs["qty"], kwargs["side"])


@pytest.fixture(autouse=True)
def isolate_logs(tmp_path, monkeypatch):
    """Redirect all log/state output into a temp dir."""
    monkeypatch.setattr(logger_mod, "LOG_DIR", tmp_path)
    monkeypatch.setattr(logger_mod, "TRADE_LOG", tmp_path / "trade_log.csv")
    monkeypatch.setattr(logger_mod, "EQUITY_LOG", tmp_path / "equity_log.csv")
    monkeypatch.setattr(logger_mod, "SIGNAL_LOG", tmp_path / "signal_log.csv")
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.json")
    return tmp_path


def make_config(**kw):
    defaults = dict(
        api_key="k", secret_key="s",
        base_url="https://paper-api.alpaca.markets", paper=True,
        symbols=["BTC/USD"], timeframe="1Hour", bar_limit=200,
        fast_window=12, slow_window=48, neutral_band_pct=0.15,
        rsi_period=14, rsi_overbought=200.0, rsi_oversold=-1.0,
        max_exposure_pct=0.5, per_trade_pct=0.02, max_position_pct=0.25,
        stop_loss_pct=0.05, take_profit_pct=0.10, max_drawdown_pct=0.15,
        min_notional=1.0, dry_run=False, time_in_force="gtc",
    )
    defaults.update(kw)
    return Config(**defaults)


def make_state(equity=10000.0, positions=None):
    return AccountState(
        equity=equity, last_equity=equity, cash=equity,
        buying_power=equity, positions=positions or [],
    )


UPTREND = [100 + i * 2 for i in range(120)]
DOWNTREND = [500 - i * 2 for i in range(120)]
FLAT = [100.0] * 120


def test_uptrend_opens_position():
    api = FakeAPI(UPTREND)
    process_symbol(api, make_config(), make_state(), "BTC/USD", halted=False)
    assert len(api.orders) == 1
    assert api.orders[0]["side"] == "buy"
    assert api.orders[0]["symbol"] == "BTC/USD"


def test_flat_market_places_no_orders():
    """Regression: the old bot traded on literally every run."""
    api = FakeAPI(FLAT)
    process_symbol(api, make_config(), make_state(), "BTC/USD", halted=False)
    assert api.orders == []


def test_does_not_stack_positions():
    """Regression: old code re-bought every 15 minutes."""
    pos = FakePosition("BTCUSD", 0.01, 300.0, 300.0, 305.0)
    api = FakeAPI(UPTREND, positions=[pos])
    process_symbol(api, make_config(), make_state(positions=[pos]),
                   "BTC/USD", halted=False)
    assert api.orders == []


def test_kill_switch_blocks_entry():
    api = FakeAPI(UPTREND)
    process_symbol(api, make_config(), make_state(), "BTC/USD", halted=True)
    assert api.orders == []


def test_downtrend_sells_existing_position():
    pos = FakePosition("BTCUSD", 0.01, 300.0, 300.0, 299.0)
    api = FakeAPI(DOWNTREND, positions=[pos])
    process_symbol(api, make_config(), make_state(positions=[pos]),
                   "BTC/USD", halted=False)
    assert len(api.orders) == 1
    assert api.orders[0]["side"] == "sell"


def test_sell_signal_with_no_position_is_noop():
    api = FakeAPI(DOWNTREND)
    process_symbol(api, make_config(), make_state(), "BTC/USD", halted=False)
    assert api.orders == []


def test_stop_loss_exits_even_when_halted():
    """The bot must always be able to flatten itself."""
    pos = FakePosition("BTCUSD", 0.01, 300.0, avg_entry_price=100.0,
                       current_price=90.0)
    api = FakeAPI(UPTREND, positions=[pos])
    process_symbol(api, make_config(), make_state(positions=[pos]),
                   "BTC/USD", halted=True)
    assert len(api.orders) == 1
    assert api.orders[0]["side"] == "sell"


def test_take_profit_exits():
    pos = FakePosition("BTCUSD", 0.01, 300.0, avg_entry_price=100.0,
                       current_price=115.0)
    api = FakeAPI(UPTREND, positions=[pos])
    process_symbol(api, make_config(), make_state(positions=[pos]),
                   "BTC/USD", halted=False)
    assert len(api.orders) == 1
    assert api.orders[0]["side"] == "sell"


def test_dry_run_submits_nothing():
    api = FakeAPI(UPTREND)
    process_symbol(api, make_config(dry_run=True), make_state(),
                   "BTC/USD", halted=False)
    assert api.orders == []


def test_qty_is_never_scientific_notation():
    """Floats like 1e-05 serialize badly and get rejected by the API."""
    api = FakeAPI(UPTREND)
    submit_market_order(api, "BTC/USD", 0.0000123, "buy", price=50000.0)
    qty = api.orders[0]["qty"]
    assert isinstance(qty, str)
    assert "e" not in qty.lower()


def test_zero_qty_order_is_refused():
    api = FakeAPI(UPTREND)
    assert submit_market_order(api, "BTC/USD", 0, "buy") is None
    assert api.orders == []


def test_signals_are_logged_even_on_hold(isolate_logs):
    api = FakeAPI(FLAT)
    process_symbol(api, make_config(), make_state(), "BTC/USD", halted=False)
    content = (isolate_logs / "signal_log.csv").read_text()
    assert "hold" in content
    assert "timestamp,symbol,signal" in content


def test_trades_are_logged_with_header(isolate_logs):
    api = FakeAPI(UPTREND)
    process_symbol(api, make_config(), make_state(), "BTC/USD", halted=False)
    content = (isolate_logs / "trade_log.csv").read_text()
    assert content.startswith("timestamp,side,symbol,qty")
    assert "buy" in content


def test_data_error_does_not_crash_the_run(monkeypatch):
    # Avoid real backoff sleeps in tests.
    monkeypatch.setattr("bot.alpaca_client.time.sleep", lambda *_: None)

    class BrokenAPI(FakeAPI):
        def get_crypto_bars(self, *a, **k):
            raise RuntimeError("boom")

    api = BrokenAPI(UPTREND)
    process_symbol(api, make_config(), make_state(), "BTC/USD", halted=False)
    assert api.orders == []


def test_permanent_client_error_is_not_retried(monkeypatch):
    """A 401/400 must fail immediately rather than burning three attempts."""
    from bot.alpaca_client import DataError, with_retries

    calls = {"n": 0}

    class Resp:
        status_code = 401

    class Unauthorized(Exception):
        response = Resp()

    def boom():
        calls["n"] += 1
        raise Unauthorized("unauthorized")

    monkeypatch.setattr("bot.alpaca_client.time.sleep", lambda *_: None)
    with pytest.raises(DataError):
        with_retries(boom, description="test")
    assert calls["n"] == 1


def test_transient_error_is_retried(monkeypatch):
    from bot.alpaca_client import DataError, with_retries

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("temporary network glitch")
        return "ok"

    monkeypatch.setattr("bot.alpaca_client.time.sleep", lambda *_: None)
    assert with_retries(flaky, description="test") == "ok"
    assert calls["n"] == 3
