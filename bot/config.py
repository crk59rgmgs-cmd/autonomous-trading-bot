"""Central configuration, sourced from environment variables.

Every tunable lives here so that behaviour can be changed from the workflow
without editing code. All values are validated at import-time-of-use via
:func:`load_config`, which raises :class:`ConfigError` with an actionable
message instead of letting a bad value surface as a confusing API error later.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
LIVE_ENDPOINT = "https://api.alpaca.markets"


class ConfigError(RuntimeError):
    """Raised when configuration or credentials are missing/invalid."""


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    api_key: str
    secret_key: str
    base_url: str
    paper: bool
    broker: str = "alpaca"

    symbols: List[str] = field(default_factory=lambda: ["BTC/USD", "ETH/USD"])
    timeframe: str = "4Hour"
    bar_limit: int = 200

    # Strategy
    fast_window: int = 20
    slow_window: int = 60
    neutral_band_pct: float = 0.15
    rsi_period: int = 14
    rsi_overbought: float = 75.0
    rsi_oversold: float = 25.0

    # Risk
    max_exposure_pct: float = 0.50
    per_trade_pct: float = 0.02
    max_position_pct: float = 0.25
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    max_drawdown_pct: float = 0.15
    min_notional: float = 1.0

    # Execution
    dry_run: bool = False
    time_in_force: str = "gtc"

    def validate(self) -> None:
        if not self.api_key or not self.secret_key:
            raise ConfigError(
                "Missing Alpaca credentials. Set the ALPACA_API_KEY and "
                "ALPACA_SECRET_KEY environment variables (in GitHub Actions "
                "these come from repository secrets)."
            )
        if self.fast_window >= self.slow_window:
            raise ConfigError(
                f"fast_window ({self.fast_window}) must be smaller than "
                f"slow_window ({self.slow_window})."
            )
        if self.bar_limit <= self.slow_window:
            raise ConfigError(
                f"bar_limit ({self.bar_limit}) must exceed slow_window "
                f"({self.slow_window}) or the strategy can never warm up."
            )
        for name in ("max_exposure_pct", "per_trade_pct", "max_position_pct",
                     "stop_loss_pct", "take_profit_pct", "max_drawdown_pct"):
            value = getattr(self, name)
            if not 0 < value <= 1:
                raise ConfigError(f"{name} must be between 0 and 1, got {value}")
        if self.time_in_force not in {"gtc", "ioc"}:
            raise ConfigError(
                "Alpaca crypto orders only support time_in_force of 'gtc' or "
                f"'ioc', got {self.time_in_force!r}"
            )
        if not self.symbols:
            raise ConfigError("At least one symbol must be configured.")

        from .brokers import SUPPORTED_BROKERS
        if self.broker not in SUPPORTED_BROKERS:
            raise ConfigError(
                f"Unknown BROKER {self.broker!r}. "
                f"Supported: {', '.join(SUPPORTED_BROKERS)}"
            )

        # Safety interlock: refuse to touch the live endpoint unless the
        # operator has explicitly opted out of paper trading.
        if not self.paper and self.base_url == LIVE_ENDPOINT:
            if not _env_bool("ALPACA_ALLOW_LIVE", False):
                raise ConfigError(
                    "Refusing to trade against the LIVE endpoint. Set "
                    "ALPACA_ALLOW_LIVE=true to override this safety check."
                )


def load_config() -> Config:
    """Build a :class:`Config` from the environment and validate it."""
    from .symbols import to_data_symbol

    paper = _env_bool("ALPACA_PAPER", True)
    base_url = os.getenv("ALPACA_BASE_URL") or (
        PAPER_ENDPOINT if paper else LIVE_ENDPOINT
    )

    raw_symbols = os.getenv("SYMBOLS", "BTC/USD,ETH/USD")
    symbols = [
        to_data_symbol(s) for s in raw_symbols.split(",") if s.strip()
    ]

    config = Config(
        api_key=os.getenv("ALPACA_API_KEY", "").strip(),
        secret_key=os.getenv("ALPACA_SECRET_KEY", "").strip(),
        base_url=base_url,
        paper=paper,
        broker=os.getenv("BROKER", "alpaca").strip().lower(),
        symbols=symbols,
        timeframe=os.getenv("TIMEFRAME", "4Hour"),
        bar_limit=_env_int("BAR_LIMIT", 200),
        fast_window=_env_int("FAST_WINDOW", 20),
        slow_window=_env_int("SLOW_WINDOW", 60),
        neutral_band_pct=_env_float("NEUTRAL_BAND_PCT", 0.15),
        rsi_period=_env_int("RSI_PERIOD", 14),
        rsi_overbought=_env_float("RSI_OVERBOUGHT", 75.0),
        rsi_oversold=_env_float("RSI_OVERSOLD", 25.0),
        max_exposure_pct=_env_float("MAX_EXPOSURE_PCT", 0.50),
        per_trade_pct=_env_float("PER_TRADE_PCT", 0.02),
        max_position_pct=_env_float("MAX_POSITION_PCT", 0.25),
        stop_loss_pct=_env_float("STOP_LOSS_PCT", 0.05),
        take_profit_pct=_env_float("TAKE_PROFIT_PCT", 0.10),
        max_drawdown_pct=_env_float("MAX_DRAWDOWN_PCT", 0.15),
        min_notional=_env_float("MIN_NOTIONAL", 1.0),
        dry_run=_env_bool("DRY_RUN", False),
        time_in_force=os.getenv("TIME_IN_FORCE", "gtc").strip().lower(),
    )
    config.validate()
    return config
