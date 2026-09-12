"""Logging and trade/equity record keeping.

Replaces the previous ad-hoc ``open("trading-bot-log.txt", "a")`` calls. There
is now exactly one writer for the run log, and it emits to *both* stdout (so it
shows up in the GitHub Actions console) and a file (so it can be uploaded as an
artifact). The workflow must NOT redirect stdout to the same file, or the two
writers will clobber each other.
"""

from __future__ import annotations

import csv
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
RUN_LOG = LOG_DIR / "trading-bot-log.txt"
TRADE_LOG = LOG_DIR / "trade_log.csv"
EQUITY_LOG = LOG_DIR / "equity_log.csv"
SIGNAL_LOG = LOG_DIR / "signal_log.csv"

TRADE_HEADER = [
    "timestamp", "side", "symbol", "qty", "notional",
    "price", "order_id", "status", "reason",
]
EQUITY_HEADER = [
    "timestamp", "equity", "last_equity", "pnl",
    "peak_equity", "drawdown_pct", "exposure_pct",
]
SIGNAL_HEADER = [
    "timestamp", "symbol", "signal", "price",
    "fast_ma", "slow_ma", "rsi", "reason",
]

_LOGGER_NAME = "bot"


def utcnow() -> datetime:
    """Timezone-aware UTC now (``datetime.utcnow`` is deprecated)."""
    return datetime.now(timezone.utc)


def _timestamp() -> str:
    return utcnow().isoformat(timespec="seconds")


def setup_logging(level: str | int = "INFO") -> logging.Logger:
    """Configure and return the package logger. Safe to call repeatedly."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    if getattr(logger, "_configured", False):
        return logger

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    file_handler = logging.FileHandler(RUN_LOG, mode="a", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logger._configured = True  # type: ignore[attr-defined]
    return logger


def get_logger(name: str = _LOGGER_NAME) -> logging.Logger:
    if name == _LOGGER_NAME:
        return logging.getLogger(_LOGGER_NAME)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")


def _append_row(path: Path, header: list, row: list) -> None:
    """Append a row, writing the header first if the file is new/empty."""
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(header)
        writer.writerow(row)


def log_trade(side, symbol, qty, order_id=None, notional=None, price=None,
              status=None, reason=""):
    """Record an executed (or simulated) trade."""
    _append_row(TRADE_LOG, TRADE_HEADER, [
        _timestamp(), side, symbol, qty, notional, price,
        order_id, status, reason,
    ])
    get_logger().info(
        "TRADE %s %s qty=%s notional=%s price=%s id=%s status=%s %s",
        side, symbol, qty, notional, price, order_id, status, reason,
    )


def log_signal(symbol, signal, price=None, fast_ma=None, slow_ma=None,
               rsi=None, reason=""):
    """Record a strategy decision, including 'hold' decisions."""
    _append_row(SIGNAL_LOG, SIGNAL_HEADER, [
        _timestamp(), symbol, signal, price, fast_ma, slow_ma, rsi, reason,
    ])


def log_equity(equity, last_equity, peak_equity=None, drawdown_pct=None,
               exposure_pct=None):
    """Record an account equity snapshot."""
    pnl = equity - last_equity
    _append_row(EQUITY_LOG, EQUITY_HEADER, [
        _timestamp(), equity, last_equity, pnl,
        peak_equity, drawdown_pct, exposure_pct,
    ])
    get_logger().info(
        "EQUITY equity=%.2f last=%.2f pnl=%.2f peak=%s dd=%s exposure=%s",
        equity, last_equity, pnl, peak_equity, drawdown_pct, exposure_pct,
    )
