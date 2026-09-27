# SPY Range Sweep v0.1

Status: PAPER-TRADING ONLY

## Goal
Test whether SPY intraday reactions around important support/resistance and liquidity zones produce repeatable short-term directional signals.

## Timeframes
- 15m: market structure and regime
- 5m: setup confirmation
- 1m: entry timing

## Pre-market / session map
Track:
- prior-day high
- prior-day low
- prior-day close
- premarket high
- premarket low
- major 15m swing highs/lows
- opening-range high/low once established
- VWAP after the open

Prefer 3-6 meaningful zones, not many minor lines.

## Regime classifier
### RANGE
- repeated VWAP crosses
- boundaries repeatedly hold
- breakouts fail quickly
- use support-call / resistance-put fades only with confirmation

### BULL TREND
- higher highs and higher lows
- price generally above VWAP
- resistance breaks and holds
- favor pullback/retest continuation; do not repeatedly fade strength

### BEAR TREND
- lower lows and lower highs
- price generally below VWAP
- support breaks and becomes resistance
- favor failed-rally/retest continuation; do not repeatedly buy support

### CHAOS
- large conflicting candles
- news-driven whipsaws
- unclear structure
- NO TRADE

## Core setup A: Support Sweep -> Call bias
Required sequence:
1. price reaches an important support/liquidity zone
2. price trades below it or rejects it strongly
3. price reclaims the level
4. 5m confirmation closes back above or structure turns bullish
5. 1m trigger forms
6. broader regime does not strongly contradict the trade

Helpful confirmations:
- rejection wick
- bullish engulfing candle
- failed breakdown
- higher low
- volume expansion on reclaim
- VWAP alignment
- positive order-flow context

## Core setup B: Resistance Sweep -> Put bias
Mirror of setup A:
1. price reaches resistance/liquidity
2. price trades above or rejects it
3. price falls back below
4. 5m confirmation closes back below or structure turns bearish
5. 1m trigger forms
6. broader regime does not strongly contradict

## Role reversal rule
If resistance breaks, holds, and successfully retests from above, treat it as potential support.
If support breaks, holds below, and retests from beneath, treat it as potential resistance.
Do not fade confirmed breakouts.

## Entry
Enter only after confirmation. Preferred trigger:
- break of the confirmation candle in the intended direction

## Invalidation / stop
The stop is based on SPY structure invalidating the thesis, not an arbitrary option-premium percentage.
Never widen a stop after entry.

## Profit-taking
- TP1: +1R
- TP2: next major structure level
- optional runner: trail beneath/above 5m structure after TP1

## Session controls
- max 3 paper trades per SPY session
- stop session at -2R
- no revenge trading
- no averaging down
- NO TRADE is valid

## Measurement
Record:
- regime
- setup type
- key level
- SPY entry
- SPY invalidation
- TP1 / TP2
- option contract used in simulation if applicable
- option entry/exit assumptions
- R result
- time of day
- confirmations present
- news/catalyst context
- screenshot or chart notes

## Options research rule
First validate directional SPY signals. Then separately compare expiration, strike, delta, spread, theta and IV behavior in simulation.
