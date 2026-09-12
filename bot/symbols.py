"""Symbol normalization helpers.

Alpaca is inconsistent about crypto symbol formatting:

* Market data (``/v1beta3/crypto``) requires the slash form: ``BTC/USD``.
* The trading API accepts the slash form for new orders, but historically
  returns positions using the compact form: ``BTCUSD``.

Comparing these two forms naively (``position.symbol == "BTC/USD"``) silently
fails and was the cause of the sell branch never matching an open position.
Everything in this codebase should therefore compare symbols via
:func:`same_symbol` rather than ``==``.
"""

from __future__ import annotations

# Quote currencies we may encounter, longest first so that "USDT" is matched
# before "USD" when splitting a compact symbol such as "BTCUSDT".
_QUOTE_CURRENCIES = ("USDT", "USDC", "USD", "BTC", "ETH")


def to_data_symbol(symbol: str) -> str:
    """Return the slash form used by the crypto market-data API (``BTC/USD``)."""
    symbol = (symbol or "").strip().upper().replace("-", "/")
    if "/" in symbol:
        base, _, quote = symbol.partition("/")
        return f"{base.strip()}/{quote.strip()}"

    for quote in _QUOTE_CURRENCIES:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return f"{symbol[: -len(quote)]}/{quote}"

    # Unknown layout: hand it back unchanged rather than guessing wrongly.
    return symbol


def to_compact_symbol(symbol: str) -> str:
    """Return the compact form used by some trading endpoints (``BTCUSD``)."""
    return (symbol or "").strip().upper().replace("-", "").replace("/", "")


def same_symbol(a: str, b: str) -> bool:
    """Compare two symbols irrespective of slash/compact formatting."""
    return to_compact_symbol(a) == to_compact_symbol(b)


def find_position(positions, symbol):
    """Return the position matching ``symbol``, or ``None``.

    Format-insensitive, unlike a plain equality check.
    """
    for position in positions or []:
        if same_symbol(getattr(position, "symbol", ""), symbol):
            return position
    return None
