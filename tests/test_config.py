import os

import pytest

from bot.config import ConfigError, load_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("ALPACA_", "SYMBOLS", "FAST_", "SLOW_", "BAR_",
                           "MAX_", "PER_TRADE", "STOP_", "TAKE_", "DRY_RUN",
                           "TIME_IN_FORCE", "TIMEFRAME", "MIN_NOTIONAL")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")


def test_defaults_are_paper_and_valid():
    cfg = load_config()
    assert cfg.paper is True
    assert "paper-api" in cfg.base_url
    assert cfg.symbols == ["BTC/USD", "ETH/USD"]


def test_missing_credentials_raise(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="Missing Alpaca credentials"):
        load_config()


def test_blank_credentials_raise(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "   ")
    with pytest.raises(ConfigError, match="Missing Alpaca credentials"):
        load_config()


def test_symbols_are_normalized(monkeypatch):
    monkeypatch.setenv("SYMBOLS", "btcusd, eth-usd")
    assert load_config().symbols == ["BTC/USD", "ETH/USD"]


def test_fast_must_be_less_than_slow(monkeypatch):
    monkeypatch.setenv("FAST_WINDOW", "50")
    monkeypatch.setenv("SLOW_WINDOW", "20")
    with pytest.raises(ConfigError, match="must be smaller"):
        load_config()


def test_bar_limit_must_exceed_slow_window(monkeypatch):
    monkeypatch.setenv("BAR_LIMIT", "10")
    with pytest.raises(ConfigError, match="must exceed slow_window"):
        load_config()


def test_bad_numeric_value_is_clear(monkeypatch):
    monkeypatch.setenv("PER_TRADE_PCT", "not-a-number")
    with pytest.raises(ConfigError, match="must be a number"):
        load_config()


def test_pct_out_of_range(monkeypatch):
    monkeypatch.setenv("MAX_EXPOSURE_PCT", "1.5")
    with pytest.raises(ConfigError, match="between 0 and 1"):
        load_config()


def test_invalid_time_in_force(monkeypatch):
    monkeypatch.setenv("TIME_IN_FORCE", "day")
    with pytest.raises(ConfigError, match="gtc"):
        load_config()


def test_live_endpoint_blocked_without_override(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER", "false")
    with pytest.raises(ConfigError, match="Refusing to trade against the LIVE"):
        load_config()


def test_live_endpoint_allowed_with_explicit_override(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER", "false")
    monkeypatch.setenv("ALPACA_ALLOW_LIVE", "true")
    cfg = load_config()
    assert cfg.paper is False
    assert cfg.base_url.endswith("api.alpaca.markets")


def test_dry_run_flag(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    assert load_config().dry_run is True
