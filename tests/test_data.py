"""Tests for market-data access helpers.

These lock in two findings that were verified against the live Alpaca API:

1. The crypto bars endpoint returns only ONE bar when ``start`` is omitted,
   regardless of ``limit``. A lookback window is therefore mandatory.
2. The compact symbol form (``BTCUSD``) returns HTTP 400; the slash form is
   required.
"""

from datetime import datetime, timedelta, timezone

import pytest

from bot.alpaca_client import (
    DataError, get_crypto_bars, lookback_start, parse_timeframe,
    timeframe_minutes,
)
from bot.config import ConfigError


class FakeBar:
    def __init__(self, close, symbol="BTC/USD"):
        self.close = close
        self.symbol = symbol


class RecordingAPI:
    def __init__(self, bars=None):
        self.calls = []
        self._bars = bars if bars is not None else [FakeBar(100.0)] * 10

    def get_crypto_bars(self, symbol, timeframe, start=None, end=None,
                        limit=None, **kwargs):
        self.calls.append(
            {"symbol": symbol, "timeframe": timeframe,
             "start": start, "limit": limit}
        )
        return self._bars


def test_parse_timeframe_accepts_common_forms():
    assert parse_timeframe("1Hour").value == "1Hour"
    assert parse_timeframe("4hour").value == "4Hour"
    assert parse_timeframe("15Min").value == "15Min"
    assert parse_timeframe("1Day").value == "1Day"


def test_parse_timeframe_rejects_garbage():
    with pytest.raises(ConfigError, match="Unsupported TIMEFRAME"):
        parse_timeframe("1Fortnight")


def test_timeframe_minutes():
    assert timeframe_minutes("4Hour") == 240
    assert timeframe_minutes("1Day") == 1440


def test_lookback_start_is_in_the_past_and_scales():
    now = datetime.now(timezone.utc)
    short = datetime.strptime(
        lookback_start("1Hour", 10), "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)
    long = datetime.strptime(
        lookback_start("1Hour", 200), "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)
    assert short < now
    assert long < short  # more bars requested => reach further back


def test_lookback_covers_requested_bars_with_buffer():
    """200 4H bars need >= 800h of history; we request 2x for safety."""
    start = datetime.strptime(
        lookback_start("4Hour", 200), "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)
    hours = (datetime.now(timezone.utc) - start).total_seconds() / 3600
    assert hours >= 200 * 4


def test_start_is_always_sent():
    """Regression: without `start` the API returns a single bar."""
    api = RecordingAPI()
    get_crypto_bars(api, "BTC/USD", "4Hour", 200)
    assert api.calls[0]["start"] is not None


def test_limit_is_not_passed_to_sdk():
    """Regression: staleness bug.

    The SDK paginates forward from `start` and stops at `limit`, returning the
    OLDEST bars in the window. Passing `limit` produced data ~33 days stale.
    """
    api = RecordingAPI()
    get_crypto_bars(api, "BTC/USD", "4Hour", 200)
    assert api.calls[0]["limit"] is None


def test_returns_most_recent_bars_not_oldest():
    """We must keep the tail of the window, not the head."""
    bars = [FakeBar(float(i)) for i in range(500)]
    api = RecordingAPI(bars=bars)
    result = get_crypto_bars(api, "BTC/USD", "4Hour", 200)
    assert len(result) == 200
    assert result[-1].close == 499.0   # newest bar retained
    assert result[0].close == 300.0    # oldest 300 dropped


def test_short_history_is_returned_whole():
    api = RecordingAPI(bars=[FakeBar(float(i)) for i in range(5)])
    result = get_crypto_bars(api, "BTC/USD", "4Hour", 200)
    assert len(result) == 5


def test_symbol_is_normalized_to_slash_form():
    """Regression: 'BTCUSD' returns HTTP 400 from the crypto endpoint."""
    api = RecordingAPI()
    get_crypto_bars(api, "BTCUSD", "4Hour", 200)
    assert api.calls[0]["symbol"] == "BTC/USD"


def test_empty_response_raises_actionable_error():
    api = RecordingAPI(bars=[])
    with pytest.raises(DataError, match="slash form"):
        get_crypto_bars(api, "BTC/USD", "4Hour", 200)


def test_foreign_symbols_are_filtered_out():
    """The crypto endpoint groups by symbol; never mix series."""
    api = RecordingAPI(bars=[FakeBar(1, "BTC/USD"), FakeBar(2, "ETH/USD")])
    bars = get_crypto_bars(api, "BTC/USD", "4Hour", 200)
    assert len(bars) == 1
    assert bars[0].symbol == "BTC/USD"
