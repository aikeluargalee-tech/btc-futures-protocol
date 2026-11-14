"""Trade Qualification, Structural Levels, Sizing, and Signal Engine (Sections 4-7 & 9)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from .indicators import atr, detect_execution_confirmation, swing_pivots, volume_profile


def identify_structural_levels(market_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract higher-timeframe structural levels from closed 1D & 4H candles."""
    d1 = market_data["klines"]["1d"]
    h4 = market_data["klines"]["4h"]
    levels: list[dict[str, Any]] = []
    if not d1:
        return levels

    # Prior closed daily high/low & latest daily open
    last_d = d1[-1]
    levels.append({"price": round(last_d["high"], 1), "label": "Prior Daily High", "kind": "resistance"})
    levels.append({"price": round(last_d["low"], 1), "label": "Prior Daily Low", "kind": "support"})
    levels.append({"price": round(last_d["open"], 1), "label": "Daily Open", "kind": "pivot"})

    # Weekly open (Monday 00:00 UTC) and prior week H/L
    if len(d1) >= 8:
        latest_dt = dt.datetime.fromtimestamp(last_d["ts"] / 1000.0, tz=dt.timezone.utc)
        days_since_mon = latest_dt.weekday()
        week_start_idx = max(0, len(d1) - 1 - days_since_mon)
        levels.append({"price": round(d1[week_start_idx]["open"], 1), "label": "Weekly Open", "kind": "pivot"})
        if week_start_idx >= 7:
            prev_wk = d1[week_start_idx - 7 : week_start_idx]
            levels.append({"price": round(max(c["high"] for c in prev_wk), 1), "label": "Prior Weekly High", "kind": "resistance"})
            levels.append({"price": round(min(c["low"] for c in prev_wk), 1), "label": "Prior Weekly Low", "kind": "support"})

    # Daily swing pivots
    d_hi, d_lo = swing_pivots(d1[-90:], left=3, right=3)
    for idx, sh in enumerate(d_hi[-3:], 1):
        levels.append({"price": round(sh["price"], 1), "label": f"1D Swing High #{idx}", "kind": "resistance"})
    for idx, sl in enumerate(d_lo[-3:], 1):
        levels.append({"price": round(sl["price"], 1), "label": f"1D Swing Low #{idx}", "kind": "support"})

    # 4H swing pivots
    if len(h4) >= 30:
        h4_hi, h4_lo = swing_pivots(h4[-120:], left=3, right=3)
        for idx, sh in enumerate(h4_hi[-2:], 1):
            levels.append({"price": round(sh["price"], 1), "label": f"4H Swing High #{idx}", "kind": "resistance"})
        for idx, sl in enumerate(h4_lo[-2:], 1):
            levels.append({"price": round(sl["price"], 1), "label": f"4H Swing Low #{idx}", "kind": "support"})

    # 30D Volume profile references (POC / VAH / VAL)
    vp = volume_profile(d1[-30:], bin_width=100.0)
    if vp:
        levels.append({"price": vp["poc"], "label": "30D VPOC", "kind": "volume"})
        levels.append({"price": vp["vah"], "label": "30D VAH", "kind": "volume"})
        levels.append({"price": vp["val"], "label": "30D VAL", "kind": "volume"})

    # Deduplicate near-identical levels (<0.15% apart)
    levels.sort(key=lambda x: x["price"])
    deduped: list[dict[str, Any]] = []
    for lv in levels:
        if deduped and abs(lv["price"] - deduped[-1]["price"]) / max(lv["price"], 1.0) < 0.0015:
            continue
        deduped.append(lv)
    return deduped


def check_macro_blackout(
    calendar: list[dict[str, Any]],
    blackout_minutes: float,
    regime_score: float,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Section 6: No entries within 30 min of major scheduled macro releases unless strongly aligned (size halved)."""
    near = [ev for ev in calendar if abs(ev.get("minutes_away", 9999)) <= blackout_minutes]
    if not near:
        return {"in_blackout": False, "halve_size": False, "blocked": False, "event": None}
    ev = near[0]
    strong_long = cfg["regime"]["strong_alignment_long"]
    strong_short = cfg["regime"]["strong_alignment_short"]
    strongly_aligned = regime_score >= strong_long or regime_score <= strong_short
    if strongly_aligned:
        return {
            "in_blackout": True,
            "halve_size": True,
            "blocked": False,
            "event": ev,
            "note": f"Within ±{blackout_minutes}m of {ev['title']} — strongly aligned ({regime_score:.1f}), size halved",
        }
    return {
        "in_blackout": True,
        "halve_size": False,
        "blocked": True,
        "event": ev,
        "note": f"Blocked: within ±{blackout_minutes}m of {ev['title']} ({ev['minutes_away']:+.1f}m) and score {regime_score:.1f} not strongly aligned",
    }


def calculate_position_sizing(
    equity: float,
    entry: float,
    stop: float,
    risk_pct: float,
    max_leverage: float = 2.0,
) -> dict[str, Any]:
    """Section 5: Risk-based BTC sizing with hard 1:2 maximum leverage cap."""
    stop_dist = abs(entry - stop)
    if equity <= 0 or entry <= 0 or stop_dist <= 0:
        return {"valid": False, "reason": "Invalid equity/entry/stop"}
    risk_usd_target = equity * risk_pct
    raw_btc = risk_usd_target / stop_dist
    max_notional = equity * max_leverage
    max_btc = max_notional / entry
    leverage_capped = raw_btc > max_btc
    size_btc = min(raw_btc, max_btc)
    notional = size_btc * entry
    actual_risk_usd = size_btc * stop_dist
    actual_risk_pct = actual_risk_usd / equity
    return {
        "valid": True,
        "size_btc": round(size_btc, 6),
        "notional_usd": round(notional, 2),
        "leverage": round(notional / equity, 3),
        "leverage_capped": leverage_capped,
        "target_risk_pct": round(risk_pct * 100.0, 4),
        "actual_risk_pct": round(actual_risk_pct * 100.0, 4),
        "actual_risk_usd": round(actual_risk_usd, 2),
        "stop_distance_usd": round(stop_dist, 2),
        "stop_distance_pct": round(stop_dist / entry * 100.0, 3),
    }


def evaluate_signal(
    market_data: dict[str, Any],
    regime: dict[str, Any],
    ledger_state: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate all 7 qualification criteria and output LONG, SHORT, or FLAT signal."""
    price = market_data["ticker"].get("price")
    h4 = market_data["klines"]["4h"]
    d1 = market_data["klines"]["1d"]
    levels = identify_structural_levels(market_data)

    if not price or not regime.get("ok") or len(h4) < 30:
        return {
            "status": "FLAT",
            "direction": None,
            "price": price,
            "structural_levels": levels,
            "checklist": [],
            "rejection_reasons": ["Insufficient market/regime data to evaluate signal."],
            "proposal": None,
        }

    score = regime["score"]
    bias = regime["bias"]
    open_positions = ledger_state.get("open_positions") or []
    equity = float(ledger_state.get("equity") or cfg["account"]["initial_equity_usd"])
    breakers = ledger_state.get("circuit_breakers") or {}
    dd_tier1 = bool(breakers.get("dd_tier1_active"))

    # Determine candidate direction (or neutral continuation if high-conviction position already open)
    candidate_dir: str | None = None
    is_neutral_continuation = False
    if bias == "LONG_ELIGIBLE":
        candidate_dir = "LONG"
    elif bias == "SHORT_ELIGIBLE":
        candidate_dir = "SHORT"
    elif open_positions:
        existing_dir = open_positions[0]["direction"]
        if existing_dir == "LONG" and score >= cfg["regime"]["neutral_high_conviction_long"]:
            candidate_dir = "LONG"
            is_neutral_continuation = True
        elif existing_dir == "SHORT" and score <= cfg["regime"]["neutral_high_conviction_short"]:
            candidate_dir = "SHORT"
            is_neutral_continuation = True

    rejections: list[str] = []
    checklist: list[dict[str, Any]] = []

    # 1. Regime threshold check
    c1_pass = candidate_dir is not None
    th_long = regime["thresholds"]["long"]
    th_short = regime["thresholds"]["short"]
    c1_detail = (
        f"Score {score:.1f} meets {candidate_dir} threshold"
        + (" (0.5x neutral continuation)" if is_neutral_continuation else "")
        if c1_pass
        else f"Score {score:.1f} in Neutral Zone ({th_short:.0f}–{th_long:.0f}); no directional edge"
    )
    checklist.append({"id": 1, "rule": "Regime Score Threshold", "passed": c1_pass, "detail": c1_detail})
    if not c1_pass:
        rejections.append(c1_detail)

    # 2. Interaction with higher-timeframe structural level
    atr_4h = atr(h4, 14) or (price * 0.015)
    prox_limit = min(
        atr_4h * cfg["qualification"]["level_proximity_atr_mult"],
        price * cfg["qualification"]["level_proximity_max_pct"],
    )
    nearest_level = min(levels, key=lambda l: abs(l["price"] - price)) if levels else None
    level_dist = abs(nearest_level["price"] - price) if nearest_level else float("inf")
    c2_pass = nearest_level is not None and level_dist <= prox_limit
    c2_detail = (
        f"Near {nearest_level['label']} ({nearest_level['price']:,.1f}, dist ${level_dist:,.0f} <= ${prox_limit:,.0f})"
        if c2_pass and nearest_level
        else (
            f"Nearest level {nearest_level['label']} ({nearest_level['price']:,.1f}) is ${level_dist:,.0f} away (band ±${prox_limit:,.0f})"
            if nearest_level
            else "No structural levels identified"
        )
    )
    checklist.append({"id": 2, "rule": "HTF Structural Level Interaction", "passed": c2_pass, "detail": c2_detail})
    if not c2_pass:
        rejections.append(c2_detail)

    # 3. Execution-timeframe confirmation (4H)
    eval_dir = candidate_dir or ("LONG" if score >= 50.0 else "SHORT")
    conf = detect_execution_confirmation(
        h4,
        eval_dir,
        nearest_level["price"] if nearest_level else None,
        min_wick_ratio=cfg["qualification"]["min_rejection_wick_ratio"],
        min_vol_ratio=cfg["qualification"]["min_confirm_volume_ratio"],
    )
    c3_pass = bool(conf["confirmed"]) and c1_pass
    c3_detail = conf.get("detail") if conf["confirmed"] else conf.get("reason", "No 4H confirmation")
    checklist.append({"id": 3, "rule": "4H Execution Confirmation", "passed": c3_pass, "detail": c3_detail})
    if not c3_pass:
        rejections.append(c3_detail)

    # Compute Stop, Target & R:R (Sections 4, 7, 9)
    h4_hi, h4_lo = swing_pivots(h4[-80:], left=2, right=2)
    stop_buf_pct = cfg["qualification"]["swing_stop_buffer_pct"]
    atr_buf = atr_4h * cfg["qualification"]["atr_stop_buffer_mult"]
    max_stop_pct = cfg["leverage_and_risk"]["max_stop_distance_pct"]

    entry_price = (
        round(nearest_level["price"], 1)
        if (nearest_level and conf.get("type") == "REJECTION_CANDLE")
        else round(price, 1)
    )
    entry_method = "LIMIT_AT_LEVEL" if conf.get("type") != "STRUCTURE_BREAK" else "MARKET_AFTER_BOS"

    if eval_dir == "LONG":
        swing_candidates = [s["price"] * (1.0 - stop_buf_pct) for s in h4_lo if s["price"] < entry_price]
        swing_stop = max(swing_candidates) if swing_candidates else (entry_price - atr_buf)
        atr_stop = entry_price - atr_buf
        # "whichever produces the tighter valid stop" -> higher price below entry is tighter
        stop_price = round(max(swing_stop, atr_stop), 1)
        if stop_price >= entry_price * 0.996:
            stop_price = round(atr_stop, 1)
        targets_above = sorted([l for l in levels if l["price"] > entry_price * 1.005], key=lambda x: x["price"])
        target1 = targets_above[0]["price"] if targets_above else round(entry_price + 2.2 * abs(entry_price - stop_price), 1)
        target1_label = targets_above[0]["label"] if targets_above else "Projected 2.2R Extension"
    else:
        swing_candidates = [s["price"] * (1.0 + stop_buf_pct) for s in h4_hi if s["price"] > entry_price]
        swing_stop = min(swing_candidates) if swing_candidates else (entry_price + atr_buf)
        atr_stop = entry_price + atr_buf
        # lower price above entry is tighter
        stop_price = round(min(swing_stop, atr_stop), 1)
        if stop_price <= entry_price * 1.004:
            stop_price = round(atr_stop, 1)
        targets_below = sorted([l for l in levels if l["price"] < entry_price * 0.995], key=lambda x: x["price"], reverse=True)
        target1 = targets_below[0]["price"] if targets_below else round(entry_price - 2.2 * abs(stop_price - entry_price), 1)
        target1_label = targets_below[0]["label"] if targets_below else "Projected 2.2R Extension"

    stop_dist = abs(entry_price - stop_price)
    stop_dist_pct = stop_dist / entry_price if entry_price > 0 else 1.0
    reward_dist = abs(target1 - entry_price)
    raw_rr = round(reward_dist / stop_dist, 2) if stop_dist > 0 else 0.0

    # Section 9: High funding rate awareness (degrading R:R over expected hold)
    fund_8h_pct = (market_data.get("derivatives") or {}).get("current_rate_pct") or 0.0
    hold_days = cfg["leverage_and_risk"]["expected_hold_days_for_funding"]
    intervals = hold_days * 3.0  # 3 x 8h per day
    # Positive funding paid by LONG, received by SHORT
    funding_drag_pct = (fund_8h_pct / 100.0) * intervals if eval_dir == "LONG" else -(fund_8h_pct / 100.0) * intervals
    funding_drag_pct = max(0.0, funding_drag_pct)  # only penalize adverse net funding cost
    adj_reward_pct = max(0.0, (reward_dist / entry_price) - funding_drag_pct)
    adj_rr = round(adj_reward_pct / stop_dist_pct, 2) if stop_dist_pct > 0 else 0.0

    min_rr = cfg["leverage_and_risk"]["min_rr"]
    stop_valid = stop_dist_pct <= max_stop_pct
    c4_pass = stop_valid and raw_rr >= min_rr and adj_rr >= min_rr
    if not stop_valid:
        c4_detail = f"Disqualified: stop distance {stop_dist_pct*100:.2f}% exceeds {max_stop_pct*100:.1f}% max"
    elif raw_rr < min_rr:
        c4_detail = f"R:R {raw_rr:.2f}:1 to {target1_label} ({target1:,.1f}) < {min_rr:.1f}:1 minimum"
    elif adj_rr < min_rr:
        c4_detail = f"Funding-adjusted R:R {adj_rr:.2f}:1 < {min_rr:.1f}:1 (raw {raw_rr:.2f}:1, funding drag {funding_drag_pct*100:.2f}%)"
    else:
        c4_detail = f"R:R {raw_rr:.2f}:1 (funding-adj {adj_rr:.2f}:1) to {target1_label} ({target1:,.1f}); stop {stop_dist_pct*100:.2f}% <= 4.0%"
    checklist.append({"id": 4, "rule": "R:R ≥ 1.8:1 & Stop ≤ 4%", "passed": c4_pass, "detail": c4_detail})
    if not c4_pass:
        rejections.append(c4_detail)

    # 5. No opposing position open + slot availability (max 1 primary + 1 satellite)
    opposing = any(p["direction"] != eval_dir for p in open_positions)
    has_primary = any(p.get("role", "primary") == "primary" for p in open_positions)
    has_satellite = any(p.get("role") == "satellite" for p in open_positions)
    slot_role = "primary" if not has_primary else ("satellite" if not has_satellite else None)
    c5_pass = (not opposing) and (slot_role is not None)
    if opposing:
        c5_detail = f"Opposing {open_positions[0]['direction']} position already open"
    elif slot_role is None:
        c5_detail = "Max concurrent positions reached (1 primary + 1 satellite open)"
    else:
        c5_detail = f"No opposing position; {slot_role} slot available"
    checklist.append({"id": 5, "rule": "No Opposing Position & Slot Free", "passed": c5_pass, "detail": c5_detail})
    if not c5_pass:
        rejections.append(c5_detail)

    # 6. Portfolio heat <= 2% after proposed trade
    base_risk_pct = (
        cfg["leverage_and_risk"]["satellite_risk_pct"]
        if slot_role == "satellite"
        else (cfg["circuit_breakers"]["drawdown_tier1_risk_pct"] if dd_tier1 else cfg["leverage_and_risk"]["risk_per_trade_pct"])
    )
    if is_neutral_continuation:
        base_risk_pct *= cfg["regime"]["neutral_continuation_size_mult"]

    # Macro blackout check (Section 6)
    macro_chk = check_macro_blackout(
        market_data.get("macro_calendar") or [],
        cfg["leverage_and_risk"]["macro_blackout_minutes"],
        score,
        cfg,
    )
    if macro_chk["halve_size"]:
        base_risk_pct *= 0.5

    sizing = calculate_position_sizing(
        equity=equity,
        entry=entry_price,
        stop=stop_price,
        risk_pct=base_risk_pct,
        max_leverage=cfg["leverage_and_risk"]["max_leverage"],
    )
    current_heat_pct = sum(float(p.get("risk_pct", 0.0)) for p in open_positions)
    proposed_heat_pct = current_heat_pct + (sizing.get("actual_risk_pct", 0.0) if sizing.get("valid") else 0.0)
    max_heat = cfg["leverage_and_risk"]["max_portfolio_heat_pct"] * 100.0
    c6_pass = bool(sizing.get("valid")) and proposed_heat_pct <= max_heat + 1e-9
    c6_detail = f"Post-trade heat {proposed_heat_pct:.2f}% <= {max_heat:.2f}% max (open {current_heat_pct:.2f}%)"
    checklist.append({"id": 6, "rule": "Portfolio Heat ≤ 2.0%", "passed": c6_pass, "detail": c6_detail})
    if not c6_pass:
        rejections.append(c6_detail)

    # 7. Circuit breakers & macro blackout
    cb_active_reasons: list[str] = []
    if breakers.get("daily_halted"):
        cb_active_reasons.append("Daily -1.5% loss limit active")
    if breakers.get("weekly_halted"):
        cb_active_reasons.append("Weekly -3.0% loss limit active")
    if breakers.get("dd_tier2_locked"):
        cb_active_reasons.append("-12% Drawdown halt active (process review required)")
    if macro_chk["blocked"]:
        cb_active_reasons.append(macro_chk["note"])

    c7_pass = len(cb_active_reasons) == 0
    c7_detail = "; ".join(cb_active_reasons) if cb_active_reasons else (macro_chk.get("note") or "All circuit breakers clear")
    checklist.append({"id": 7, "rule": "Circuit Breakers & Macro Gate", "passed": c7_pass, "detail": c7_detail})
    if not c7_pass:
        rejections.append(c7_detail)

    all_pass = all(c["passed"] for c in checklist)
    status = candidate_dir if (all_pass and candidate_dir) else "FLAT"

    proposal = {
        "direction": eval_dir,
        "role": slot_role or "primary",
        "entry_method": entry_method,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target1_price": target1,
        "target1_label": target1_label,
        "raw_rr": raw_rr,
        "funding_adjusted_rr": adj_rr,
        "funding_drag_pct": round(funding_drag_pct * 100.0, 3),
        "level_label": nearest_level["label"] if nearest_level else None,
        "level_price": nearest_level["price"] if nearest_level else None,
        "confirmation_type": conf.get("type"),
        "macro_halved": macro_chk["halve_size"],
        "neutral_continuation": is_neutral_continuation,
        **sizing,
    }

    return {
        "status": status,
        "direction": status if status in ("LONG", "SHORT") else None,
        "price": round(price, 1),
        "atr_4h": round(atr_4h, 1),
        "structural_levels": levels,
        "checklist": checklist,
        "rejection_reasons": [] if status != "FLAT" else rejections,
        "proposal": proposal,
        "macro_blackout": macro_chk,
    }
