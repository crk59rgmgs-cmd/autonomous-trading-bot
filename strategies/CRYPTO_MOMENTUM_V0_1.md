# Crypto Momentum v0.1

Status: PAPER-TRADING ONLY

## Goal
Find tradable continuation structures in crypto after abnormal momentum without chasing vertical price moves.

## Standardized scanner windows
Compute directly from candles:
- 1h return
- 4h return
- 24h return
- recent range expansion
- recent trend structure
- relative strength vs BTC
- catalyst/news context when available

Do not rely only on a website's "% today" figure because crypto reference windows can differ.

## Core setup M1: Momentum Base Breakout
Required sequence:
1. abnormal upward momentum / relative strength
2. consolidation or base lasting roughly 5-30 minutes
3. bullish structure with higher lows or tight acceptance near the base high
4. breakout above base resistance
5. breakout holds
6. preferred entry on retest/reclaim or confirmation-candle break

## Entry preference
Do not chase a large impulse candle.
Prefer:
- breakout -> retest -> continuation
- tight base -> breakout -> hold
- failed breakdown -> reclaim inside a strong momentum regime

## Invalidation / stop
Stop below the structure that proves the breakout/retest failed.
Never widen the stop.
Never average down.

## Profit-taking
- TP1: +1R
- TP2: around +2R or next major structure level
- runner: trail below 5m higher lows when trend remains clean

## Quality filters
Prefer:
- clean 5m structure
- strong relative strength vs BTC
- orderly consolidation after impulse
- repeated defense of a base
- clear catalyst where available

Avoid:
- vertical moves with no definable stop
- chaotic two-sided whipsaw
- thin / erratic price action
- buying solely because a coin is already +50% or +100%

## Session controls
- max 2 attempts on the same coin
- stop testing session at -2R
- no averaging down
- no moving stops farther away
- NO TRADE is valid

## Principle
Biggest mover != best setup.
We want abnormal momentum plus clean structure plus defined risk.

## Measurement
Record:
- symbol
- 1h / 4h / 24h returns
- BTC regime
- setup type
- base high / low
- entry
- invalidation
- TP1 / TP2
- R result
- time
- catalyst/news
- notes on structure quality
