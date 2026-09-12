"""Entry point: execute one full trading cycle, then exit.

Designed for scheduled GitHub Actions runs. Exits non-zero on unrecoverable
errors so that a permanently broken bot does not show a green checkmark
forever.

Run with:  python -m bot.run_once_and_exit
"""

from __future__ import annotations

import sys
import traceback

from . import __version__
from .brokers import DataError, get_broker
from .execution import close_position, submit_market_order
from .config import Config, ConfigError, load_config
from .logger import get_logger, log_equity, log_signal, setup_logging
from .risk import (
    AccountState,
    can_open_position,
    check_exit_rules,
    check_kill_switch,
    drawdown_pct,
    position_size,
    read_account,
)
from .state import load_state, save_state, update_peak_equity
from .strategy import BUY, HOLD, SELL, get_signal
from .symbols import find_position

log = get_logger("run")

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_RUNTIME_ERROR = 1


def process_symbol(broker, config: Config, state: AccountState, symbol: str,
                   halted: bool) -> None:
    """Evaluate and act on a single symbol."""
    try:
        bars = broker.get_bars(symbol, config.timeframe, config.bar_limit)
    except DataError as exc:
        log.error("Skipping %s: %s", symbol, exc)
        log_signal(symbol, "error", reason=str(exc))
        return

    signal = get_signal(
        bars,
        fast_window=config.fast_window,
        slow_window=config.slow_window,
        neutral_band_pct=config.neutral_band_pct,
        rsi_period=config.rsi_period,
        rsi_overbought=config.rsi_overbought,
        rsi_oversold=config.rsi_oversold,
    )
    log_signal(symbol, signal.action, price=signal.price,
               fast_ma=signal.fast_ma, slow_ma=signal.slow_ma,
               rsi=signal.rsi, reason=signal.reason)
    log.info("%s -> %s | price=%.2f %s",
             symbol, signal.action.upper(), signal.price, signal.reason)

    position = find_position(state.positions, symbol)

    # 1. Protective exits always take priority and are never blocked by the
    #    kill switch -- the bot must always be able to flatten itself.
    if position is not None:
        should_exit, exit_reason = check_exit_rules(
            position, config.stop_loss_pct, config.take_profit_pct
        )
        if should_exit:
            log.warning("Protective exit on %s: %s", symbol, exit_reason)
            close_position(broker, position, price=signal.price,
                           time_in_force=config.time_in_force,
                           dry_run=config.dry_run, reason=exit_reason)
            return
        log.info("%s position held: %s", symbol, exit_reason)

    # 2. Strategy exit.
    if signal.action == SELL:
        if position is None:
            log.info("Sell signal for %s but no open position; nothing to do.",
                     symbol)
            return
        close_position(broker, position, price=signal.price,
                       time_in_force=config.time_in_force,
                       dry_run=config.dry_run,
                       reason=f"strategy sell: {signal.reason}")
        return

    # 3. Entry.
    if signal.action == BUY:
        if position is not None:
            log.info(
                "Buy signal for %s but a position is already open "
                "(qty=%s); not adding.", symbol, position.qty,
            )
            return
        if halted:
            log.warning("Buy signal for %s suppressed: kill switch active.",
                        symbol)
            return

        qty, notional = position_size(
            state, signal.price, config.per_trade_pct, config.min_notional
        )
        if qty <= 0:
            log.info("Buy signal for %s but computed size is too small "
                     "(notional < %.2f).", symbol, config.min_notional)
            return

        allowed, risk_reason = can_open_position(
            state, symbol, notional,
            max_exposure_pct=config.max_exposure_pct,
            max_position_pct=config.max_position_pct,
        )
        if not allowed:
            log.warning("Entry on %s blocked by risk: %s", symbol, risk_reason)
            return

        log.info("Entering %s: qty=%s notional=%.2f (%s)",
                 symbol, qty, notional, risk_reason)
        submit_market_order(
            broker, symbol, qty, "buy",
            price=signal.price,
            time_in_force=config.time_in_force,
            dry_run=config.dry_run,
            reason=f"strategy buy: {signal.reason}",
        )
        return

    log.info("%s: holding. %s", symbol, signal.reason)


def run_bot_once() -> int:
    setup_logging()
    log.info("=" * 70)
    log.info("Autonomous trading bot v%s starting", __version__)

    try:
        config = load_config()
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        return EXIT_CONFIG_ERROR

    log.info(
        "Broker: %s | Mode: %s | symbols=%s | timeframe=%s | dry_run=%s",
        config.broker, "PAPER" if config.paper else "LIVE",
        ",".join(config.symbols), config.timeframe, config.dry_run,
    )

    persisted = load_state()

    try:
        broker = get_broker(config)
        account = read_account(broker)
    except Exception as exc:  # noqa: BLE001
        log.error("Could not reach broker: %s", exc)
        log.debug(traceback.format_exc())
        return EXIT_RUNTIME_ERROR

    peak = update_peak_equity(persisted, account.equity)
    halted, halt_reason = check_kill_switch(
        account, peak, config.max_drawdown_pct
    )
    persisted["halted"] = halted
    persisted["halt_reason"] = halt_reason if halted else ""

    if halted:
        log.error("KILL SWITCH ACTIVE: %s", halt_reason)
        log.error("New entries are disabled; exits remain enabled.")
    else:
        log.info("Risk check OK: %s", halt_reason)

    log.info(
        "Account: equity=%.2f cash=%.2f buying_power=%.2f positions=%d "
        "exposure=%.2f%%",
        account.equity, account.cash, account.buying_power,
        len(account.positions), account.exposure_pct * 100,
    )

    exit_code = EXIT_OK
    for symbol in config.symbols:
        try:
            process_symbol(broker, config, account, symbol, halted)
        except Exception as exc:  # noqa: BLE001
            # One bad symbol must not abort the others, but it should still
            # be reflected in the job's exit status.
            log.error("Unhandled error processing %s: %s", symbol, exc)
            log.debug(traceback.format_exc())
            exit_code = EXIT_RUNTIME_ERROR

    try:
        refreshed = read_account(broker)
        log_equity(
            refreshed.equity,
            refreshed.last_equity,
            peak_equity=peak,
            drawdown_pct=round(drawdown_pct(refreshed.equity, peak), 6),
            exposure_pct=round(refreshed.exposure_pct, 6),
        )
        update_peak_equity(persisted, refreshed.equity)
    except Exception as exc:  # noqa: BLE001
        log.error("Failed to record equity snapshot: %s", exc)
        exit_code = EXIT_RUNTIME_ERROR

    persisted["runs"] = int(persisted.get("runs") or 0) + 1
    save_state(persisted)

    log.info("Run complete (exit=%d)", exit_code)
    return exit_code


def main() -> int:
    try:
        return run_bot_once()
    except KeyboardInterrupt:
        log.warning("Interrupted.")
        return EXIT_RUNTIME_ERROR
    except Exception as exc:  # noqa: BLE001
        setup_logging()
        log.critical("Fatal unhandled error: %s", exc)
        log.critical(traceback.format_exc())
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main())
