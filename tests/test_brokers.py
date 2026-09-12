"""Tests for the broker abstraction and registry.

The point of this layer is that swapping venues is a config change, not a
rewrite. These tests assert the seam actually holds.
"""

import pytest

from bot.brokers import SUPPORTED_BROKERS, get_broker
from bot.brokers.base import Account, Bar, Broker, BrokerError, Order, Position
from bot.config import ConfigError, load_config


def test_alpaca_is_registered():
    assert "alpaca" in SUPPORTED_BROKERS


def test_unknown_broker_rejected_by_config(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    monkeypatch.setenv("BROKER", "definitely-not-a-broker")
    with pytest.raises(ConfigError, match="Unknown BROKER"):
        load_config()


def test_default_broker_is_alpaca(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    monkeypatch.delenv("BROKER", raising=False)
    assert load_config().broker == "alpaca"


def test_get_broker_rejects_unknown_name():
    class Cfg:
        broker = "nope"
        api_key = "k"
        secret_key = "s"
        paper = True

    with pytest.raises(BrokerError, match="Unknown broker"):
        get_broker(Cfg())


# --- interface conformance ----------------------------------------------

class MinimalBroker(Broker):
    """A complete adapter, to prove the interface is implementable."""

    name = "minimal"

    def get_bars(self, symbol, timeframe, limit):
        return [Bar(symbol, None, 1, 1, 1, 1, 1)]

    def get_account(self):
        return Account(1.0, 1.0, 1.0, 1.0)

    def get_positions(self):
        return []

    def submit_market_order(self, symbol, qty, side, time_in_force="gtc"):
        return Order("id", symbol, qty, side, "accepted")


def test_minimal_adapter_satisfies_the_interface():
    broker = MinimalBroker()
    assert isinstance(broker, Broker)
    assert broker.describe() == "minimal"
    assert broker.get_bars("BTC/USD", "4Hour", 1)[0].close == 1
    assert broker.get_account().equity == 1.0
    assert broker.submit_market_order("BTC/USD", 1, "buy").status == "accepted"


def test_incomplete_adapter_cannot_be_instantiated():
    class Broken(Broker):
        name = "broken"
        # get_account / get_positions / submit_market_order missing

        def get_bars(self, symbol, timeframe, limit):
            return []

    with pytest.raises(TypeError):
        Broken()


def test_core_modules_do_not_import_a_vendor_sdk():
    """Guard against a vendor SDK leaking back into the core modules.

    Checks imports rather than raw text, so explanatory comments mentioning a
    venue are fine -- only real coupling fails.
    """
    import ast
    import pathlib

    for name in ("risk", "strategy", "execution", "backtest"):
        path = pathlib.Path("bot") / f"{name}.py"
        tree = ast.parse(path.read_text())
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        leaked = [m for m in imported if "alpaca" in m.lower()]
        assert not leaked, f"bot/{name}.py imports a vendor SDK: {leaked}"


def test_adapter_is_the_only_sdk_consumer():
    """The SDK must be confined to bot/brokers/alpaca.py."""
    import pathlib

    offenders = []
    for path in pathlib.Path("bot").rglob("*.py"):
        if path.name == "alpaca.py":
            continue
        text = path.read_text()
        if "import alpaca" in text or "from alpaca" in text:
            offenders.append(str(path))
    assert not offenders, f"SDK imported outside the adapter: {offenders}"
