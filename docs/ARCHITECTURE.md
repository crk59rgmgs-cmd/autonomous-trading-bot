# Paper Trading System Architecture

Status: DESIGN / PAPER ONLY

## Components

1. Data layer
- Webull snapshots
- Webull candles
- Webull quotes and available flow data
- public news / catalysts
- optional secondary research sources

2. Scanner layer
- SPY level builder and regime classifier
- crypto 1h/4h/24h momentum scanner
- candidate ranking by structure quality

3. Signal engine
- deterministic rules from strategy specs
- explicit setup type
- entry trigger
- invalidation
- TP1 / TP2
- NO TRADE state

4. Risk engine
- R-based accounting
- per-session max loss
- max attempts
- no averaging down
- no stop widening

5. Paper execution layer
- simulate fills
- account for spread/slippage assumptions
- never submit live-money orders

6. Journal
- one record per signal / trade
- store inputs, outputs and result

7. Evaluation layer
Track:
- win rate
- average win / loss
- expectancy
- profit factor
- max drawdown
- performance by setup
- performance by regime
- performance by time of day
- performance by confirmation feature

8. Learning loop
The system does NOT automatically rewrite live rules after individual trades.

Approved process:
v0.1 -> collect enough paper trades -> analyze -> propose change -> backtest / paper-test separately -> compare -> human review -> version bump.

This reduces overfitting and preserves auditability.

## Source of truth
- strategy markdown files define human-readable logic
- config/paper_strategy.json defines machine-readable controls
- journal/paper_trades.csv stores test outcomes
- Git history records all accepted strategy changes

## Safety
All current automation is for research and simulated/paper trading only.
