# BTC Short-Term Futures + Inventory Protocol v4.0

**4H / Day-Trade Only · Long & Short Futures at ≤ 1:2 · Sell Inventory Option · Multi-Factor Regime · Rigorous Risk Management**

Automated protocol evaluation engine running every 15 minutes via GitHub Actions and serving a live Signal Tab HUD on GitHub Pages:
https://aikeluargalee-tech.github.io/btc-futures-protocol/

## Core Rules (Version 4.0)
- **Actions**:
  - `LONG`: score `≥ 68` + all 9 futures checks pass (≤ 1:2 leverage)
  - `SHORT`: score `≤ 32` + all 9 futures checks pass (≤ 1:2 leverage)
  - `SELL INVENTORY`: score `≤ 32` + valid 4H structural reference (15–25%, default 20% spot BTC trim; exempt from futures checks 3–9 & futures halts; counts as 0% futures heat)
  - `FLAT`: score `33–67` (strict, no exceptions) or any failed futures check
- **4H Multi-Factor Regime (0–100)**: Trend Structure (30%), Momentum 4H (25%), Volatility & Liquidity 4H (25%), Session / Context (20%).
- **Position Sizing & Risk**: `0.4%` equity risk per trade, hard `1:2` leverage cap, `≤ 1.5%` portfolio heat, max 1 concurrent futures position, `≤ 2.2%` max stop distance, `≥ 1.6 : 1` R:R, `±60m` macro release blackout.
- **Hold & Time Management**: 4–24h intended hold, `45%` partial at `+1.5R`, BE + 4H EMA20 trail at `+1R`, `8h` 50% cut / `12h` exit if `< +1R`, `24h` max hold, UTC daily-close reduction unless regime improves, weekend holds only if score `≥ 80` or `≤ 20` at `0.5x` size.
- **5-Tier Circuit Breakers**: `-1.2%` intraday halt, `-2.0%` daily pause, `-4.0%` weekly flatten, `-6.0%` DD Tier 1 (`0.2%` risk, `75/25` thresholds), `-10.0%` DD Tier 2 flatten + manual unlock via `workflow_dispatch`.

All parameters are configurable in `config/protocol_params.json`.
