"""Alpaca REST client construction and resilient market-data access."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit

from .config import Config, ConfigError, load_config
from .logger import get_logger
from .symbols import to_data_symbol

log = get_logger("client")

_TIMEFRAME_ALIASES: Dict[str, TimeFrame] = {
    "1min": TimeFrame(1, TimeFrameUnit.Minute),
    "5min": TimeFrame(5, TimeFrameUnit.Minute),
    "15min": TimeFrame(15, TimeFrameUnit.Minute),
    "30min": TimeFrame(30, TimeFrameUnit.Minute),
    "1hour": TimeFrame(1, TimeFrameUnit.Hour),
    "2hour": TimeFrame(2, TimeFrameUnit.Hour),
    "4hour": TimeFrame(4, TimeFrameUnit.Hour),
    "1day": TimeFrame(1, TimeFrameUnit.Day),
}


class DataError(RuntimeError):
    """Raised when market data cannot be retrieved."""


def parse_timeframe(value: str) -> TimeFrame:
    """Convert a string such as ``"1Hour"`` into a :class:`TimeFrame`.

    The original code passed the raw string ``"1Hour"`` straight into the SDK,
    which expects a ``TimeFrame`` object.
    """
    key = (value or "").strip().lower().replace(" ", "")
    if key in _TIMEFRAME_ALIASES:
        return _TIMEFRAME_ALIASES[key]
    raise ConfigError(
        f"Unsupported TIMEFRAME {value!r}. "
        f"Supported values: {', '.join(sorted(_TIMEFRAME_ALIASES))}"
    )


def get_client(config: Optional[Config] = None):
    """Build an authenticated Alpaca REST client.

    Unlike the previous implementation this fails fast with a clear message
    when credentials are absent, rather than passing ``None`` to the SDK.
    """
    config = config or load_config()
    log.info(
        "Connecting to Alpaca at %s (paper=%s)", config.base_url, config.paper
    )
    return tradeapi.REST(
        key_id=config.api_key,
        secret_key=config.secret_key,
        base_url=config.base_url,
        api_version="v2",
    )


def _is_permanent_error(exc: Exception) -> bool:
    """True for client errors that will never succeed on retry.

    Retrying a 401 (bad credentials) or 400 (bad symbol format) just wastes
    runner minutes and delays a clear failure message.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    if status is None:
        return False
    return status in {400, 401, 403, 404, 422}


def with_retries(func: Callable, *, attempts: int = 3, base_delay: float = 1.5,
                 description: str = "API call"):
    """Run ``func`` with exponential backoff on *transient* failures.

    GitHub Actions runners see transient DNS/TLS/5xx failures often enough that
    a single unlucky request should not take down the whole run. Permanent
    client errors are surfaced immediately.
    """
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - deliberately broad
            last_error = exc
            if _is_permanent_error(exc):
                raise DataError(f"{description} failed: {exc}") from exc
            if attempt == attempts:
                break
            delay = base_delay ** attempt
            log.warning(
                "%s failed (attempt %d/%d): %s - retrying in %.1fs",
                description, attempt, attempts, exc, delay,
            )
            time.sleep(delay)
    raise DataError(f"{description} failed after {attempts} attempts: {last_error}")


_TIMEFRAME_MINUTES: Dict[str, int] = {
    "1min": 1, "5min": 5, "15min": 15, "30min": 30,
    "1hour": 60, "2hour": 120, "4hour": 240, "1day": 1440,
}


def timeframe_minutes(value: str) -> int:
    key = (value or "").strip().lower().replace(" ", "")
    if key not in _TIMEFRAME_MINUTES:
        raise ConfigError(f"Unsupported TIMEFRAME {value!r}")
    return _TIMEFRAME_MINUTES[key]


def lookback_start(timeframe: str, limit: int, buffer: float = 2.0) -> str:
    """Compute an RFC-3339 ``start`` far enough back to yield ``limit`` bars.

    This is essential: the crypto bars endpoint returns only the single
    most-recent bar when ``start`` is omitted, regardless of ``limit``. Without
    this the strategy would permanently report "insufficient history" and never
    trade. The buffer absorbs any gaps in the series.
    """
    minutes = timeframe_minutes(timeframe) * max(limit, 1) * buffer
    start = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_crypto_bars(api, symbol: str, timeframe: str, limit: int) -> List:
    """Fetch crypto bars for a single symbol.

    Why this exists
    ---------------
    The old code called ``api.get_bars(...)``, which targets the **stock**
    data endpoint (``/v2/stocks``) and therefore never returned crypto data.
    Crypto lives at ``/v1beta3/crypto`` and is reached via
    ``get_crypto_bars``. The compact ``BTCUSD`` form also returns HTTP 400 on
    that endpoint; the slash form ``BTC/USD`` is required.

    We deliberately request one symbol at a time: the SDK applies ``limit`` to
    the *total* number of bars across all requested symbols, so a multi-symbol
    request would silently starve the strategy's warm-up window.
    """
    data_symbol = to_data_symbol(symbol)
    tf = parse_timeframe(timeframe)
    start = lookback_start(timeframe, limit)

    # IMPORTANT: we deliberately do NOT pass `limit` to the SDK.
    #
    # The SDK paginates forward from `start` and stops as soon as it has
    # collected `limit` bars, which yields the OLDEST bars in the window
    # rather than the newest. With a 2x lookback buffer that returned data
    # roughly 33 days stale (verified against the live API), and the bot
    # would have traded on month-old prices.
    #
    # Instead we fetch the whole window and keep the most recent `limit`
    # bars ourselves.
    def _fetch():
        return api.get_crypto_bars(data_symbol, tf, start=start)

    bars = with_retries(_fetch, description=f"get_crypto_bars({data_symbol})")
    bars = list(bars)

    if not bars:
        raise DataError(
            f"No bars returned for {data_symbol} since {start}. Check the "
            f"symbol format (crypto requires the slash form, e.g. 'BTC/USD')."
        )

    # Defensive: ensure we only keep bars for the requested symbol.
    filtered = [
        b for b in bars
        if to_data_symbol(getattr(b, "symbol", data_symbol)) == data_symbol
    ]
    result = (filtered or bars)[-limit:]
    log.info("Fetched %d bars for %s (%s), most recent of window since %s",
             len(result), data_symbol, timeframe, start)
    return result


def get_latest_price(api, symbol: str) -> float:
    """Best-effort latest trade price, falling back to the latest bar close.

    Note: the SDK only exposes the *plural* ``get_latest_crypto_trades``,
    which takes a list and returns a dict keyed by symbol. There is no
    singular ``get_latest_crypto_trade`` for crypto.
    """
    data_symbol = to_data_symbol(symbol)
    try:
        trades = with_retries(
            lambda: api.get_latest_crypto_trades([data_symbol]),
            attempts=2,
            description=f"get_latest_crypto_trades({data_symbol})",
        )
        trade = trades.get(data_symbol) if hasattr(trades, "get") else None
        price = float(getattr(trade, "price", 0) or 0) if trade else 0.0
        if price > 0:
            return price
    except Exception as exc:  # noqa: BLE001
        log.warning("Latest trade unavailable for %s: %s", data_symbol, exc)

    bars = get_crypto_bars(api, data_symbol, "1Min", 1)
    return float(bars[-1].close)
