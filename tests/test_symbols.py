import pytest

from bot.symbols import (
    find_position, same_symbol, to_compact_symbol, to_data_symbol,
)


class FakePosition:
    def __init__(self, symbol):
        self.symbol = symbol


@pytest.mark.parametrize("raw,expected", [
    ("BTCUSD", "BTC/USD"),
    ("btcusd", "BTC/USD"),
    ("BTC/USD", "BTC/USD"),
    ("BTC-USD", "BTC/USD"),
    ("ETHUSD", "ETH/USD"),
    ("ETHUSDT", "ETH/USDT"),
    ("  btc/usd  ", "BTC/USD"),
])
def test_to_data_symbol(raw, expected):
    assert to_data_symbol(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("BTC/USD", "BTCUSD"),
    ("BTCUSD", "BTCUSD"),
    ("btc-usd", "BTCUSD"),
])
def test_to_compact_symbol(raw, expected):
    assert to_compact_symbol(raw) == expected


def test_same_symbol_across_formats():
    assert same_symbol("BTC/USD", "BTCUSD")
    assert same_symbol("eth-usd", "ETH/USD")
    assert not same_symbol("BTC/USD", "ETH/USD")


def test_find_position_matches_compact_form():
    """The core bug: positions come back as BTCUSD, we search for BTC/USD."""
    positions = [FakePosition("ETHUSD"), FakePosition("BTCUSD")]
    found = find_position(positions, "BTC/USD")
    assert found is not None and found.symbol == "BTCUSD"


def test_find_position_returns_none_when_absent():
    assert find_position([FakePosition("ETHUSD")], "BTC/USD") is None
    assert find_position([], "BTC/USD") is None
    assert find_position(None, "BTC/USD") is None
