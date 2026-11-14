"""Deterministic Paper-Trading Ledger, Trade Management & Circuit Breakers (Sections 7-10)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from .indicators import ema_series, swing_pivots


def init_ledger(cfg: dict[str, Any], now_utc: dt.datetime | None = None) -> dict[str, Any]:
    """Create initial clean paper-trading ledger."""
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    eq = float(cfg["account"]["initial_equity_usd"])
    iso_year, iso_week, _ = now.isocalendar()
    return {
        "protocol_version": cfg["protocol_version"],
        "realized_equity": eq,
        "equity": eq,
        "high_water_mark": eq,
        "drawdown_pct": 0.0,
        "utc_day": now.strftime("%Y-%m-%d"),
        "day_start_equity": eq,
        "daily_pnl_pct": 0.0,
        "utc_week": f"{iso_year}-W{iso_week:02d}",
        "week_start_equity": eq,
        "weekly_pnl_pct": 0.0,
        "circuit_breakers": {
            "daily_halted": False,
            "weekly_halted": False,
            "dd_tier1_active": False,
            "dd_tier2_locked": False,
        },
        "open_positions": [],
        "closed_trades": [],
        "last_regime": None,
        "trade_seq": 0,
    }


def _unrealized_pnl(pos: dict[str, Any], price: float) -> float:
    diff = (price - pos["entry_price"]) if pos["direction"] == "LONG" else (pos["entry_price"] - price)
    return diff * pos["size_btc"]


def _unrealized_r(pos: dict[str, Any], price: float) -> float:
    risk_per_btc = abs(pos["entry_price"] - pos["initial_stop_price"])
    if risk_per_btc <= 0:
        return 0.0
    diff = (price - pos["entry_price"]) if pos["direction"] == "LONG" else (pos["entry_price"] - price)
    return diff / risk_per_btc


def _recompute_account_metrics(ledger: dict[str, Any], mark_price: float) -> None:
    unreal = sum(_unrealized_pnl(p, mark_price) for p in ledger["open_positions"])
    total_eq = ledger["realized_equity"] + unreal
    ledger["equity"] = round(total_eq, 2)
    ledger["unrealized_pnl_usd"] = round(unreal, 2)
    ledger["high_water_mark"] = round(max(ledger["high_water_mark"], total_eq), 2)
    hwm = ledger["high_water_mark"]
    ledger["drawdown_pct"] = round(((total_eq - hwm) / hwm) * 100.0, 3) if hwm > 0 else 0.0
    d0 = ledger["day_start_equity"]
    w0 = ledger["week_start_equity"]
    ledger["daily_pnl_pct"] = round(((total_eq - d0) / d0) * 100.0, 3) if d0 > 0 else 0.0
    ledger["weekly_pnl_pct"] = round(((total_eq - w0) / w0) * 100.0, 3) if w0 > 0 else 0.0


def _close_position(
    ledger: dict[str, Any],
    pos: dict[str, Any],
    exit_price: float,
    reason: str,
    now_iso: str,
    audit_events: list[dict[str, Any]],
    fraction: float = 1.0,
) -> None:
    close_btc = pos["size_btc"] * fraction
    diff = (exit_price - pos["entry_price"]) if pos["direction"] == "LONG" else (pos["entry_price"] - exit_price)
    pnl_usd = diff * close_btc
    risk_per_btc = abs(pos["entry_price"] - pos["initial_stop_price"])
    r_mult = (diff / risk_per_btc) if risk_per_btc > 0 else 0.0

    ledger["realized_equity"] = round(ledger["realized_equity"] + pnl_usd, 2)
    pos["realized_partial_usd"] = round(pos.get("realized_partial_usd", 0.0) + pnl_usd, 2)

    action = {
        "ts_utc": now_iso,
        "trade_id": pos["id"],
        "event": reason,
        "direction": pos["direction"],
        "price": round(exit_price, 1),
        "size_btc": round(close_btc, 6),
        "pnl_usd": round(pnl_usd, 2),
        "r_multiple": round(r_mult, 2),
    }
    pos.setdefault("actions", []).append(action)
    audit_events.append(action)

    if fraction >= 0.999:
        total_pnl = pos["realized_partial_usd"]
        init_risk_usd = pos["initial_risk_usd"]
        total_r = (total_pnl / init_risk_usd) if init_risk_usd > 0 else r_mult
        ledger["closed_trades"].append(
            {
                "id": pos["id"],
                "role": pos["role"],
                "direction": pos["direction"],
                "opened_at_utc": pos["opened_at_utc"],
                "closed_at_utc": now_iso,
                "entry_price": pos["entry_price"],
                "exit_price": round(exit_price, 1),
                "initial_stop_price": pos["initial_stop_price"],
                "initial_size_btc": pos["initial_size_btc"],
                "initial_risk_usd": pos["initial_risk_usd"],
                "regime_score_at_entry": pos["regime_score_at_entry"],
                "dominant_factors": pos["dominant_factors"],
                "pnl_usd": round(total_pnl, 2),
                "r_multiple": round(total_r, 2),
                "exit_reason": reason,
                "actions": pos["actions"],
            }
        )
        ledger["open_positions"] = [p for p in ledger["open_positions"] if p["id"] != pos["id"]]
    else:
        pos["size_btc"] = round(pos["size_btc"] - close_btc, 6)
        pos["risk_usd"] = round(abs(pos["entry_price"] - pos["stop_price"]) * pos["size_btc"], 2)
        pos["risk_pct"] = round((pos["risk_usd"] / max(ledger["equity"], 1.0)) * 100.0, 4)


def process_cycle(
    ledger: dict[str, Any],
    market_data: dict[str, Any],
    regime: dict[str, Any],
    cfg: dict[str, Any],
    now_utc: dt.datetime | None = None,
    reset_review_lock: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Advance ledger state: rollovers, position exits/trails, circuit breakers, and optional entry."""
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    audit_events: list[dict[str, Any]] = []

    mark_price = float(market_data["ticker"].get("price") or 0.0)
    if mark_price <= 0:
        return ledger, audit_events

    if reset_review_lock:
        _recompute_account_metrics(ledger, mark_price)
        ledger["high_water_mark"] = ledger["equity"]
        ledger["day_start_equity"] = ledger["equity"]
        ledger["week_start_equity"] = ledger["equity"]
        ledger["circuit_breakers"]["dd_tier2_locked"] = False
        ledger["circuit_breakers"]["dd_tier1_active"] = False
        ledger["circuit_breakers"]["daily_halted"] = False
        ledger["circuit_breakers"]["weekly_halted"] = False
        audit_events.append(
            {
                "ts_utc": now_iso,
                "event": "MANUAL_REVIEW_RESET",
                "detail": f"Process review completed; HWM rebased to ${ledger['equity']:,.2f}",
            }
        )

    # 1. UTC day / week rollovers
    _recompute_account_metrics(ledger, mark_price)
    cur_day = now.strftime("%Y-%m-%d")
    iso_year, iso_week, _ = now.isocalendar()
    cur_week = f"{iso_year}-W{iso_week:02d}"

    if cur_day != ledger["utc_day"]:
        ledger["utc_day"] = cur_day
        ledger["day_start_equity"] = ledger["equity"]
        ledger["circuit_breakers"]["daily_halted"] = False

    if cur_week != ledger["utc_week"]:
        ledger["utc_week"] = cur_week
        ledger["week_start_equity"] = ledger["equity"]
        ledger["circuit_breakers"]["weekly_halted"] = False

    # 2. Manage open positions (Sections 7 & 8)
    h1 = market_data["klines"].get("1h") or []
    h4 = market_data["klines"].get("4h") or []
    recent_h1_lo = h1[-1]["low"] if h1 else mark_price
    recent_h1_hi = h1[-1]["high"] if h1 else mark_price
    ema20_4h = ema_series([c["close"] for c in h4], cfg["trade_management"]["trail_ema_period_4h"]) if h4 else []
    trail_ema = ema20_4h[-1] if ema20_4h else None
    h4_hi, h4_lo = swing_pivots(h4[-60:], left=2, right=2) if len(h4) >= 10 else ([], [])

    for pos in list(ledger["open_positions"]):
        d = pos["direction"]
        stop = pos["stop_price"]
        cur_r = _unrealized_r(pos, mark_price)
        pos["max_favorable_r"] = round(max(pos.get("max_favorable_r", 0.0), cur_r), 2)

        # A) Hard stop check (intrabar 1H low/high or current mark)
        stop_hit = (recent_h1_lo <= stop or mark_price <= stop) if d == "LONG" else (recent_h1_hi >= stop or mark_price >= stop)
        if stop_hit:
            fill = min(stop, mark_price) if (d == "LONG" and mark_price < stop) else (max(stop, mark_price) if (d == "SHORT" and mark_price > stop) else stop)
            _close_position(ledger, pos, fill, "HARD_STOP", now_iso, audit_events, fraction=1.0)
            continue

        # B) Opposing regime threshold exit (Section 8)
        if regime.get("ok"):
            sc = regime["score"]
            th_l = regime["thresholds"]["long"]
            th_s = regime["thresholds"]["short"]
            if (d == "LONG" and sc <= th_s) or (d == "SHORT" and sc >= th_l):
                _close_position(ledger, pos, mark_price, "REGIME_FLIP_EXIT", now_iso, audit_events, fraction=1.0)
                continue

        # C) Scale-out 30-50% at 1.5-2R (Section 7)
        if not pos.get("scale_out_done") and cur_r >= cfg["trade_management"]["scale_out_r_min"]:
            pos["scale_out_done"] = True
            _close_position(
                ledger,
                pos,
                mark_price,
                "SCALE_OUT_PARTIAL",
                now_iso,
                audit_events,
                fraction=cfg["trade_management"]["scale_out_pct"],
            )

        # D) Move to breakeven & trail once >= 1R (never widen!)
        if cur_r >= cfg["trade_management"]["breakeven_trigger_r"]:
            new_stop = stop
            if d == "LONG":
                new_stop = max(new_stop, pos["entry_price"])
                if trail_ema and trail_ema < mark_price:
                    new_stop = max(new_stop, round(trail_ema, 1))
                if h4_lo and h4_lo[-1]["price"] < mark_price:
                    new_stop = max(new_stop, round(h4_lo[-1]["price"], 1))
                if new_stop > pos["stop_price"] and new_stop < mark_price:
                    pos["stop_price"] = round(new_stop, 1)
                    pos["be_moved"] = True
                    ev = {"ts_utc": now_iso, "trade_id": pos["id"], "event": "TRAIL_STOP_UPDATE", "new_stop": pos["stop_price"]}
                    pos.setdefault("actions", []).append(ev)
                    audit_events.append(ev)
            else:
                new_stop = min(new_stop, pos["entry_price"])
                if trail_ema and trail_ema > mark_price:
                    new_stop = min(new_stop, round(trail_ema, 1))
                if h4_hi and h4_hi[-1]["price"] > mark_price:
                    new_stop = min(new_stop, round(h4_hi[-1]["price"], 1))
                if new_stop < pos["stop_price"] and new_stop > mark_price:
                    pos["stop_price"] = round(new_stop, 1)
                    pos["be_moved"] = True
                    ev = {"ts_utc": now_iso, "trade_id": pos["id"], "event": "TRAIL_STOP_UPDATE", "new_stop": pos["stop_price"]}
                    pos.setdefault("actions", []).append(ev)
                    audit_events.append(ev)

        # Update dynamic risk for current stop
        pos["risk_usd"] = round(max(0.0, (pos["entry_price"] - pos["stop_price"]) * pos["size_btc"] if d == "LONG" else (pos["stop_price"] - pos["entry_price"]) * pos["size_btc"]), 2)
        pos["risk_pct"] = round((pos["risk_usd"] / max(ledger["equity"], 1.0)) * 100.0, 4)
        pos["unrealized_pnl_usd"] = round(_unrealized_pnl(pos, mark_price), 2)
        pos["unrealized_r"] = round(cur_r, 2)

        # E) Time-based review (7-10 days without 1R and no regime improvement)
        opened_dt = dt.datetime.fromisoformat(pos["opened_at_utc"].replace("Z", "+00:00"))
        age_days = (now - opened_dt).total_seconds() / 86400.0
        regime_improved = (
            (d == "LONG" and regime.get("score", 50) > pos["regime_score_at_entry"])
            or (d == "SHORT" and regime.get("score", 50) < pos["regime_score_at_entry"])
        )
        if pos.get("max_favorable_r", 0.0) < 1.0 and not regime_improved:
            if age_days >= cfg["trade_management"]["time_stop_days_max"]:
                _close_position(ledger, pos, mark_price, "TIME_STOP_EXIT", now_iso, audit_events, fraction=1.0)
                continue
            if age_days >= cfg["trade_management"]["time_stop_days_min"] and not pos.get("time_reduced"):
                pos["time_reduced"] = True
                _close_position(
                    ledger,
                    pos,
                    mark_price,
                    "TIME_STOP_REDUCE",
                    now_iso,
                    audit_events,
                    fraction=cfg["trade_management"]["time_stop_reduce_pct"],
                )

    # 3. Recompute metrics & evaluate portfolio circuit breakers (Section 9)
    _recompute_account_metrics(ledger, mark_price)
    cb_cfg = cfg["circuit_breakers"]
    cb = ledger["circuit_breakers"]

    if ledger["daily_pnl_pct"] <= cb_cfg["daily_loss_limit_pct"] * 100.0:
        if not cb["daily_halted"]:
            audit_events.append({"ts_utc": now_iso, "event": "CB_DAILY_HALT", "daily_pnl_pct": ledger["daily_pnl_pct"]})
        cb["daily_halted"] = True

    if ledger["weekly_pnl_pct"] <= cb_cfg["weekly_loss_limit_pct"] * 100.0:
        if not cb["weekly_halted"]:
            audit_events.append({"ts_utc": now_iso, "event": "CB_WEEKLY_FLAT", "weekly_pnl_pct": ledger["weekly_pnl_pct"]})
        cb["weekly_halted"] = True
        for pos in list(ledger["open_positions"]):
            _close_position(ledger, pos, mark_price, "CIRCUIT_BREAKER_WEEKLY", now_iso, audit_events, fraction=1.0)

    if ledger["drawdown_pct"] <= cb_cfg["drawdown_tier2_pct"] * 100.0:
        if not cb["dd_tier2_locked"]:
            audit_events.append({"ts_utc": now_iso, "event": "CB_DD_12_LOCK", "drawdown_pct": ledger["drawdown_pct"]})
        cb["dd_tier2_locked"] = True
        cb["dd_tier1_active"] = True
        for pos in list(ledger["open_positions"]):
            _close_position(ledger, pos, mark_price, "CIRCUIT_BREAKER_DD12", now_iso, audit_events, fraction=1.0)
    elif ledger["drawdown_pct"] <= cb_cfg["drawdown_tier1_pct"] * 100.0:
        if not cb["dd_tier1_active"]:
            audit_events.append({"ts_utc": now_iso, "event": "CB_DD_8_THROTTLE", "drawdown_pct": ledger["drawdown_pct"]})
        cb["dd_tier1_active"] = True
    else:
        cb["dd_tier1_active"] = False

    _recompute_account_metrics(ledger, mark_price)
    return ledger, audit_events


def execute_signal_entry(
    ledger: dict[str, Any],
    signal: dict[str, Any],
    regime: dict[str, Any],
    now_utc: dt.datetime | None = None,
) -> dict[str, Any] | None:
    """Open a paper position when signal status is LONG or SHORT and constraints hold."""
    if signal.get("status") not in ("LONG", "SHORT"):
        return None
    prop = signal.get("proposal") or {}
    if not prop.get("valid") or prop.get("size_btc", 0) <= 0:
        return None

    now = now_utc or dt.datetime.now(dt.timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger["trade_seq"] = ledger.get("trade_seq", 0) + 1
    tid = f"BTC-{ledger['trade_seq']:04d}"

    pos = {
        "id": tid,
        "role": prop["role"],
        "direction": signal["status"],
        "entry_method": prop["entry_method"],
        "opened_at_utc": now_iso,
        "entry_price": prop["entry_price"],
        "stop_price": prop["stop_price"],
        "initial_stop_price": prop["stop_price"],
        "target1_price": prop["target1_price"],
        "target1_label": prop["target1_label"],
        "size_btc": prop["size_btc"],
        "initial_size_btc": prop["size_btc"],
        "notional_usd": prop["notional_usd"],
        "leverage": prop["leverage"],
        "risk_usd": prop["actual_risk_usd"],
        "initial_risk_usd": prop["actual_risk_usd"],
        "risk_pct": prop["actual_risk_pct"],
        "initial_rr": prop["raw_rr"],
        "funding_adjusted_rr": prop["funding_adjusted_rr"],
        "regime_score_at_entry": regime["score"],
        "dominant_factors": regime["dominant_factors"],
        "scale_out_done": False,
        "be_moved": False,
        "time_reduced": False,
        "max_favorable_r": 0.0,
        "realized_partial_usd": 0.0,
        "unrealized_pnl_usd": 0.0,
        "unrealized_r": 0.0,
        "actions": [
            {
                "ts_utc": now_iso,
                "trade_id": tid,
                "event": "OPEN_POSITION",
                "direction": signal["status"],
                "price": prop["entry_price"],
                "stop": prop["stop_price"],
                "size_btc": prop["size_btc"],
                "notional_usd": prop["notional_usd"],
                "regime_score": regime["score"],
            }
        ],
    }
    ledger["open_positions"].append(pos)
    return pos


def compute_review_metrics(ledger: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Section 10 fixed weekly review metrics + 30-trade sample gate."""
    closed = ledger.get("closed_trades") or []
    n = len(closed)
    min_sample = cfg["review"]["min_sample_for_weight_adjustment"]
    if n == 0:
        return {
            "total_trades": 0,
            "win_rate_pct": None,
            "avg_r": None,
            "largest_winner_r": None,
            "largest_loser_r": None,
            "net_pnl_usd": 0.0,
            "min_sample_for_weight_adjustment": min_sample,
            "weight_adjustment_unlocked": False,
        }
    wins = [t for t in closed if t["pnl_usd"] > 0]
    rs = [t["r_multiple"] for t in closed]
    return {
        "total_trades": n,
        "wins": len(wins),
        "losses": n - len(wins),
        "win_rate_pct": round(len(wins) / n * 100.0, 1),
        "avg_r": round(sum(rs) / n, 2),
        "largest_winner_r": round(max(rs), 2),
        "largest_loser_r": round(min(rs), 2),
        "net_pnl_usd": round(sum(t["pnl_usd"] for t in closed), 2),
        "min_sample_for_weight_adjustment": min_sample,
        "weight_adjustment_unlocked": n >= min_sample,
    }
