"""End-to-end cycle tests against a mock Alpaca API.

These exercise the full orchestration path without touching the network.
"""

import json
import math

import pytest

import bot.logger as logger_mod
import bot.state as state_mod
from bot.brokers.base import Account, Bar, DataError, Order, Position
from bot.execution import submit_market_order
from bot.config import Config
from bot.run_once_and_exit import process_symbol
from bot.risk import AccountState


def FakePosition(symbol, qty, market_value, avg_entry_price, current_price,
                 side="long"):
    return Position(symbol=symbol, qty=qty, side=side,
                    market_value=market_value,
                    avg_entry_price=avg_entry_price,
                    current_price=current_price)


def FakeBar(close, symbol="BTC/USD"):
    return Bar(symbol=symbol, timestamp=None, open=close, high=close,
               low=close, close=close, volume=1.0)


class FakeBroker:
    """In-memory Broker implementation for cycle tests."""

    name = "fake"

    def __init__(self, closes, positions=None, equity=10000.0):
        self._closes = closes
        self.positions = positions or []
        self.orders = []
        self.equity = equity

    def get_bars(self, symbol, timeframe, limit):
        return [FakeBar(c, symbol) for c in self._closes]

    def get_account(self):
        return Account(equity=self.equity, last_equity=self.equity,
                       cash=self.equity, buying_power=self.equity)

    def get_positions(self):
        return self.positions

    def submit_market_order(self, symbol, qty, side, time_in_force="gtc"):
        self.orders.append({"symbol": symbol, "qty": qty, "side": side,
                            "time_in_force": time_in_force})
        return Order(id="order-1", symbol=symbol, qty=float(qty), side=side,
                     status="accepted")


FakeAPI = FakeBroker  # tests below use the broker interface


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


def test_tiny_qty_is_logged_without_scientific_notation(isolate_logs):
    """Floats like 1e-05 serialize badly; the trade log must stay readable."""
    api = FakeAPI(UPTREND)
    submit_market_order(api, "BTC/USD", 0.0000123, "buy", price=50000.0)
    content = (isolate_logs / "trade_log.csv").read_text()
    assert "0.0000123" in content
    assert "e-" not in content


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


def test_data_error_does_not_crash_the_run():
    class BrokenAPI(FakeAPI):
        def get_bars(self, *a, **k):
            raise DataError("boom")

    api = BrokenAPI(UPTREND)
    process_symbol(api, make_config(), make_state(), "BTC/USD", halted=False)
    assert api.orders == []
