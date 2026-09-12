"""Risk management: exposure limits, position sizing, stops, and a kill switch.

The original ``can_open_position`` had several defects that are addressed here:

* It divided by ``equity`` with no zero guard.
* It used signed ``market_value``, so a short position *reduced* measured
  exposure.
* It ignored the size of the order being proposed, so it could approve a trade
  that immediately breached the limit.
* There was no drawdown kill switch, stop-loss, or take-profit anywhere, which
  meant an unattended bot could bleed indefinitely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .logger import get_logger
from .symbols import find_position

log = get_logger("risk")


@dataclass
class AccountState:
    equity: float
    last_equity: float
    cash: float
    buying_power: float
    positions: List
    trading_blocked: bool = False

    @property
    def gross_exposure(self) -> float:
        """Absolute market value across all positions."""
        return sum(abs(float(p.market_value)) for p in self.positions)

    @property
    def exposure_pct(self) -> float:
        if self.equity <= 0:
            return 1.0
        return self.gross_exposure / self.equity


def read_account(broker) -> AccountState:
    """Snapshot the account through the broker interface."""
    account = broker.get_account()
    positions = list(broker.get_positions())
    return AccountState(
        equity=float(account.equity),
        last_equity=float(account.last_equity or account.equity),
        cash=float(account.cash),
        buying_power=float(account.buying_power),
        positions=positions,
        trading_blocked=bool(account.trading_blocked),
    )


def drawdown_pct(equity: float, peak_equity: float) -> float:
    """Fractional drawdown from the recorded peak (0.0 - 1.0)."""
    if peak_equity <= 0:
        return 0.0
    return max(0.0, (peak_equity - equity) / peak_equity)


def check_kill_switch(state: AccountState, peak_equity: float,
                      max_drawdown_pct: float):
    """Return ``(halted, reason)``.

    When the account has drawn down more than ``max_drawdown_pct`` from its
    all-time peak equity, no NEW positions may be opened. Exits are always
    still allowed so the bot can flatten itself.
    """
    if state.trading_blocked:
        return True, "account has trading_blocked=True"

    if state.equity <= 0:
        return True, f"non-positive equity ({state.equity})"

    dd = drawdown_pct(state.equity, peak_equity)
    if dd >= max_drawdown_pct:
        return True, (
            f"drawdown {dd:.2%} >= limit {max_drawdown_pct:.2%} "
            f"(equity {state.equity:.2f} vs peak {peak_equity:.2f})"
        )
    return False, f"drawdown {dd:.2%} within limit {max_drawdown_pct:.2%}"


def can_open_position(state: AccountState, symbol: str, order_notional: float,
                      max_exposure_pct: float = 0.50,
                      max_position_pct: float = 0.25):
    """Return ``(allowed, reason)`` for a proposed BUY of ``order_notional``.

    Accounts for the proposed order, not just current exposure.
    """
    if state.equity <= 0:
        return False, "equity is zero or negative"

    if order_notional <= 0:
        return False, "computed order notional is zero"

    if order_notional > state.buying_power:
        return False, (
            f"order notional {order_notional:.2f} exceeds buying power "
            f"{state.buying_power:.2f}"
        )

    projected = (state.gross_exposure + order_notional) / state.equity
    if projected > max_exposure_pct:
        return False, (
            f"projected exposure {projected:.2%} would exceed limit "
            f"{max_exposure_pct:.2%}"
        )

    existing = find_position(state.positions, symbol)
    existing_value = abs(float(existing.market_value)) if existing else 0.0
    projected_position = (existing_value + order_notional) / state.equity
    if projected_position > max_position_pct:
        return False, (
            f"projected {symbol} position {projected_position:.2%} would "
            f"exceed per-symbol limit {max_position_pct:.2%}"
        )

    return True, (
        f"projected exposure {projected:.2%} within {max_exposure_pct:.2%}"
    )


def position_size(state: AccountState, price: float, per_trade_pct: float,
                  min_notional: float = 1.0):
    """Return ``(qty, notional)`` for a new entry, or ``(0, 0)`` if too small."""
    if price <= 0 or state.equity <= 0:
        return 0.0, 0.0

    notional = state.equity * per_trade_pct
    notional = min(notional, state.buying_power)

    if notional < min_notional:
        return 0.0, 0.0

    qty = notional / price
    # Alpaca accepts fractional crypto quantities; 8dp mirrors satoshi
    # precision and avoids scientific-notation serialization issues.
    qty = round(qty, 8)
    if qty <= 0:
        return 0.0, 0.0
    return qty, qty * price


def check_exit_rules(position, stop_loss_pct: float, take_profit_pct: float):
    """Return ``(should_exit, reason)`` based on unrealized P&L on a position."""
    try:
        entry = float(position.avg_entry_price)
        current = float(getattr(position, "current_price", 0) or 0)
    except (TypeError, ValueError):
        return False, "could not parse position prices"

    if entry <= 0 or current <= 0:
        return False, "missing entry/current price"

    change = (current - entry) / entry
    side = str(getattr(position, "side", "long")).lower()
    if side == "short":
        change = -change

    if change <= -stop_loss_pct:
        return True, f"stop-loss hit: {change:.2%} <= -{stop_loss_pct:.2%}"
    if change >= take_profit_pct:
        return True, f"take-profit hit: {change:.2%} >= {take_profit_pct:.2%}"
    return False, f"P&L {change:+.2%} within stop/target"
