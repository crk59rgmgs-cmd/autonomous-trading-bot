"""Alpaca adapter built on the modern ``alpaca-py`` SDK.

Replaces the deprecated ``alpaca-trade-api``, which pinned the project to
``pandas<3``. All Alpaca-specific quirks are contained here:

* Crypto market data lives at ``/v1beta3/crypto``, not ``/v2/stocks``.
* Crypto symbols must use the slash form (``BTC/USD``); ``BTCUSD`` is a 400.
* Omitting ``start`` returns exactly ONE bar regardless of ``limit``.
* The API paginates FORWARD from ``start`` and stops once ``limit`` bars are
  collected, which returns the OLDEST bars in the window. Verified against
  live data: this produced prices ~33 days stale. We therefore never send
  ``limit`` and slice the most recent bars ourselves.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from ..logger import get_logger
from ..symbols import to_data_symbol
from .base import Account, Bar, Broker, BrokerError, DataError, Order, Position

log = get_logger("broker.alpaca")

_TIMEFRAMES: Dict[str, TimeFrame] = {
    "1min": TimeFrame(1, TimeFrameUnit.Minute),
    "5min": TimeFrame(5, TimeFrameUnit.Minute),
    "15min": TimeFrame(15, TimeFrameUnit.Minute),
    "30min": TimeFrame(30, TimeFrameUnit.Minute),
    "1hour": TimeFrame(1, TimeFrameUnit.Hour),
    "2hour": TimeFrame(2, TimeFrameUnit.Hour),
    "4hour": TimeFrame(4, TimeFrameUnit.Hour),
    "1day": TimeFrame(1, TimeFrameUnit.Day),
}

_TIMEFRAME_MINUTES: Dict[str, int] = {
    "1min": 1, "5min": 5, "15min": 15, "30min": 30,
    "1hour": 60, "2hour": 120, "4hour": 240, "1day": 1440,
}

_SIDES = {"buy": OrderSide.BUY, "sell": OrderSide.SELL}
_TIF = {"gtc": TimeInForce.GTC, "ioc": TimeInForce.IOC}

# Client errors that will never succeed on retry.
_PERMANENT_STATUS = {400, 401, 403, 404, 422}


def _normalize(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "")


def parse_timeframe(value: str) -> TimeFrame:
    key = _normalize(value)
    if key not in _TIMEFRAMES:
        raise BrokerError(
            f"Unsupported timeframe {value!r}. "
            f"Supported: {', '.join(sorted(_TIMEFRAMES))}"
        )
    return _TIMEFRAMES[key]


def timeframe_minutes(value: str) -> int:
    key = _normalize(value)
    if key not in _TIMEFRAME_MINUTES:
        raise BrokerError(f"Unsupported timeframe {value!r}")
    return _TIMEFRAME_MINUTES[key]


def lookback_start(timeframe: str, limit: int, buffer: float = 2.0) -> datetime:
    """Compute a ``start`` far enough back to cover ``limit`` bars.

    Mandatory: without ``start`` the endpoint returns a single bar.
    """
    minutes = timeframe_minutes(timeframe) * max(limit, 1) * buffer
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def _is_permanent(exc: Exception) -> bool:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    return status in _PERMANENT_STATUS if status is not None else False


def with_retries(func: Callable, *, attempts: int = 3, base_delay: float = 1.5,
                 description: str = "API call"):
    """Retry transient failures with exponential backoff.

    Permanent client errors (bad credentials, bad symbol) fail immediately
    rather than burning three attempts and delaying a clear message.
    """
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if _is_permanent(exc):
                raise DataError(f"{description} failed: {exc}") from exc
            if attempt == attempts:
                break
            delay = base_delay ** attempt
            log.warning("%s failed (attempt %d/%d): %s - retrying in %.1fs",
                        description, attempt, attempts, exc, delay)
            time.sleep(delay)
    raise DataError(f"{description} failed after {attempts} attempts: {last_error}")


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class AlpacaBroker(Broker):
    name = "alpaca"

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        # `paper` is an explicit SDK flag rather than a URL string, which
        # makes accidental live trading much harder.
        self._trading = TradingClient(
            api_key=api_key, secret_key=secret_key, paper=paper
        )
        # Crypto market data requires no credentials, but we pass them so
        # rate limits apply to our account rather than the shared pool.
        self._data = CryptoHistoricalDataClient(
            api_key=api_key or None, secret_key=secret_key or None
        )
        self.paper = paper
        log.info("Alpaca broker ready (paper=%s)", paper)

    # --- market data ---------------------------------------------------

    def get_bars(self, symbol: str, timeframe: str, limit: int) -> List[Bar]:
        data_symbol = to_data_symbol(symbol)
        start = lookback_start(timeframe, limit)

        request = CryptoBarsRequest(
            symbol_or_symbols=[data_symbol],
            timeframe=parse_timeframe(timeframe),
            start=start,
            # NOTE: `limit` is deliberately omitted. See module docstring --
            # sending it returns the oldest bars in the window.
        )

        response = with_retries(
            lambda: self._data.get_crypto_bars(request),
            description=f"get_crypto_bars({data_symbol})",
        )

        raw = (response.data or {}).get(data_symbol) or []
        if not raw:
            raise DataError(
                f"No bars returned for {data_symbol} since {start:%Y-%m-%d}. "
                f"Crypto requires the slash form, e.g. 'BTC/USD'."
            )

        bars = [
            Bar(
                symbol=data_symbol,
                timestamp=getattr(b, "timestamp", None),
                open=_f(b.open), high=_f(b.high), low=_f(b.low),
                close=_f(b.close), volume=_f(getattr(b, "volume", 0)),
            )
            for b in raw
        ]
        # Keep only the most recent `limit` bars.
        bars = bars[-limit:]
        log.info("Fetched %d bars for %s (%s), newest %s",
                 len(bars), data_symbol, timeframe,
                 bars[-1].timestamp if bars else "n/a")
        return bars

    # --- account -------------------------------------------------------

    def get_account(self) -> Account:
        acct = with_retries(self._trading.get_account,
                            description="get_account")
        equity = _f(acct.equity)
        return Account(
            equity=equity,
            last_equity=_f(getattr(acct, "last_equity", None), equity),
            cash=_f(getattr(acct, "cash", 0)),
            buying_power=_f(getattr(acct, "buying_power", 0)),
            trading_blocked=bool(getattr(acct, "trading_blocked", False)),
        )

    def get_positions(self) -> List[Position]:
        raw = with_retries(self._trading.get_all_positions,
                           description="get_all_positions")
        positions = []
        for p in raw or []:
            side = getattr(p, "side", "long")
            positions.append(Position(
                symbol=str(p.symbol),
                qty=_f(p.qty),
                side=str(getattr(side, "value", side)).lower(),
                market_value=_f(getattr(p, "market_value", 0)),
                avg_entry_price=_f(getattr(p, "avg_entry_price", 0)),
                current_price=_f(getattr(p, "current_price", 0)),
            ))
        return positions

    # --- orders --------------------------------------------------------

    def submit_market_order(self, symbol: str, qty: float, side: str,
                            time_in_force: str = "gtc") -> Order:
        data_symbol = to_data_symbol(symbol)
        side_key = (side or "").strip().lower()
        tif_key = (time_in_force or "gtc").strip().lower()

        if side_key not in _SIDES:
            raise BrokerError(f"Invalid order side {side!r}")
        if tif_key not in _TIF:
            raise BrokerError(
                f"Alpaca crypto supports only 'gtc' or 'ioc', got {time_in_force!r}"
            )

        # Send qty as a plain decimal string: floats can serialize as
        # scientific notation (1e-05), which the API rejects.
        qty_str = f"{float(qty):.8f}".rstrip("0").rstrip(".")

        request = MarketOrderRequest(
            symbol=data_symbol,
            qty=qty_str,
            side=_SIDES[side_key],
            time_in_force=_TIF[tif_key],
        )
        order = self._trading.submit_order(request)
        status = getattr(order, "status", "submitted")
        return Order(
            id=str(getattr(order, "id", "")),
            symbol=data_symbol,
            qty=float(qty),
            side=side_key,
            status=str(getattr(status, "value", status)),
        )
