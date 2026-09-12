"""Order execution: safety checks, dry-run support, and trade logging.

Sits between the orchestrator and the broker adapter. Knows nothing about any
vendor SDK -- it talks only to :class:`~bot.brokers.base.Broker`.
"""

from __future__ import annotations

from typing import Optional

from .brokers.base import Broker, Order, Position
from .logger import get_logger, log_trade
from .symbols import to_data_symbol

log = get_logger("execution")


def _dry_run_order(symbol: str, qty: float, side: str) -> Order:
    return Order(id="DRY-RUN", symbol=symbol, qty=qty, side=side,
                 status="dry_run")


def submit_market_order(broker: Broker, symbol: str, qty: float, side: str, *,
                        price: Optional[float] = None,
                        time_in_force: str = "gtc",
                        dry_run: bool = False,
                        reason: str = "") -> Optional[Order]:
    """Place a market order, or simulate it when ``dry_run`` is set."""
    data_symbol = to_data_symbol(symbol)
    qty = float(qty)

    if qty <= 0:
        log.warning("Refusing to submit %s order for non-positive qty %s",
                    side, qty)
        return None

    qty_str = f"{qty:.8f}".rstrip("0").rstrip(".")
    notional = qty * price if price else None

    if dry_run:
        log.info("[DRY RUN] would %s %s %s (~%s USD) - %s",
                 side, qty_str, data_symbol,
                 f"{notional:.2f}" if notional else "?", reason)
        order = _dry_run_order(data_symbol, qty, side)
        log_trade(side, data_symbol, qty_str, order_id=order.id,
                  notional=notional, price=price, status="dry_run",
                  reason=reason)
        return order

    try:
        order = broker.submit_market_order(
            data_symbol, qty, side, time_in_force=time_in_force
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Order REJECTED: %s %s %s - %s",
                  side, qty_str, data_symbol, exc)
        log_trade(side, data_symbol, qty_str, order_id=None,
                  notional=notional, price=price, status="rejected",
                  reason=f"{reason} | error={exc}")
        raise

    log_trade(side, data_symbol, qty_str, order_id=order.id,
              notional=notional, price=price, status=order.status,
              reason=reason)
    return order


def close_position(broker: Broker, position: Position, *,
                   price: Optional[float] = None,
                   time_in_force: str = "gtc",
                   dry_run: bool = False,
                   reason: str = "") -> Optional[Order]:
    """Fully exit an open position."""
    qty = abs(float(position.qty))
    side = "sell" if str(position.side).lower() == "long" else "buy"
    return submit_market_order(
        broker, position.symbol, qty, side,
        price=price, time_in_force=time_in_force,
        dry_run=dry_run, reason=reason,
    )
