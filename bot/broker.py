"""Order execution with safety checks and dry-run support."""

from __future__ import annotations

from typing import Optional

from .logger import get_logger, log_trade
from .symbols import to_data_symbol

log = get_logger("broker")


class DryRunOrder:
    """Stand-in for an SDK order object when ``DRY_RUN=true``."""

    def __init__(self, symbol: str, qty: float, side: str):
        self.id = "DRY-RUN"
        self.symbol = symbol
        self.qty = qty
        self.side = side
        self.status = "dry_run"


def submit_market_order(api, symbol: str, qty: float, side: str, *,
                        price: Optional[float] = None,
                        time_in_force: str = "gtc",
                        dry_run: bool = False,
                        reason: str = ""):
    """Submit a market order, or simulate it when ``dry_run`` is set.

    Quantities are always sent as plain decimal strings: floats can serialize
    in scientific notation (e.g. ``1e-05``), which the API rejects.
    """
    data_symbol = to_data_symbol(symbol)
    qty = float(qty)

    if qty <= 0:
        log.warning("Refusing to submit %s order for non-positive qty %s", side, qty)
        return None

    qty_str = f"{qty:.8f}".rstrip("0").rstrip(".")
    notional = qty * price if price else None

    if dry_run:
        log.info(
            "[DRY RUN] would %s %s %s (~%s USD) - %s",
            side, qty_str, data_symbol, f"{notional:.2f}" if notional else "?",
            reason,
        )
        order = DryRunOrder(data_symbol, qty, side)
        log_trade(side, data_symbol, qty_str, order_id=order.id,
                  notional=notional, price=price, status="dry_run",
                  reason=reason)
        return order

    try:
        order = api.submit_order(
            symbol=data_symbol,
            qty=qty_str,
            side=side,
            type="market",
            time_in_force=time_in_force,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Order REJECTED: %s %s %s - %s", side, qty_str, data_symbol, exc)
        log_trade(side, data_symbol, qty_str, order_id=None, notional=notional,
                  price=price, status="rejected", reason=f"{reason} | error={exc}")
        raise

    log_trade(
        side, data_symbol, qty_str,
        order_id=getattr(order, "id", None),
        notional=notional,
        price=price,
        status=getattr(order, "status", "submitted"),
        reason=reason,
    )
    return order


def close_position(api, position, *, price: Optional[float] = None,
                   time_in_force: str = "gtc", dry_run: bool = False,
                   reason: str = ""):
    """Fully exit an open position."""
    symbol = getattr(position, "symbol", "")
    qty = abs(float(position.qty))
    side = "sell" if str(getattr(position, "side", "long")).lower() == "long" else "buy"
    return submit_market_order(
        api, symbol, qty, side,
        price=price, time_in_force=time_in_force,
        dry_run=dry_run, reason=reason,
    )
