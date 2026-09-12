import math

import pytest

from bot.strategy import (
    BUY, HOLD, SELL, Signal, extract_closes, get_signal, rsi, sma,
)


class FakeBar:
    def __init__(self, close, symbol="BTC/USD"):
        self.close = close
        self.symbol = symbol


def test_extract_closes_from_entities():
    bars = [FakeBar(1.0), FakeBar(2.0)]
    assert extract_closes(bars) == [1.0, 2.0]


def test_extract_closes_from_dicts_and_raw_keys():
    assert extract_closes([{"close": 5}, {"c": 6}]) == [5.0, 6.0]


def test_extract_closes_from_floats():
    assert extract_closes([1, 2.5]) == [1.0, 2.5]


def test_sma_basic():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1, 2], 5) is None


def test_rsi_all_gains_is_100():
    assert rsi(list(range(1, 40)), 14) == 100.0


def test_rsi_all_losses_is_zero():
    assert rsi(list(range(40, 1, -1)), 14) == 0.0


def test_rsi_insufficient_history():
    assert rsi([1, 2, 3], 14) is None


def test_insufficient_history_returns_hold():
    sig = get_signal([FakeBar(100)] * 10, slow_window=48)
    assert sig.action == HOLD
    assert "insufficient history" in sig.reason


def test_flat_market_is_hold_not_signal():
    """Regression: the old strategy emitted buy/sell on every single run."""
    bars = [FakeBar(100.0)] * 100
    sig = get_signal(bars, fast_window=12, slow_window=48)
    assert sig.action == HOLD


def test_tiny_noise_stays_inside_neutral_band():
    """Prices wobbling by a hair must not trigger trades."""
    closes = [100 + (0.001 if i % 2 else -0.001) for i in range(100)]
    sig = get_signal([FakeBar(c) for c in closes],
                     fast_window=12, slow_window=48, neutral_band_pct=0.15)
    assert sig.action == HOLD
    assert "neutral band" in sig.reason


def test_strong_uptrend_gives_buy():
    closes = [100 + i * 2 for i in range(120)]
    sig = get_signal([FakeBar(c) for c in closes],
                     fast_window=12, slow_window=48, rsi_overbought=200)
    assert sig.action == BUY
    assert sig.fast_ma > sig.slow_ma


def test_strong_downtrend_gives_sell():
    closes = [500 - i * 2 for i in range(120)]
    sig = get_signal([FakeBar(c) for c in closes],
                     fast_window=12, slow_window=48, rsi_oversold=-1)
    assert sig.action == SELL
    assert sig.fast_ma < sig.slow_ma


def test_rsi_filter_blocks_overbought_buy():
    closes = [100 + i * 2 for i in range(120)]
    sig = get_signal([FakeBar(c) for c in closes],
                     fast_window=12, slow_window=48, rsi_overbought=50)
    assert sig.action == HOLD
    assert "overbought" in sig.reason


def test_rsi_filter_blocks_oversold_sell():
    closes = [500 - i * 2 for i in range(120)]
    sig = get_signal([FakeBar(c) for c in closes],
                     fast_window=12, slow_window=48, rsi_oversold=50)
    assert sig.action == HOLD
    assert "oversold" in sig.reason


def test_signal_is_never_none():
    """The old code could return None; callers now always get a Signal."""
    for bars in ([], [FakeBar(1)], [FakeBar(i) for i in range(100)]):
        assert isinstance(get_signal(bars), Signal)
