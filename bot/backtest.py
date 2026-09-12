"""Offline backtest harness.

Lets strategy parameters be evaluated against historical bars before any
change is deployed. Run with:

    python -m bot.backtest --symbol BTC/USD --timeframe 1Hour --limit 1000
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .strategy import BUY, SELL, extract_closes, get_signal


@dataclass
class BacktestResult:
    symbol: str
    bars: int
    trades: int
    wins: int
    losses: int
    return_pct: float
    max_drawdown_pct: float
    buy_and_hold_pct: float

    @property
    def win_rate(self) -> float:
        return (self.wins / self.trades * 100.0) if self.trades else 0.0

    def summary(self) -> str:
        return (
            f"\n=== Backtest: {self.symbol} ===\n"
            f"Bars evaluated   : {self.bars}\n"
            f"Round-trip trades: {self.trades}\n"
            f"Win rate         : {self.win_rate:.1f}% ({self.wins}W/{self.losses}L)\n"
            f"Strategy return  : {self.return_pct:+.2f}%\n"
            f"Buy & hold return: {self.buy_and_hold_pct:+.2f}%\n"
            f"Max drawdown     : {self.max_drawdown_pct:.2f}%\n"
        )


def run_backtest(closes: Sequence[float], symbol: str = "BTC/USD",
                 fast_window: int = 20, slow_window: int = 60,
                 neutral_band_pct: float = 0.15, rsi_period: int = 14,
                 rsi_overbought: float = 75.0, rsi_oversold: float = 25.0,
                 stop_loss_pct: float = 0.05, take_profit_pct: float = 0.10,
                 fee_pct: float = 0.0025) -> BacktestResult:
    """Simulate the strategy over a close-price series.

    Long-only, all-in/all-out, with per-side fees applied.
    """
    closes = [float(c) for c in closes]
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    entry_price: Optional[float] = None
    trades = wins = losses = 0

    start = max(slow_window, rsi_period + 1)
    if len(closes) <= start:
        return BacktestResult(symbol, len(closes), 0, 0, 0, 0.0, 0.0, 0.0)

    for i in range(start, len(closes)):
        window = closes[: i + 1]
        price = window[-1]

        if entry_price is not None:
            change = (price - entry_price) / entry_price
            forced_exit = change <= -stop_loss_pct or change >= take_profit_pct
        else:
            forced_exit = False

        signal = get_signal(
            window, fast_window=fast_window, slow_window=slow_window,
            neutral_band_pct=neutral_band_pct, rsi_period=rsi_period,
            rsi_overbought=rsi_overbought, rsi_oversold=rsi_oversold,
        )

        if entry_price is None and signal.action == BUY:
            entry_price = price * (1 + fee_pct)
        elif entry_price is not None and (signal.action == SELL or forced_exit):
            gross = (price * (1 - fee_pct)) / entry_price
            equity *= gross
            trades += 1
            if gross > 1:
                wins += 1
            else:
                losses += 1
            entry_price = None

            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)

    # Mark any still-open position to market.
    if entry_price is not None:
        equity *= (closes[-1] * (1 - fee_pct)) / entry_price
        trades += 1
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)

    bh = (closes[-1] / closes[start] - 1.0) * 100.0 if closes[start] else 0.0

    return BacktestResult(
        symbol=symbol,
        bars=len(closes),
        trades=trades,
        wins=wins,
        losses=losses,
        return_pct=(equity - 1.0) * 100.0,
        max_drawdown_pct=max_dd * 100.0,
        buy_and_hold_pct=bh,
    )


def _fetch_closes(symbol: str, timeframe: str, limit: int) -> List[float]:
    from .alpaca_client import get_client, get_crypto_bars
    from .config import load_config

    config = load_config()
    api = get_client(config)
    bars = get_crypto_bars(api, symbol, timeframe, limit)
    return extract_closes(bars)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Backtest the bot strategy.")
    parser.add_argument("--symbol", default="BTC/USD")
    parser.add_argument("--timeframe", default="4Hour")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--fast", type=int, default=20)
    parser.add_argument("--slow", type=int, default=60)
    parser.add_argument("--band", type=float, default=0.15)
    parser.add_argument("--stop-loss", type=float, default=0.05)
    parser.add_argument("--take-profit", type=float, default=0.10)
    parser.add_argument("--fee", type=float, default=0.0025)
    args = parser.parse_args(argv)

    closes = _fetch_closes(args.symbol, args.timeframe, args.limit)
    result = run_backtest(
        closes, symbol=args.symbol,
        fast_window=args.fast, slow_window=args.slow,
        neutral_band_pct=args.band,
        stop_loss_pct=args.stop_loss, take_profit_pct=args.take_profit,
        fee_pct=args.fee,
    )
    print(result.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
