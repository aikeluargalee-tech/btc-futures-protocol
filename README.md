# BTC Futures Swing Trading Protocol (v1.0)

Deterministic signal generation, multi-factor regime analysis, and paper-ledger risk control for BTC perpetual futures, automated via **GitHub Actions** and published to **GitHub Pages**.

## Implemented Architecture

- **Configurable Constants** (`config/protocol_params.json`): All factor weights (30/25/25/20), regime thresholds (≥ 65 Long / ≤ 35 Short / 36–64 Neutral), 1:2 max leverage, 0.5% risk per trade, 2% max portfolio heat, 4% max stop distance, 1.8:1 min R:R, and circuit breakers (-1.5% daily, -3% weekly, -8% DD tier 1, -12% DD tier 2).
- **Multi-Factor Regime Engine** (`engine/regime_engine.py`): Continuous 0–100 score across Trend Structure (30%), Momentum & Breadth (25%), Volatility & Liquidity (25%), and Macro / External Context (20%).
- **Qualification & Sizing Engine** (`engine/signal_engine.py`): Enforces all 7 qualification rules, HTF structural level interaction, 4H execution confirmation (BOS or volume-backed rejection), funding-adjusted R:R ≥ 1.8:1, ±30m macro release gate, and hard 2× leverage clamp.
- **Paper Ledger & Trade Management** (`engine/paper_ledger.py`): Tracks open/closed positions in `data/ledger.json`, executes breakeven moves & trailing stops (≥ 1R), 40% scale-outs (≥ 1.5R), 7–10 day time stops, circuit breakers, and weekly review metrics (`30`-trade sample gate).
- **GitHub Actions** (`.github/workflows/protocol_engine.yml`): Runs tests + `python -m engine.run_cycle` every 15 minutes and commits updated `data/*.json`.
- **GitHub Pages Dashboard** (`index.html`, `style.css`, `app.js`): 4-tab live UI (Signal Tab, Multi-Factor Regime, Paper Ledger & Interactive Risk Calculator, Audit Log & Config) with 5s live BTC price polling.

## Local Usage

```bash
python -m pytest -v
python -m engine.run_cycle
python -m http.server 8000
```
