"""Main orchestrator run every 15 minutes by GitHub Actions (Protocol v4.0)."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from .config import load_config
from .context_overlays import compute_context_overlays
from .cortex_rhyme_engine import compute_cortex_rhyme
from .data_fetcher import fetch_all_market_data
from .kline_playbook_engine import compute_regime_and_kline_playbook
from .news_macro_engine import compute_news_macro
from .positioning_matrix import compute_positioning_matrix_g
from .paper_ledger import (
    compute_review_metrics,
    execute_signal_entry,
    init_ledger,
    migrate_ledger_schema,
    process_cycle,
    reset_review_lock,
)
from .regime_engine import compute_regime
from .signal_engine import evaluate_signal
from .spot_magnet_engine import compute_spot_magnet
from .spot_shield_engine import compute_spot_shield

ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / "data" / "ledger.json"
STATE_PATH = ROOT / "data" / "state.json"
AUDIT_PATH = ROOT / "data" / "audit_log.json"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    cfg = load_config()
    prev_state = _load_json(STATE_PATH)
    prev_regime = prev_state.get("regime") if prev_state else None

    ledger = _load_json(LEDGER_PATH)
    if not ledger:
        ledger = init_ledger(cfg, now)
    else:
        migrate_ledger_schema(ledger, cfg, now)

    if os.getenv("RESET_REVIEW_LOCK", "").strip().lower() == "true":
        reset_review_lock(ledger, cfg, now)

    market = fetch_all_market_data()
    dd_tier1 = bool((ledger.get("breakers") or {}).get("dd_tier1_active"))
    regime = compute_regime(market, cfg, dd_tier1_active=dd_tier1, prev_regime=prev_regime, now_utc=now)

    ledger = process_cycle(ledger, market, regime, cfg, now)
    signal = evaluate_signal(market, regime, ledger, cfg)
    ledger = execute_signal_entry(ledger, signal, regime=regime, now=now)

    if signal["status"] in ("LONG", "SHORT"):
        signal = evaluate_signal(market, regime, ledger, cfg)

    playbook_bundle = compute_regime_and_kline_playbook(market, regime, signal)
    regime["state_of_regime"] = playbook_bundle["state_of_regime"]
    spot_magnet = compute_spot_magnet(market, regime, signal)
    cortex_rhyme = compute_cortex_rhyme()
    positioning_matrix_g = compute_positioning_matrix_g(market, cortex_rhyme=cortex_rhyme)
    news_macro = compute_news_macro(market, now_utc=now)
    spot_shield = compute_spot_shield(now_utc=now)
    context_overlays = compute_context_overlays(
        market,
        signal=signal,
        spot_magnet=spot_magnet,
        cortex_rhyme=cortex_rhyme,
        news_macro=news_macro,
        now_utc=now,
    )

    _save_json(LEDGER_PATH, ledger)
    _save_json(AUDIT_PATH, ledger["audit_log"][-100:])

    cb = cfg["circuit_breakers"]
    eq = ledger["equity"]
    intraday_peak = ledger.get("intraday_peak_equity") or ledger["day_start_equity"] or eq
    intraday_pnl_pct = round(((eq - intraday_peak) / intraday_peak) * 100.0, 2) if intraday_peak > 0 else 0.0
    day_pnl_pct = (
        round(((eq - ledger["day_start_equity"]) / ledger["day_start_equity"]) * 100.0, 2)
        if ledger["day_start_equity"] > 0
        else 0.0
    )
    wk_pnl_pct = (
        round(((eq - ledger["week_start_equity"]) / ledger["week_start_equity"]) * 100.0, 2)
        if ledger["week_start_equity"] > 0
        else 0.0
    )
    dd_pct = float(ledger["drawdown_pct"])

    intraday_lim = cb["intraday_loss_limit_pct"] * 100.0
    daily_lim = cb["daily_loss_limit_pct"] * 100.0
    weekly_lim = cb["weekly_loss_limit_pct"] * 100.0
    dd1_lim = cb["drawdown_tier1_pct"] * 100.0
    dd2_lim = cb["drawdown_tier2_pct"] * 100.0

    current_heat_pct = round(sum(float(p.get("risk_pct", 0.0)) for p in ledger["open_positions"]), 3)
    open_notional_usd = round(sum(float(p.get("notional_usd", 0.0)) for p in ledger["open_positions"]), 2)
    current_leverage = round(open_notional_usd / eq, 3) if eq > 0 else 0.0
    risk_per_trade_pct = round(
        (
            cb["drawdown_tier1_risk_pct"]
            if ledger["breakers"]["dd_tier1_active"]
            else cfg["leverage_and_risk"]["risk_per_trade_pct"]
        )
        * 100.0,
        2,
    )

    h4_bars = (market.get("klines") or {}).get("4h") or []
    d1_bars = (market.get("klines") or {}).get("1d") or []
    charts = {
        "h4": [
            [
                c["ts"],
                round(c["open"], 1),
                round(c["high"], 1),
                round(c["low"], 1),
                round(c["close"], 1),
                round(c.get("volume", 0.0), 2),
            ]
            for c in h4_bars[-90:]
        ],
        "d1": [
            [
                c["ts"],
                round(c["open"], 1),
                round(c["high"], 1),
                round(c["low"], 1),
                round(c["close"], 1),
                round(c.get("volume", 0.0), 2),
            ]
            for c in d1_bars[-90:]
        ],
    }

    portfolio = {
        "equity_usd": eq,
        "realized_equity_usd": ledger["realized_equity"],
        "high_water_mark_usd": ledger["high_water_mark"],
        "drawdown_pct": dd_pct,
        "intraday_pnl_pct": intraday_pnl_pct,
        "intraday_limit_pct": intraday_lim,
        "intraday_buffer_pct": round(intraday_pnl_pct - intraday_lim, 2),
        "daily_pnl_pct": day_pnl_pct,
        "daily_limit_pct": daily_lim,
        "daily_buffer_pct": round(day_pnl_pct - daily_lim, 2),
        "weekly_pnl_pct": wk_pnl_pct,
        "weekly_limit_pct": weekly_lim,
        "weekly_buffer_pct": round(wk_pnl_pct - weekly_lim, 2),
        "dd_tier1_pct": dd1_lim,
        "dd_tier1_buffer_pct": round(dd_pct - dd1_lim, 2),
        "dd_tier2_pct": dd2_lim,
        "dd_tier2_buffer_pct": round(dd_pct - dd2_lim, 2),
        "open_heat_pct": current_heat_pct,
        "max_heat_pct": cfg["leverage_and_risk"]["max_portfolio_heat_pct"] * 100.0,
        "open_notional_usd": open_notional_usd,
        "current_leverage": current_leverage,
        "max_leverage": cfg["leverage_and_risk"]["max_leverage"],
        "risk_per_trade_pct": risk_per_trade_pct,
        "circuit_breakers": ledger["breakers"],
        "open_positions": ledger["open_positions"],
        "closed_trades": ledger["closed_trades"][-25:],
        "review": compute_review_metrics(ledger),
    }

    state = {
        "protocol_version": cfg["protocol_version"],
        "protocol_name": cfg["protocol_name"],
        "updated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_at_ms": int(now.timestamp() * 1000),
        "last_4h_close_utc": regime.get("last_4h_close_utc"),
        "ticker": market["ticker"],
        "derivatives": {
            "current_rate_pct": (market.get("derivatives") or {}).get("current_rate_pct"),
            "oi_btc": (market.get("derivatives") or {}).get("oi_btc"),
            "total_oi_btc": (market.get("derivatives") or {}).get("total_oi_btc"),
            "venues": (market.get("derivatives") or {}).get("venues"),
            "venue_oi_btc": (market.get("derivatives") or {}).get("venue_oi_btc"),
            "orderbook_1pct": (market.get("derivatives") or {}).get("orderbook_1pct"),
            "cmc_liquidations": (market.get("derivatives") or {}).get("cmc_liquidations"),
        },
        "extras": market.get("extras") or {},
        "etf": market.get("etf"),
        "stables": market.get("stables"),
        "macro_calendar": market.get("macro_calendar") or [],
        "charts": charts,
        "regime": regime,
        "state_of_regime": playbook_bundle["state_of_regime"],
        "kline_patterns": playbook_bundle["kline_patterns"],
        "cortex_11p": playbook_bundle["cortex_11p"],
        "spot_magnet": spot_magnet,
        "spot_shield": spot_shield,
        "cortex_rhyme": cortex_rhyme,
        "positioning_matrix_g": positioning_matrix_g,
        "context_overlays": context_overlays,
        "news_macro": news_macro,
        "signal": signal,
        "portfolio": portfolio,
        "audit_log_recent": list(reversed(ledger["audit_log"][-40:])),
        "config": cfg,
        "fetch_errors": market.get("fetch_errors") or [],
    }
    _save_json(STATE_PATH, state)
    sh_s1 = (spot_shield.get("sleeve1") or {}).get("action", "—")
    sh_s2 = (spot_shield.get("sleeve2") or {}).get("action", "—")
    print(
        f"[OK] BTC={market['ticker']['price']} | v4.0 Regime={regime['score']} ({regime['bias']}, 1D={regime.get('daily_bias')}, {playbook_bundle['state_of_regime']['code']}) | Spot={(spot_magnet.get('regime_diagnosis') or {}).get('name')} | Shield={sh_s1}/{sh_s2} | News={len(news_macro.get('headlines') or [])} | KlineHits={playbook_bundle['kline_patterns']['active_count']} | Signal={signal['status']} | Eq=${eq:,.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
