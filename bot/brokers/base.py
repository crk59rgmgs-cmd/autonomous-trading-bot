"""Broker-agnostic interfaces and data models.

The strategy, risk, logging, and orchestration layers depend only on the
types in this module -- never on a vendor SDK. Adding a new venue means
writing one adapter that satisfies :class:`Broker`; nothing else changes.

This also keeps SDK quirks quarantined in the adapter. For example, Alpaca's
crypto bars endpoint returns a single bar when ``start`` is omitted, and
paginates forward so that passing ``limit`` yields the *oldest* bars in the
window. That is the adapter's problem to solve, not the strategy's.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class Bar:
    """A single OHLCV candle."""
    symbol: str
    timestamp: Optional[datetime]
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    # Convenience alias: some strategy code and the Alpaca raw payload use
    # single-letter keys.
    @property
    def c(self) -> float:
        return self.close


@dataclass
class Account:
    equity: float
    last_equity: float
    cash: float
    buying_power: float
    trading_blocked: bool = False


@dataclass
class Position:
    symbol: str
    qty: float
    side: str            # "long" or "short"
    market_value: float
    avg_entry_price: float
    current_price: float


@dataclass
class Order:
    id: str
    symbol: str
    qty: float
    side: str
    status: str


class BrokerError(RuntimeError):
    """Raised when a broker operation fails."""


class DataError(BrokerError):
    """Raised when market data cannot be retrieved."""


class Broker(ABC):
    """The contract every venue adapter must satisfy."""

    #: Human-readable venue name, used in logs.
    name: str = "unknown"

    @abstractmethod
    def get_bars(self, symbol: str, timeframe: str, limit: int) -> List[Bar]:
        """Return up to ``limit`` of the MOST RECENT bars for ``symbol``.

        Implementations must guarantee freshness: the last element is the
        latest available bar.
        """

    @abstractmethod
    def get_account(self) -> Account:
        """Return current account balances."""

    @abstractmethod
    def get_positions(self) -> List[Position]:
        """Return all open positions."""

    @abstractmethod
    def submit_market_order(self, symbol: str, qty: float, side: str,
                            time_in_force: str = "gtc") -> Order:
        """Submit a market order and return the resulting order."""

    def describe(self) -> str:
        return self.name
