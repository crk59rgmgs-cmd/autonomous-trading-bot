"""Broker registry.

Selecting a venue is a config change, not a code change. To add one, write an
adapter satisfying :class:`~bot.brokers.base.Broker` and register it below.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict

from .base import (
    Account, Bar, Broker, BrokerError, DataError, Order, Position,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Config

__all__ = [
    "Account", "Bar", "Broker", "BrokerError", "DataError", "Order",
    "Position", "get_broker", "SUPPORTED_BROKERS",
]


def _build_alpaca(config: "Config") -> Broker:
    # Imported lazily so the SDK is only required when actually used.
    from .alpaca import AlpacaBroker

    return AlpacaBroker(
        api_key=config.api_key,
        secret_key=config.secret_key,
        paper=config.paper,
    )


_REGISTRY: Dict[str, Callable[["Config"], Broker]] = {
    "alpaca": _build_alpaca,
}

SUPPORTED_BROKERS = tuple(sorted(_REGISTRY))


def get_broker(config: "Config") -> Broker:
    """Instantiate the broker named by ``config.broker``."""
    name = (config.broker or "alpaca").strip().lower()
    if name not in _REGISTRY:
        raise BrokerError(
            f"Unknown broker {name!r}. Supported: {', '.join(SUPPORTED_BROKERS)}"
        )
    return _REGISTRY[name](config)
