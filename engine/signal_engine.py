"""9-Point Futures Qualification, Sell Inventory & Sizing Engine (v4.0 Sections 2, 3, 5, 6)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from .indicators import atr, detect_execution_confirmation, swing_pivots, volume_profile


def identify_structural_levels(market_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract 4H and daily structural levels from closed candles."""
    d1 = market_data["klines"]["1d"]
    h4 = market_data["klines"]["4h"]
    levels: list[dict[str, Any]] = []
    if not d1 or not h4:
        return levels

    last_d = d1[-1]
    levels.append({"price": round(last_d["high"], 1), "label": "Prior Daily High", "kind": "resistance"})
    levels.append({"price": round(last_d["low"], 1), "label": "Prior Daily Low", "kind": "support"})
    levels.append({"price": round(last_d["open"], 1), "label": "Daily Open", "kind": "pivot"})

    last_4h = h4[-1]
    levels.append({"price": round(last_4h["high"], 1), "label": "Prior 4H High", "kind": "resistance"})
    levels.append({"price": round(last_4h["low"], 1), "label": "Prior 4H Low", "kind": "support"})

    if len(d1) >= 8:
        latest_dt = dt.datetime.fromtimestamp(last_d["ts"] / 1000.0, tz=dt.timezone.utc)
        week_start_idx = max(0, len(d1) - 1 - latest_dt.weekday())
        levels.append({"price": round(d1[week_start_idx]["open"], 1), "label": "Weekly Open", "kind": "pivot"})

    h4_hi, h4_lo = swing_pivots(h4[-120:], left=3, right=3)
    for idx, sh in enumerate(h4_hi[-3:], 1):
        levels.append({"price": round(sh["price"], 1), "label": f"4H Swing High #{idx}", "kind": "resistance"})
    for idx, sl in enumerate(h4_lo[-3:], 1):
        levels.append({"price": round(sl["price"], 1), "label": f"4H Swing Low #{idx}", "kind": "support"})

    vp = volume_profile(d1[-30:], bin_width=100.0)
    if vp:
        levels.append({"price": vp["poc"], "label": "30D VPOC", "kind": "volume"})
        levels.append({"price": vp["vah"], "label": "30D VAH", "kind": "volume"})
        levels.append({"price": vp["val"], "label": "30D VAL", "kind": "volume"})

    levels.sort(key=lambda x: x["price"])
    deduped: list[dict[str, Any]] = []
    for lv in levels:
        if deduped and abs(lv["price"] - deduped[-1]["price"]) / max(lv["price"], 1.0) < 0.0012:
            continue
        deduped.append(lv)
    return deduped


def check_macro_release_window(calendar: list[dict[str, Any]], blackout_minutes: float) -> dict[str, Any]:
    """Section 5 Rule 9: No major release inside the next 60 minutes."""
    upcoming = [
        ev
        for ev in calendar
        if 0.0 <= float(ev.get("minutes_away", 9999)) <= blackout_minutes
    ]
    if not upcoming:
        return {"blocked": False, "event": None, "note": f"No major release inside next {int(blackout_minutes)}m"}
    ev = upcoming[0]
    return {
        "blocked": True,
        "event": ev,
        "note": f"Blocked: {ev['title']} in {ev['minutes_away']:.0f}m (≤ {int(blackout_minutes)}m rule)",
    }


def calculate_position_sizing(
    equity: float,
    entry: float,
    stop: float,
    risk_pct: float,
    max_leverage: float = 2.0,
) -> dict[str, Any]:
    """Section 6: Risk-based BTC sizing with hard 1:2 leverage cap."""
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
    """Evaluate 9-point futures checklist + Sell Inventory option per Version 4.0."""
    price = market_data["ticker"].get("price")
    h4 = market_data["klines"]["4h"]
    levels = identify_structural_levels(market_data)

    if not price or not regime.get("ok") or len(h4) < 30:
        return {
            "status": "FLAT",
            "primary_futures_signal": "FLAT",
            "active_signals": ["FLAT"],
            "direction": None,
            "price": price,
            "structural_levels": levels,
            "checklist": [],
            "rejection_reasons": ["Insufficient 4H/1D data to evaluate Version 4.0 signal."],
            "proposal": None,
            "sell_inventory": {"active": False, "reason": "Insufficient data"},
        }

    score = regime["score"]
    bias = regime["bias"]
    daily_bias = regime.get("daily_bias", "NEUTRAL")
    is_weekend = bool(regime.get("is_weekend_utc"))
    open_positions = ledger_state.get("open_positions") or []
    equity = float(ledger_state.get("equity") or cfg["account"]["initial_equity_usd"])
    breakers = ledger_state.get("breakers") or ledger_state.get("circuit_breakers") or {}
    dd_tier1 = bool(breakers.get("dd_tier1_active"))

    th_long = regime["thresholds"]["long"]
    th_short = regime["thresholds"]["short"]
    wk_long = regime["thresholds"]["weekend_long"]
    wk_short = regime["thresholds"]["weekend_short"]

    candidate_dir = bias if bias in ("LONG", "SHORT") else None
    eval_dir = candidate_dir or ("LONG" if score >= 50.0 else "SHORT")

    rejections: list[str] = []
    checklist: list[dict[str, Any]] = []

    # Rule 1: Regime score meets threshold (and weekend extreme check: >=80 / <=20)
    if candidate_dir is None:
        c1_pass = False
        c1_detail = f"Score {score:.1f} in Flat Zone ({th_short:.0f}–{th_long:.0f}); no exceptions"
    elif is_weekend and ((candidate_dir == "LONG" and score < wk_long) or (candidate_dir == "SHORT" and score > wk_short)):
        c1_pass = False
        c1_detail = f"Weekend UTC requires extreme score (≥{wk_long:.0f}/≤{wk_short:.0f}); current {score:.1f}"
    else:
        c1_pass = True
        c1_detail = f"Score {score:.1f} meets {candidate_dir} threshold" + (" (Weekend extreme 0.5x size)" if is_weekend else "")
    checklist.append({"id": 1, "rule": "Regime Score Meets Threshold", "passed": c1_pass, "detail": c1_detail})
    if not c1_pass:
        rejections.append(c1_detail)

    # Rule 2: Price at relevant 4H structural level aligned with daily bias
    atr_4h = atr(h4, 14) or (price * 0.012)
    prox_limit = min(
        atr_4h * cfg["qualification"]["level_proximity_atr_mult"],
        price * cfg["qualification"]["level_proximity_max_pct"],
    )
    nearest_level = min(levels, key=lambda l: abs(l["price"] - price)) if levels else None
    level_dist = abs(nearest_level["price"] - price) if nearest_level else float("inf")
    daily_aligned = (
        (eval_dir == "LONG" and daily_bias != "BEAR")
        or (eval_dir == "SHORT" and daily_bias != "BULL")
    )
    at_level = nearest_level is not None and level_dist <= prox_limit
    c2_pass = at_level and daily_aligned
    if not daily_aligned:
        c2_detail = f"Direction {eval_dir} opposes Daily Bias ({daily_bias})"
    elif not at_level:
        c2_detail = (
            f"Nearest 4H level {nearest_level['label']} ({nearest_level['price']:,.1f}) is ${level_dist:,.0f} away (band ±${prox_limit:,.0f})"
            if nearest_level
            else "No 4H structural level found"
        )
    else:
        c2_detail = f"At {nearest_level['label']} ({nearest_level['price']:,.1f}, dist ${level_dist:,.0f}) aligned w/ Daily {daily_bias}"
    checklist.append({"id": 2, "rule": "4H Level Aligned w/ Daily Bias", "passed": c2_pass, "detail": c2_detail})
    if not c2_pass:
        rejections.append(c2_detail)

    # Rule 3: 4H confirmation (structure break or rejection + volume)
    conf = detect_execution_confirmation(
        h4,
        eval_dir,
        nearest_level["price"] if nearest_level else None,
        min_wick_ratio=cfg["qualification"]["min_rejection_wick_ratio"],
        min_vol_ratio=cfg["qualification"]["min_confirm_volume_ratio"],
    )
    c3_pass = bool(conf["confirmed"]) and c1_pass
    c3_detail = conf.get("detail") if conf["confirmed"] else conf.get("reason", "No 4H confirmation")
    checklist.append({"id": 3, "rule": "4H Confirmation (BOS / Rejection+Vol)", "passed": c3_pass, "detail": c3_detail})
    if not c3_pass:
        rejections.append(c3_detail)

    # Compute Stop, Target & R:R (Rules 4 & 5)
    h4_hi, h4_lo = swing_pivots(h4[-80:], left=2, right=2)
    stop_buf_pct = cfg["qualification"]["swing_stop_buffer_pct"]
    atr_buf = atr_4h * cfg["qualification"]["atr_stop_buffer_mult"]
    max_stop_pct = cfg["leverage_and_risk"]["max_stop_distance_pct"]  # 2.2%

    entry_price = (
        round(nearest_level["price"], 1)
        if (nearest_level and conf.get("type") == "REJECTION_CANDLE")
        else round(price, 1)
    )
    entry_method = "LIMIT_AT_LEVEL" if conf.get("type") != "STRUCTURE_BREAK" else "MARKET_AFTER_BOS"

    if eval_dir == "LONG":
        swing_cands = [s["price"] * (1.0 - stop_buf_pct) for s in h4_lo if s["price"] < entry_price]
        swing_stop = max(swing_cands) if swing_cands else (entry_price - atr_buf)
        atr_stop = entry_price - atr_buf
        stop_price = round(max(swing_stop, atr_stop), 1)
        if stop_price >= entry_price * 0.997:
            stop_price = round(atr_stop, 1)
        targets = sorted([l for l in levels if l["price"] > entry_price * 1.004], key=lambda x: x["price"])
        target1 = targets[0]["price"] if targets else round(entry_price + 2.0 * abs(entry_price - stop_price), 1)
        target1_label = targets[0]["label"] if targets else "Projected 2.0R Target"
    else:
        swing_cands = [s["price"] * (1.0 + stop_buf_pct) for s in h4_hi if s["price"] > entry_price]
        swing_stop = min(swing_cands) if swing_cands else (entry_price + atr_buf)
        atr_stop = entry_price + atr_buf
        stop_price = round(min(swing_stop, atr_stop), 1)
        if stop_price <= entry_price * 1.003:
            stop_price = round(atr_stop, 1)
        targets = sorted([l for l in levels if l["price"] < entry_price * 0.996], key=lambda x: x["price"], reverse=True)
        target1 = targets[0]["price"] if targets else round(entry_price - 2.0 * abs(stop_price - entry_price), 1)
        target1_label = targets[0]["label"] if targets else "Projected 2.0R Target"

    stop_dist = abs(entry_price - stop_price)
    stop_dist_pct = stop_dist / entry_price if entry_price > 0 else 1.0
    reward_dist = abs(target1 - entry_price)
    raw_rr = round(reward_dist / stop_dist, 2) if stop_dist > 0 else 0.0

    fund_8h_pct = (market_data.get("derivatives") or {}).get("current_rate_pct") or 0.0
    intervals = cfg["leverage_and_risk"]["expected_hold_hours_for_funding"] / 8.0  # 24h -> 3 intervals
    funding_drag_pct = max(
        0.0,
        ((fund_8h_pct / 100.0) * intervals) if eval_dir == "LONG" else (-(fund_8h_pct / 100.0) * intervals),
    )
    adj_reward_pct = max(0.0, (reward_dist / entry_price) - funding_drag_pct)
    adj_rr = round(adj_reward_pct / stop_dist_pct, 2) if stop_dist_pct > 0 else 0.0

    min_rr = cfg["leverage_and_risk"]["min_rr"]  # 1.6

    # Rule 4: Risk-reward >= 1.6 : 1
    c4_pass = raw_rr >= min_rr and adj_rr >= min_rr
    c4_detail = (
        f"R:R {raw_rr:.2f}:1 (funding-adj {adj_rr:.2f}:1) to {target1_label} ({target1:,.1f}) ≥ {min_rr:.1f}:1"
        if c4_pass
        else f"R:R {raw_rr:.2f}:1 (adj {adj_rr:.2f}:1) to {target1_label} ({target1:,.1f}) < {min_rr:.1f}:1 min"
    )
    checklist.append({"id": 4, "rule": "Risk-Reward ≥ 1.6 : 1", "passed": c4_pass, "detail": c4_detail})
    if not c4_pass:
        rejections.append(c4_detail)

    # Rule 5: Stop distance <= 2.2%
    c5_pass = stop_dist_pct <= max_stop_pct
    c5_detail = (
        f"Stop distance {stop_dist_pct*100:.2f}% ≤ {max_stop_pct*100:.1f}% max"
        if c5_pass
        else f"Stop distance {stop_dist_pct*100:.2f}% exceeds {max_stop_pct*100:.1f}% max"
    )
    checklist.append({"id": 5, "rule": "Stop Distance ≤ 2.2%", "passed": c5_pass, "detail": c5_detail})
    if not c5_pass:
        rejections.append(c5_detail)

    # Rule 6: No opposing futures position open (and max 1 futures position)
    opposing = any(p["direction"] != eval_dir for p in open_positions)
    already_open = len(open_positions) >= cfg["leverage_and_risk"]["max_concurrent_futures"]
    c6_pass = (not opposing) and (not already_open)
    if opposing:
        c6_detail = f"Opposing {open_positions[0]['direction']} futures position open"
    elif already_open:
        c6_detail = "Maximum 1 concurrent futures position already open"
    else:
        c6_detail = "No open/opposing futures position"
    checklist.append({"id": 6, "rule": "No Opposing / Max 1 Futures", "passed": c6_pass, "detail": c6_detail})
    if not c6_pass:
        rejections.append(c6_detail)

    # Rule 7: Portfolio heat after trade <= 1.5% of equity
    base_risk_pct = (
        cfg["circuit_breakers"]["drawdown_tier1_risk_pct"]
        if dd_tier1
        else cfg["leverage_and_risk"]["risk_per_trade_pct"]
    )
    if is_weekend:
        base_risk_pct *= cfg["timeframe_and_hold"]["weekend_size_mult"]

    sizing = calculate_position_sizing(
        equity=equity,
        entry=entry_price,
        stop=stop_price,
        risk_pct=base_risk_pct,
        max_leverage=cfg["leverage_and_risk"]["max_leverage"],
    )
    current_heat_pct = sum(float(p.get("risk_pct", 0.0)) for p in open_positions)
    post_heat_pct = current_heat_pct + (sizing.get("actual_risk_pct", 0.0) if sizing.get("valid") else 0.0)
    max_heat_pct = cfg["leverage_and_risk"]["max_portfolio_heat_pct"] * 100.0
    c7_pass = bool(sizing.get("valid")) and post_heat_pct <= max_heat_pct + 1e-9
    c7_detail = f"Post-trade heat {post_heat_pct:.2f}% ≤ {max_heat_pct:.2f}% max"
    checklist.append({"id": 7, "rule": "Portfolio Heat ≤ 1.5%", "passed": c7_pass, "detail": c7_detail})
    if not c7_pass:
        rejections.append(c7_detail)

    # Rule 8: No circuit breaker active
    cb_reasons: list[str] = []
    if breakers.get("intraday_halted"):
        cb_reasons.append("Intraday -1.2% loss halt")
    if breakers.get("daily_halted"):
        cb_reasons.append("Daily -2.0% loss halt")
    if breakers.get("weekly_halted"):
        cb_reasons.append("Weekly -4.0% loss halt")
    if breakers.get("dd_tier2_locked"):
        cb_reasons.append("-10.0% DD halt (review required)")
    c8_pass = len(cb_reasons) == 0
    c8_detail = "; ".join(cb_reasons) if cb_reasons else "All circuit breakers clear"
    checklist.append({"id": 8, "rule": "No Circuit Breaker Active", "passed": c8_pass, "detail": c8_detail})
    if not c8_pass:
        rejections.append(c8_detail)

    # Rule 9: No major release inside the next 60 minutes
    macro_chk = check_macro_release_window(
        market_data.get("macro_calendar") or [],
        cfg["leverage_and_risk"]["macro_blackout_minutes"],
    )
    c9_pass = not macro_chk["blocked"]
    c9_detail = macro_chk["note"]
    checklist.append({"id": 9, "rule": "No Major Release ≤ 60m", "passed": c9_pass, "detail": c9_detail})
    if not c9_pass:
        rejections.append(c9_detail)

    all_futures_pass = all(c["passed"] for c in checklist)
    futures_status = candidate_dir if (all_futures_pass and candidate_dir) else "FLAT"

    # Sell Inventory (Section 2 & 5): requires ONLY score <= short_th and a 4H structural reference
    spot_inv_btc = float(cfg["account"].get("spot_inventory_btc", 0.0))
    inv_pct = float(cfg["inventory"]["default_sell_pct"])
    inv_active = (score <= th_short) and (nearest_level is not None)
    # Note: Even under weekly/intraday/daily futures halts, Sell Inventory remains allowed (Section 8)
    sell_btc = round(spot_inv_btc * inv_pct, 6) if inv_active else 0.0
    sell_usd = round(sell_btc * price, 2) if inv_active else 0.0
    sell_inventory = {
        "active": inv_active,
        "recommended_pct": round(inv_pct * 100.0, 1),
        "band_pct": f"{cfg['inventory']['min_sell_pct']*100:.0f}–{cfg['inventory']['max_sell_pct']*100:.0f}%",
        "spot_inventory_btc": spot_inv_btc,
        "sell_btc": sell_btc,
        "sell_usd": sell_usd,
        "structural_ref": f"{nearest_level['label']} @ {nearest_level['price']:,.1f}" if nearest_level else None,
        "counts_toward_heat": False,
        "reason": (
            f"Score {score:.1f} ≤ {th_short:.0f} w/ 4H ref {nearest_level['label']} ({nearest_level['price']:,.1f}) — reduce {inv_pct*100:.0f}% spot inventory"
            if inv_active
            else f"Hold spot inventory (requires score ≤ {th_short:.0f}; current {score:.1f})"
        ),
    }

    active_signals: list[str] = []
    if futures_status in ("LONG", "SHORT"):
        active_signals.append(futures_status)
    if inv_active:
        active_signals.append("SELL_INVENTORY")
    if not active_signals:
        active_signals.append("FLAT")

    proposal = {
        "direction": eval_dir,
        "entry_method": entry_method,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target1_price": target1,
        "target1_label": target1_label,
        "raw_rr": raw_rr,
        "funding_adjusted_rr": adj_rr,
        "level_label": nearest_level["label"] if nearest_level else None,
        "level_price": nearest_level["price"] if nearest_level else None,
        "confirmation_type": conf.get("type"),
        "weekend_halved": is_weekend,
        **sizing,
    }

    return {
        "status": futures_status,
        "primary_futures_signal": futures_status,
        "active_signals": active_signals,
        "direction": futures_status if futures_status in ("LONG", "SHORT") else None,
        "price": round(price, 1),
        "atr_4h": round(atr_4h, 1),
        "structural_levels": levels,
        "checklist": checklist,
        "rejection_reasons": [] if futures_status != "FLAT" else rejections,
        "proposal": proposal,
        "sell_inventory": sell_inventory,
        "macro_blackout": macro_chk,
    }
