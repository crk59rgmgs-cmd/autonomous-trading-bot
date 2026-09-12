"""Tests for the Alpaca broker adapter.

These lock in behaviour verified against the LIVE Alpaca API:

1. The crypto bars endpoint returns only ONE bar when ``start`` is omitted,
   regardless of ``limit``.
2. The endpoint paginates FORWARD from ``start`` and stops at ``limit``,
   returning the OLDEST bars in the window. Sending ``limit`` produced prices
   ~33 days stale. Reproduced on BOTH alpaca-trade-api and alpaca-py, so it
   is an API trait, not an SDK bug.
3. The compact symbol form (``BTCUSD``) returns HTTP 400; the slash form is
   required.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from bot.brokers.alpaca import (
    AlpacaBroker, lookback_start, parse_timeframe, timeframe_minutes,
    with_retries,
)
from bot.brokers.base import BrokerError, DataError


class RawBar:
    def __init__(self, close, ts=None):
        self.open = close
        self.high = close
        self.low = close
        self.close = close
        self.volume = 1.0
        self.timestamp = ts or datetime.now(timezone.utc)


class FakeDataClient:
    def __init__(self, bars, symbol="BTC/USD"):
        self._bars = bars
        self._symbol = symbol
        self.requests = []

    def get_crypto_bars(self, request):
        self.requests.append(request)
        return SimpleNamespace(data={self._symbol: self._bars})


def make_broker(bars, symbol="BTC/USD"):
    broker = AlpacaBroker.__new__(AlpacaBroker)  # bypass network setup
    broker._data = FakeDataClient(bars, symbol)
    broker._trading = None
    broker.paper = True
    return broker


# --- timeframes ----------------------------------------------------------

def test_parse_timeframe_forms():
    assert parse_timeframe("4Hour").amount == 4
    assert parse_timeframe("15min").amount == 15


def test_parse_timeframe_rejects_garbage():
    with pytest.raises(BrokerError, match="Unsupported timeframe"):
        parse_timeframe("1Fortnight")


def test_timeframe_minutes():
    assert timeframe_minutes("4Hour") == 240
    assert timeframe_minutes("1Day") == 1440


# --- lookback ------------------------------------------------------------

def test_lookback_is_in_the_past():
    assert lookback_start("4Hour", 200) < datetime.now(timezone.utc)


def test_lookback_covers_requested_bars():
    """200 4H bars need >= 800h of history."""
    start = lookback_start("4Hour", 200)
    hours = (datetime.now(timezone.utc) - start).total_seconds() / 3600
    assert hours >= 200 * 4


def test_lookback_scales_with_limit():
    assert lookback_start("1Hour", 500) < lookback_start("1Hour", 10)


# --- the two critical regressions ----------------------------------------

def test_start_is_always_sent():
    """Without `start` the API returns a single bar."""
    broker = make_broker([RawBar(1.0)] * 10)
    broker.get_bars("BTC/USD", "4Hour", 200)
    assert broker._data.requests[0].start is not None


def test_limit_is_never_sent_to_the_api():
    """Regression: sending `limit` returns the OLDEST bars (33 days stale)."""
    broker = make_broker([RawBar(1.0)] * 10)
    broker.get_bars("BTC/USD", "4Hour", 200)
    assert broker._data.requests[0].limit is None


def test_returns_newest_bars_not_oldest():
    broker = make_broker([RawBar(float(i)) for i in range(500)])
    bars = broker.get_bars("BTC/USD", "4Hour", 200)
    assert len(bars) == 200
    assert bars[-1].close == 499.0   # newest retained
    assert bars[0].close == 300.0    # oldest dropped


# --- symbols and errors --------------------------------------------------

def test_symbol_normalized_to_slash_form():
    """'BTCUSD' is HTTP 400 on the crypto endpoint."""
    broker = make_broker([RawBar(1.0)], symbol="BTC/USD")
    broker.get_bars("BTCUSD", "4Hour", 200)
    assert broker._data.requests[0].symbol_or_symbols == ["BTC/USD"]


def test_empty_response_raises_actionable_error():
    broker = make_broker([])
    with pytest.raises(DataError, match="slash form"):
        broker.get_bars("BTC/USD", "4Hour", 200)


def test_short_history_returned_whole():
    broker = make_broker([RawBar(float(i)) for i in range(5)])
    assert len(broker.get_bars("BTC/USD", "4Hour", 200)) == 5


def test_bars_expose_close_and_c_alias():
    broker = make_broker([RawBar(42.0)])
    bar = broker.get_bars("BTC/USD", "4Hour", 10)[0]
    assert bar.close == 42.0 and bar.c == 42.0


# --- retries -------------------------------------------------------------

def test_permanent_error_not_retried(monkeypatch):
    calls = {"n": 0}

    class Unauthorized(Exception):
        response = SimpleNamespace(status_code=401)

    def boom():
        calls["n"] += 1
        raise Unauthorized("unauthorized")

    monkeypatch.setattr("bot.brokers.alpaca.time.sleep", lambda *_: None)
    with pytest.raises(DataError):
        with_retries(boom, description="t")
    assert calls["n"] == 1


def test_transient_error_is_retried(monkeypatch):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("network glitch")
        return "ok"

    monkeypatch.setattr("bot.brokers.alpaca.time.sleep", lambda *_: None)
    assert with_retries(flaky, description="t") == "ok"
    assert calls["n"] == 3
