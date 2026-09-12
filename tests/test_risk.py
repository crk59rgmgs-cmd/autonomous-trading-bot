import pytest

from bot.risk import (
    AccountState, can_open_position, check_exit_rules, check_kill_switch,
    drawdown_pct, position_size,
)


class FakePosition:
    def __init__(self, symbol, market_value, qty=1.0, avg_entry_price=100.0,
                 current_price=100.0, side="long"):
        self.symbol = symbol
        self.market_value = market_value
        self.qty = qty
        self.avg_entry_price = avg_entry_price
        self.current_price = current_price
        self.side = side


def state(equity=10000.0, positions=None, buying_power=None, **kw):
    return AccountState(
        equity=equity,
        last_equity=kw.get("last_equity", equity),
        cash=kw.get("cash", equity),
        buying_power=equity if buying_power is None else buying_power,
        positions=positions or [],
        trading_blocked=kw.get("trading_blocked", False),
    )


# --- exposure ------------------------------------------------------------

def test_zero_equity_does_not_crash():
    """Regression: the old code divided by equity with no guard."""
    s = state(equity=0.0)
    allowed, reason = can_open_position(s, "BTC/USD", 100.0)
    assert allowed is False
    assert "equity" in reason


def test_short_position_counts_as_exposure():
    """Regression: signed market_value let shorts mask real exposure."""
    s = state(equity=1000.0, positions=[FakePosition("BTCUSD", -900.0)])
    assert s.gross_exposure == 900.0
    assert s.exposure_pct == pytest.approx(0.9)


def test_proposed_order_is_counted():
    """Regression: the old check ignored the size of the pending order."""
    s = state(equity=1000.0, positions=[FakePosition("ETHUSD", 450.0)])
    allowed, _ = can_open_position(s, "BTC/USD", 400.0, max_exposure_pct=0.5)
    assert allowed is False


def test_allows_reasonable_order():
    s = state(equity=10000.0)
    allowed, _ = can_open_position(s, "BTC/USD", 200.0, max_exposure_pct=0.5)
    assert allowed is True


def test_per_symbol_cap_enforced():
    s = state(equity=1000.0, positions=[FakePosition("BTCUSD", 240.0)])
    allowed, reason = can_open_position(
        s, "BTC/USD", 100.0, max_exposure_pct=0.9, max_position_pct=0.25
    )
    assert allowed is False
    assert "per-symbol" in reason


def test_symbol_format_mismatch_still_matches_position():
    """Position comes back as BTCUSD while we ask about BTC/USD."""
    s = state(equity=1000.0, positions=[FakePosition("BTCUSD", 240.0)])
    allowed, reason = can_open_position(
        s, "BTC/USD", 50.0, max_exposure_pct=0.9, max_position_pct=0.25
    )
    assert allowed is False


def test_order_exceeding_buying_power_rejected():
    s = state(equity=10000.0, buying_power=50.0)
    allowed, reason = can_open_position(s, "BTC/USD", 200.0)
    assert allowed is False
    assert "buying power" in reason


# --- kill switch ---------------------------------------------------------

def test_drawdown_pct():
    assert drawdown_pct(80, 100) == pytest.approx(0.2)
    assert drawdown_pct(120, 100) == 0.0
    assert drawdown_pct(100, 0) == 0.0


def test_kill_switch_triggers_on_drawdown():
    halted, reason = check_kill_switch(state(equity=800.0), 1000.0, 0.15)
    assert halted is True
    assert "drawdown" in reason


def test_kill_switch_inactive_within_limit():
    halted, _ = check_kill_switch(state(equity=950.0), 1000.0, 0.15)
    assert halted is False


def test_kill_switch_respects_trading_blocked():
    halted, reason = check_kill_switch(
        state(equity=1000.0, trading_blocked=True), 1000.0, 0.15
    )
    assert halted is True
    assert "trading_blocked" in reason


# --- sizing --------------------------------------------------------------

def test_position_size_basic():
    qty, notional = position_size(state(equity=10000.0), price=50000.0,
                                  per_trade_pct=0.02)
    assert notional == pytest.approx(200.0)
    assert qty == pytest.approx(0.004)


def test_position_size_rejects_dust():
    qty, notional = position_size(state(equity=10.0), price=50000.0,
                                  per_trade_pct=0.02, min_notional=1.0)
    assert (qty, notional) == (0.0, 0.0)


def test_position_size_zero_price_is_safe():
    assert position_size(state(), price=0.0, per_trade_pct=0.02) == (0.0, 0.0)


def test_position_size_capped_by_buying_power():
    qty, notional = position_size(
        state(equity=10000.0, buying_power=50.0), price=1000.0,
        per_trade_pct=0.02,
    )
    assert notional == pytest.approx(50.0)


# --- exits ---------------------------------------------------------------

def test_stop_loss_triggers():
    p = FakePosition("BTCUSD", 100, avg_entry_price=100, current_price=94)
    should_exit, reason = check_exit_rules(p, 0.05, 0.10)
    assert should_exit is True
    assert "stop-loss" in reason


def test_take_profit_triggers():
    p = FakePosition("BTCUSD", 100, avg_entry_price=100, current_price=111)
    should_exit, reason = check_exit_rules(p, 0.05, 0.10)
    assert should_exit is True
    assert "take-profit" in reason


def test_no_exit_inside_band():
    p = FakePosition("BTCUSD", 100, avg_entry_price=100, current_price=102)
    should_exit, _ = check_exit_rules(p, 0.05, 0.10)
    assert should_exit is False


def test_short_position_pnl_is_inverted():
    """A short that gains 12% as price falls should hit take-profit."""
    p = FakePosition("BTCUSD", -100, avg_entry_price=100, current_price=88,
                     side="short")
    should_exit, reason = check_exit_rules(p, 0.05, 0.10)
    assert should_exit is True
    assert "take-profit" in reason


def test_short_position_stop_loss_on_price_rise():
    """A short loses when price rises, so this must be a stop-loss."""
    p = FakePosition("BTCUSD", -100, avg_entry_price=100, current_price=106,
                     side="short")
    should_exit, reason = check_exit_rules(p, 0.05, 0.10)
    assert should_exit is True
    assert "stop-loss" in reason


def test_bad_prices_do_not_crash():
    p = FakePosition("BTCUSD", 100, avg_entry_price="oops", current_price=100)
    should_exit, _ = check_exit_rules(p, 0.05, 0.10)
    assert should_exit is False
