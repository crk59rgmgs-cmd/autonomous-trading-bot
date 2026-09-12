"""Trading strategy: MA crossover with a neutral band and an RSI filter.

The previous strategy compared the last close to a 20-period mean and returned
``buy`` when above and ``sell`` when below. Because price is essentially never
exactly equal to its mean, that produced a signal on *every* single run,
causing constant churn.

This implementation fixes that in three ways:

1. A fast/slow moving-average **spread** must exceed ``neutral_band_pct``
   before any signal is emitted; inside the band the result is ``hold``.
2. An RSI filter suppresses buying into overbought conditions and selling
   into oversold ones.
3. Signals are *state aware* at the caller level, so an existing position is
   not repeatedly topped up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

BUY = "buy"
SELL = "sell"
HOLD = "hold"


@dataclass
class Signal:
    action: str
    price: float
    fast_ma: Optional[float] = None
    slow_ma: Optional[float] = None
    rsi: Optional[float] = None
    reason: str = ""

    def __str__(self) -> str:
        return f"{self.action} ({self.reason})"


def extract_closes(bars: Sequence) -> List[float]:
    """Pull close prices out of SDK bar entities or plain dicts/floats."""
    closes: List[float] = []
    for bar in bars:
        if isinstance(bar, (int, float)):
            closes.append(float(bar))
            continue
        value = None
        if isinstance(bar, dict):
            value = bar.get("close", bar.get("c"))
        else:
            value = getattr(bar, "close", None)
            if value is None:
                value = getattr(bar, "c", None)
        if value is None:
            continue
        closes.append(float(value))
    return closes


def sma(values: Sequence[float], window: int) -> Optional[float]:
    """Simple moving average of the trailing ``window`` values."""
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def rsi(values: Sequence[float], period: int = 14) -> Optional[float]:
    """Wilder's RSI. Returns ``None`` when there is insufficient history."""
    if period <= 0 or len(values) < period + 1:
        return None

    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period

    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def get_signal(bars, fast_window: int = 20, slow_window: int = 60,
               neutral_band_pct: float = 0.15, rsi_period: int = 14,
               rsi_overbought: float = 75.0,
               rsi_oversold: float = 25.0) -> Signal:
    """Evaluate the strategy and return a :class:`Signal`.

    ``neutral_band_pct`` is expressed in percent (0.15 == 0.15%).
    """
    closes = extract_closes(bars)

    if len(closes) < slow_window:
        return Signal(
            HOLD,
            price=closes[-1] if closes else 0.0,
            reason=f"insufficient history: {len(closes)}/{slow_window} bars",
        )

    price = closes[-1]
    fast = sma(closes, fast_window)
    slow = sma(closes, slow_window)
    momentum = rsi(closes, rsi_period)

    if fast is None or slow is None or slow == 0:
        return Signal(HOLD, price=price, reason="moving averages unavailable")

    spread_pct = (fast - slow) / slow * 100.0

    base = Signal(HOLD, price=price, fast_ma=fast, slow_ma=slow, rsi=momentum)

    if abs(spread_pct) < neutral_band_pct:
        base.reason = (
            f"spread {spread_pct:+.3f}% inside neutral band "
            f"+/-{neutral_band_pct:.3f}%"
        )
        return base

    if spread_pct > 0:
        if momentum is not None and momentum >= rsi_overbought:
            base.reason = (
                f"bullish spread {spread_pct:+.3f}% but RSI {momentum:.1f} "
                f">= {rsi_overbought} (overbought)"
            )
            return base
        base.action = BUY
        base.reason = f"fast>slow by {spread_pct:+.3f}%"
        return base

    if momentum is not None and momentum <= rsi_oversold:
        base.reason = (
            f"bearish spread {spread_pct:+.3f}% but RSI {momentum:.1f} "
            f"<= {rsi_oversold} (oversold)"
        )
        return base
    base.action = SELL
    base.reason = f"fast<slow by {spread_pct:+.3f}%"
    return base
