"""Orchestrator for BTC Futures Swing Trading Protocol v1.0 (GitHub Actions & Local)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from .config import ROOT_DIR, load_config
from .data_fetcher import fetch_all_market_data
from .paper_ledger import compute_review_metrics, execute_signal_entry, init_ledger, process_cycle
from .regime_engine import compute_regime
from .signal_engine import evaluate_signal


def _load_json(path: Path, default: Any) -> Any:
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return default
    return default


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def run_cycle(
    root_dir: Path | str | None = None,
    reset_review_lock: bool = False,
    market_data_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one full deterministic evaluation & paper-ledger cycle."""
    root = Path(root_dir) if root_dir else ROOT_DIR
    cfg = load_config(root / "config" / "protocol_params.json")
    data_dir = root / "data"
    ledger_path = data_dir / "ledger.json"
    audit_path = data_dir / "audit_log.json"
    state_path = data_dir / "state.json"

    now_utc = dt.datetime.now(dt.timezone.utc)
    ledger = _load_json(ledger_path, init_ledger(cfg, now_utc))
    audit_log: list[dict[str, Any]] = _load_json(audit_path, [])

    market_data = market_data_override or fetch_all_market_data()
    prev_regime = ledger.get("last_regime")
    dd_tier1 = bool((ledger.get("circuit_breakers") or {}).get("dd_tier1_active"))

    regime = compute_regime(market_data, cfg, dd_tier1_active=dd_tier1, prev_regime=prev_regime)
    ledger, cycle_events = process_cycle(
        ledger, market_data, regime, cfg, now_utc=now_utc, reset_review_lock=reset_review_lock
    )

    # Re-evaluate regime if DD Tier 1 state changed during process_cycle
    new_dd_tier1 = bool((ledger.get("circuit_breakers") or {}).get("dd_tier1_active"))
    if new_dd_tier1 != dd_tier1:
        regime = compute_regime(market_data, cfg, dd_tier1_active=new_dd_tier1, prev_regime=prev_regime)

    signal = evaluate_signal(market_data, regime, ledger, cfg)

    if signal["status"] in ("LONG", "SHORT"):
        pos = execute_signal_entry(ledger, signal, regime, now_utc=now_utc)
        if pos:
            cycle_events.append(pos["actions"][0])

    # Portfolio heat & circuit-breaker distance metrics (Section 11)
    open_heat_pct = round(sum(float(p.get("risk_pct", 0.0)) for p in ledger["open_positions"]), 3)
    open_notional = round(sum(float(p.get("size_btc", 0.0)) * (market_data["ticker"].get("price") or p["entry_price"]) for p in ledger["open_positions"]), 2)
    eq = max(float(ledger["equity"]), 1.0)
    cur_leverage = round(open_notional / eq, 3)

    cb_cfg = cfg["circuit_breakers"]
    daily_limit = cb_cfg["daily_loss_limit_pct"] * 100.0
    weekly_limit = cb_cfg["weekly_loss_limit_pct"] * 100.0
    dd1_limit = cb_cfg["drawdown_tier1_pct"] * 100.0
    dd2_limit = cb_cfg["drawdown_tier2_pct"] * 100.0

    portfolio_summary = {
        "equity_usd": ledger["equity"],
        "realized_equity_usd": ledger["realized_equity"],
        "high_water_mark_usd": ledger["high_water_mark"],
        "unrealized_pnl_usd": ledger.get("unrealized_pnl_usd", 0.0),
        "open_heat_pct": open_heat_pct,
        "max_heat_pct": cfg["leverage_and_risk"]["max_portfolio_heat_pct"] * 100.0,
        "open_notional_usd": open_notional,
        "current_leverage": cur_leverage,
        "max_leverage": cfg["leverage_and_risk"]["max_leverage"],
        "daily_pnl_pct": ledger["daily_pnl_pct"],
        "daily_limit_pct": daily_limit,
        "daily_buffer_pct": round(ledger["daily_pnl_pct"] - daily_limit, 3),
        "weekly_pnl_pct": ledger["weekly_pnl_pct"],
        "weekly_limit_pct": weekly_limit,
        "weekly_buffer_pct": round(ledger["weekly_pnl_pct"] - weekly_limit, 3),
        "drawdown_pct": ledger["drawdown_pct"],
        "dd_tier1_limit_pct": dd1_limit,
        "dd_tier1_buffer_pct": round(ledger["drawdown_pct"] - dd1_limit, 3),
        "dd_tier2_limit_pct": dd2_limit,
        "dd_tier2_buffer_pct": round(ledger["drawdown_pct"] - dd2_limit, 3),
        "circuit_breakers": ledger["circuit_breakers"],
        "open_positions": ledger["open_positions"],
        "closed_trades": ledger["closed_trades"][-30:],
        "review": compute_review_metrics(ledger, cfg),
    }

    ledger["last_regime"] = {
        "score": regime.get("score"),
        "bias": regime.get("bias"),
        "recalc_utc_day": regime.get("recalc_utc_day"),
        "groups": {
            "trend_structure": {
                "daily_structure": ((regime.get("groups") or {}).get("trend_structure") or {}).get("daily_structure"),
                "h4_structure": ((regime.get("groups") or {}).get("trend_structure") or {}).get("h4_structure"),
            }
        },
    }

    if cycle_events:
        audit_log = (audit_log + cycle_events)[-250:]
        _save_json(audit_path, audit_log)
    elif not audit_path.exists():
        _save_json(audit_path, audit_log)

    # Compact chart series for the web dashboard
    h4_bars = market_data["klines"]["4h"][-60:]
    d1_bars = market_data["klines"]["1d"][-60:]

    state = {
        "protocol_version": cfg["protocol_version"],
        "updated_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_at_ms": int(now_utc.timestamp() * 1000),
        "ticker": market_data["ticker"],
        "derivatives": {
            "current_rate_pct": market_data["derivatives"].get("current_rate_pct"),
            "oi_btc": market_data["derivatives"].get("oi_btc"),
            "venues": market_data["derivatives"].get("venues"),
        },
        "extras": market_data.get("extras") or {},
        "etf": market_data.get("etf"),
        "stables": market_data.get("stables"),
        "macro_calendar": market_data.get("macro_calendar") or [],
        "regime": regime,
        "signal": signal,
        "portfolio": portfolio_summary,
        "charts": {
            "h4": [[c["ts"], c["open"], c["high"], c["low"], c["close"]] for c in h4_bars],
            "d1": [[c["ts"], c["open"], c["high"], c["low"], c["close"]] for c in d1_bars],
        },
        "audit_log_recent": list(reversed(audit_log[-40:])),
        "config": cfg,
        "fetch_errors": market_data.get("fetch_errors") or [],
    }

    _save_json(ledger_path, ledger)
    _save_json(state_path, state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BTC Futures Swing Trading Protocol cycle.")
    parser.add_argument("--reset-review-lock", action="store_true", help="Clear -12% DD manual review halt.")
    args = parser.parse_args()
    reset = args.reset_review_lock or (os.environ.get("RESET_REVIEW_LOCK", "").lower() in ("1", "true", "yes"))
    state = run_cycle(reset_review_lock=reset)
    sig = state["signal"]
    reg = state["regime"]
    print(
        f"BTC=${state['ticker'].get('price')} | Regime={reg.get('score')} ({reg.get('bias')}) | "
        f"Signal={sig.get('status')} | Equity=${state['portfolio']['equity_usd']:,.2f} | "
        f"Open={len(state['portfolio']['open_positions'])} | Errors={len(state['fetch_errors'])}"
    )


if __name__ == "__main__":
    main()
