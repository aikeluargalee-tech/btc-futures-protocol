"""BTC State of Regime (5-State + Modifiers), Layer-1 10 Kline Primitives,
and Layer-2 Symmetrical 11-Pattern Microstructure Playbook (cortex_11p_raw_telemetry_v1).

Follows the Strict Zero-Fabrication / Missing-Data Rule: unverified metrics output
None (`null` in JSON) or `"UNAVAILABLE"` rather than placeholder/interpolated values.
"""
from __future__ import annotations

from typing import Any

from .indicators import (
    anchored_vwap,
    atr,
    awesome_oscillator_series,
    rsi_series,
    sma,
    swing_pivots,
    volume_profile,
)

UNAVAILABLE = "UNAVAILABLE"

REGIME_CATALOG = [
    ("R1", "R1_EXPANSION_BULL", "Expansion (Bull Trend)", "BULLISH", "Price > 4H EMA20 > EMA50, RSI 50–72, Spot/volume participation"),
    ("R2", "R2_FRAGILE_OVEREXTENDED", "Fragile / Overextended", "OVEREXTENDED", "Stretched price above EMA20, RSI > 72 or Perp/funding crowding"),
    ("R3", "R3_RANGE_COMPRESSION", "Range / Compression", "NEUTRAL", "Rotational equilibrium around 4H EMAs / VPOC or tight range"),
    ("R4", "R4_CASCADE_DELEVERAGING", "Cascade / Deleveraging", "CAPITULATION", "Sharp impulse selloff, ATR > 75th pctile, RSI < 28/29 oversold"),
    ("R5", "R5_DISTRIBUTION_BEAR", "Distribution / Bear", "BEARISH", "Price < 4H EMA50 & 1D structure bearish LH/LL"),
]

KLINE_10_META = [
    ("ENGULFING", "Engulfing Candle", "Reversal"),
    ("PIN_BAR", "Pin Bar / Rejection Wick", "Reversal"),
    ("SFP_SWEEP", "Liquidity Sweep / SFP", "Reversal"),
    ("INSIDE_BAR", "Inside Bar (Coil)", "Consolidation"),
    ("OUTSIDE_BAR", "Outside Bar (Expansion)", "Consolidation"),
    ("MOMENTUM_THRUST", "Momentum Thrust (Marubozu)", "Impulse"),
    ("NR4_NR7", "NR4 / NR7 Range Squeeze", "Volatility"),
    ("TIGHT_COIL_3BAR", "Tight 3-Bar Coil", "Volatility"),
    ("RSI_DIVERGENCE", "RSI(14) Swing Divergence", "Divergence"),
    ("VOLUME_CLIMAX", "Volume Climax / Exhaustion", "Volatility"),
]


def _match_confluence(
    anchor_price: float | None,
    levels: list[dict[str, Any]],
    atr_val: float | None,
) -> tuple[str | None, str]:
    """Check whether a pattern anchor aligns with any known structural S/R or VPOC level."""
    if not anchor_price or not levels:
        return None, "MID_RANGE"
    best: dict[str, Any] | None = None
    best_dist = float("inf")
    for lvl in levels:
        lp = lvl.get("price")
        if not isinstance(lp, (int, float)) or lp <= 0:
            continue
        dist_pct = abs(lp - anchor_price) / anchor_price * 100.0
        dist_atr = abs(lp - anchor_price) / atr_val if (atr_val and atr_val > 0) else 99.0
        if (dist_pct <= 1.0 or dist_atr <= 0.55) and dist_pct < best_dist:
            best_dist = dist_pct
            best = lvl
    if best is None:
        return None, "MID_RANGE"
    return f"{best.get('label')} (${float(best['price']):,.1f})", "STRUCTURAL_CONFLUENCE"


def _detect_kline_10_for_tf(
    candles: list[dict[str, Any]],
    tf_label: str,
    levels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect active Layer-1 10 high-signal crypto patterns on the latest closed bars of one timeframe."""
    if len(candles) < 20:
        return []

    found: list[dict[str, Any]] = []
    c = candles[-1]
    p = candles[-2]
    rng = max(float(c["high"]) - float(c["low"]), 1e-6)
    p_rng = max(float(p["high"]) - float(p["low"]), 1e-6)
    body = abs(float(c["close"]) - float(c["open"]))
    p_body = abs(float(p["close"]) - float(p["open"]))
    upper_wick = float(c["high"]) - max(float(c["open"]), float(c["close"]))
    lower_wick = min(float(c["open"]), float(c["close"])) - float(c["low"])

    atr_val = atr(candles, 14) or rng
    vols = [float(x.get("volume") or 0.0) for x in candles[:-1]]
    vol_sma20 = sma(vols, 20) or sma(vols, min(10, len(vols))) or 0.0
    rel_vol = (float(c.get("volume") or 0.0) / vol_sma20) if vol_sma20 > 0 else 1.0

    def _add(pid: str, name: str, direction: str, detail: str, anchor: float) -> None:
        conf_lvl, conv = _match_confluence(anchor, levels, atr_val)
        found.append(
            {
                "id": pid,
                "name": name,
                "timeframe": tf_label,
                "direction": direction,
                "detail": detail,
                "bar_ts": int(c["ts"]),
                "confluence_level": conf_lvl,
                "conviction": conv,
            }
        )

    # 1. ENGULFING
    c_bull = c["close"] > c["open"]
    p_bull = p["close"] > p["open"]
    if c_bull != p_bull and body > p_body * 1.05:
        c_hi_b, c_lo_b = max(c["open"], c["close"]), min(c["open"], c["close"])
        p_hi_b, p_lo_b = max(p["open"], p["close"]), min(p["open"], p["close"])
        if c_hi_b >= p_hi_b and c_lo_b <= p_lo_b:
            dir_s = "BULLISH" if c_bull else "BEARISH"
            _add("ENGULFING", "Engulfing Candle", dir_s, f"{dir_s.title()} body engulfs prior {tf_label} bar (vol {rel_vol:.2f}x)", c["close"])

    # 2. PIN_BAR
    close_pos = (c["close"] - c["low"]) / rng
    if rng >= 0.45 * atr_val:
        if lower_wick >= max(2.0 * max(body, 1e-6), 0.50 * rng) and close_pos >= 0.62:
            _add("PIN_BAR", "Pin Bar / Hammer", "BULLISH", f"Lower wick {lower_wick / rng * 100:.0f}% of range; close near high", c["low"])
        elif upper_wick >= max(2.0 * max(body, 1e-6), 0.50 * rng) and close_pos <= 0.38:
            _add("PIN_BAR", "Pin Bar / Shooting Star", "BEARISH", f"Upper wick {upper_wick / rng * 100:.0f}% of range; close near low", c["high"])

    # 3. SFP_SWEEP (against prior local highs/lows in window -16:-1)
    prior_win = candles[-16:-1] if len(candles) >= 16 else candles[:-1]
    prior_hi = max(float(x["high"]) for x in prior_win)
    prior_lo = min(float(x["low"]) for x in prior_win)
    if c["low"] < prior_lo and c["close"] > prior_lo:
        _add("SFP_SWEEP", "Bullish Sweep (SFP)", "BULLISH", f"Swept ${prior_lo:,.1f} (wick ${c['low']:,.1f}) & reclaimed ${c['close']:,.1f}", prior_lo)
    if c["high"] > prior_hi and c["close"] < prior_hi:
        _add("SFP_SWEEP", "Bearish Sweep (SFP)", "BEARISH", f"Swept ${prior_hi:,.1f} (wick ${c['high']:,.1f}) & closed ${c['close']:,.1f}", prior_hi)

    # 4. INSIDE_BAR
    if c["high"] <= p["high"] and c["low"] >= p["low"]:
        _add("INSIDE_BAR", "Inside Bar (Coil)", "NEUTRAL", f"Range ${c['low']:,.1f}–${c['high']:,.1f} contained inside prior {tf_label} bar", c["close"])

    # 5. OUTSIDE_BAR
    if c["high"] > p["high"] and c["low"] < p["low"] and p_rng > 0:
        dir_s = "BULLISH" if c_bull else "BEARISH"
        _add("OUTSIDE_BAR", "Outside Bar (Expansion)", dir_s, f"Expanded both sides of prior {tf_label} range (${c['low']:,.1f}–${c['high']:,.1f})", c["close"])

    # 6. MOMENTUM_THRUST
    if body >= 0.68 * rng and rng >= 0.85 * atr_val and rel_vol >= 1.15:
        dir_s = "BULLISH" if c_bull else "BEARISH"
        _add("MOMENTUM_THRUST", "Momentum Thrust (Marubozu)", dir_s, f"Body {body / rng * 100:.0f}% of range on {rel_vol:.2f}x vol", c["close"])

    # 7. NR4_NR7
    last7_rngs = [max(float(x["high"]) - float(x["low"]), 0.0) for x in candles[-7:]]
    if len(last7_rngs) == 7 and rng <= min(last7_rngs) + 1e-6:
        _add("NR4_NR7", "NR7 Squeeze", "NEUTRAL", f"Narrowest {tf_label} range of last 7 bars (${rng:,.1f})", c["close"])
    elif len(last7_rngs) >= 4 and rng <= min(last7_rngs[-4:]) + 1e-6:
        _add("NR4_NR7", "NR4 Squeeze", "NEUTRAL", f"Narrowest {tf_label} range of last 4 bars (${rng:,.1f})", c["close"])

    # 8. TIGHT_COIL_3BAR
    last3 = candles[-3:]
    span3 = max(float(x["high"]) for x in last3) - min(float(x["low"]) for x in last3)
    if all((float(x["high"]) - float(x["low"])) < 0.75 * atr_val for x in last3) and span3 < 1.40 * atr_val:
        _add("TIGHT_COIL_3BAR", "Tight 3-Bar Coil", "NEUTRAL", f"3-bar span ${span3:,.1f} (< 1.4x ATR ${atr_val:,.1f})", c["close"])

    # 9. RSI_DIVERGENCE
    closes = [float(x["close"]) for x in candles]
    rsis = rsi_series(closes, 14)
    offset = len(candles) - len(rsis)
    if rsis:
        shs, sls = swing_pivots(candles[-40:], left=2, right=2)
        base_off = max(0, len(candles) - 40)
        if len(sls) >= 2:
            l1, l2 = sls[-2], sls[-1]
            i1 = base_off + int(l1["idx"]) - offset
            i2 = base_off + int(l2["idx"]) - offset
            if 0 <= i1 < len(rsis) and 0 <= i2 < len(rsis):
                if l2["price"] < l1["price"] * 1.001 and rsis[i2] >= rsis[i1] + 2.0 and (40 - int(l2["idx"])) <= 12:
                    _add("RSI_DIVERGENCE", "RSI Bullish Divergence", "BULLISH", f"Price LL ${l2['price']:,.1f} vs RSI HL ({rsis[i1]:.1f}→{rsis[i2]:.1f})", float(l2["price"]))
        if len(shs) >= 2:
            h1, h2 = shs[-2], shs[-1]
            i1 = base_off + int(h1["idx"]) - offset
            i2 = base_off + int(h2["idx"]) - offset
            if 0 <= i1 < len(rsis) and 0 <= i2 < len(rsis):
                if h2["price"] > h1["price"] * 0.999 and rsis[i2] <= rsis[i1] - 2.0 and (40 - int(h2["idx"])) <= 12:
                    _add("RSI_DIVERGENCE", "RSI Bearish Divergence", "BEARISH", f"Price HH ${h2['price']:,.1f} vs RSI LH ({rsis[i1]:.1f}→{rsis[i2]:.1f})", float(h2["price"]))

    # 10. VOLUME_CLIMAX
    if rel_vol >= 1.85 and rng >= 1.25 * atr_val and max(upper_wick, lower_wick) >= 0.35 * rng:
        dir_s = "BULLISH" if lower_wick > upper_wick else "BEARISH"
        _add("VOLUME_CLIMAX", "Volume Climax / Exhaustion", dir_s, f"Spike {rel_vol:.2f}x vol + ${rng:,.1f} range + exhaustion wick", c["close"])

    return found


def _build_kline_10(
    h1: list[dict[str, Any]],
    h4: list[dict[str, Any]],
    d1: list[dict[str, Any]],
    levels: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run Layer-1 10-pattern detection across 1H, 4H, and 1D closed bars."""
    by_tf = {
        "1h": _detect_kline_10_for_tf(h1, "1H", levels),
        "4h": _detect_kline_10_for_tf(h4, "4H", levels),
        "1d": _detect_kline_10_for_tf(d1, "1D", levels),
    }

    catalog: list[dict[str, Any]] = []
    for pid, name, category in KLINE_10_META:
        hits: list[dict[str, Any]] = []
        for tf_k in ("1d", "4h", "1h"):
            for item in by_tf[tf_k]:
                if item["id"] == pid:
                    hits.append(item)
        top = hits[0] if hits else None
        catalog.append(
            {
                "id": pid,
                "name": name,
                "category": category,
                "active_tfs": [h["timeframe"] for h in hits],
                "direction": top["direction"] if top else "INACTIVE",
                "detail": top["detail"] if top else None,
                "confluence_level": top["confluence_level"] if top else None,
                "conviction": top["conviction"] if top else "INACTIVE",
            }
        )

    return {
        "by_timeframe": by_tf,
        "active_count": sum(len(v) for v in by_tf.values()),
        "catalog_10": catalog,
    }


def _bar_delta_proxy(c: dict[str, Any]) -> float:
    """Directional volume delta proxy when taker_buy_volume is unavailable on a candle."""
    rng = max(float(c["high"]) - float(c["low"]), 1e-6)
    pos = (float(c["close"]) - float(c["open"])) / rng
    return float(c.get("volume") or 0.0) * pos


def _compute_rulebook_3(
    h1: list[dict[str, Any]],
    spot_1h: list[dict[str, Any]],
    deriv: dict[str, Any],
    range_high: float | None,
    poor_highs: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Compute Gate 3 Microstructure Rulebooks R3.1..R3.4 strictly without fabrication."""
    feed_status = {
        "candles": "OK" if len(h1) >= 48 else UNAVAILABLE,
        "cvd": UNAVAILABLE,
        "oi_funding": UNAVAILABLE,
        "frvp": UNAVAILABLE,
        "avwap": UNAVAILABLE,
    }

    # R3.1 Spot vs. Perp CVD across recent swing highs
    r3_1: dict[str, Any] = {
        "spot_cvd_last_two_highs": None,
        "perp_cvd_last_two_highs": None,
        "spot_lag_or_divergence_flag": None,
    }
    if len(spot_1h) >= 40 and all(c.get("taker_buy_volume") is not None for c in spot_1h[-40:]):
        feed_status["cvd"] = "OK"
        spot_cvd: list[float] = []
        acc_s = 0.0
        for c in spot_1h[-48:]:
            tb = float(c["taker_buy_volume"])
            vol = float(c["volume"])
            acc_s += 2.0 * tb - vol
            spot_cvd.append(round(acc_s, 1))

        # Align perp proxy series to matching h1 tail
        perp_tail = h1[-len(spot_cvd) :] if len(h1) >= len(spot_cvd) else spot_1h[-len(spot_cvd) :]
        perp_cvd: list[float] = []
        acc_p = 0.0
        for c in perp_tail:
            acc_p += _bar_delta_proxy(c)
            perp_cvd.append(round(acc_p, 1))

        shs, _ = swing_pivots(spot_1h[-48:], left=2, right=2)
        if len(shs) >= 2:
            i1, i2 = int(shs[-2]["idx"]), int(shs[-1]["idx"])
            p1, p2 = float(shs[-2]["price"]), float(shs[-1]["price"])
            if 0 <= i1 < len(spot_cvd) and 0 <= i2 < len(spot_cvd):
                s_pair = [spot_cvd[i1], spot_cvd[i2]]
                p_pair = [perp_cvd[i1], perp_cvd[i2]] if len(perp_cvd) == len(spot_cvd) else None
                spot_lag = (p2 > p1) and (s_pair[1] <= s_pair[0]) and (p_pair is None or p_pair[1] > p_pair[0])
                r3_1 = {
                    "spot_cvd_last_two_highs": s_pair,
                    "perp_cvd_last_two_highs": p_pair,
                    "spot_lag_or_divergence_flag": bool(spot_lag),
                }

    # R3.2 BTC-denominated OI change & positive funding timing
    oi_1h = deriv.get("btc_oi_change_pct_1h")
    oi_4h = deriv.get("btc_oi_change_pct_4h")
    fund_cur = deriv.get("current_rate_pct")
    if oi_1h is not None or fund_cur is not None:
        feed_status["oi_funding"] = "OK"
    sweep_oi_spike: bool | None = None
    if oi_1h is not None and fund_cur is not None and h1:
        swept = range_high is not None and h1[-1]["high"] > range_high and h1[-1]["close"] < range_high
        sweep_oi_spike = bool(swept and oi_1h > 0.35 and fund_cur > 0.0)
    r3_2 = {
        "btc_oi_change_pct_1h": oi_1h,
        "btc_oi_change_pct_4h": oi_4h,
        "funding_rate_current": fund_cur,
        "sweep_oi_spike_flag": sweep_oi_spike,
    }

    # R3.3 "P"-Shaped FRVP & Poor Highs breakdown
    r3_3: dict[str, Any] = {
        "frvp_poc": None,
        "frvp_vah": None,
        "frvp_val": None,
        "closed_below_upper_val": None,
    }
    if len(h1) >= 24:
        win = h1[-24:]
        low_idx = min(range(len(win)), key=lambda i: float(win[i]["low"]))
        seg = win[low_idx:] if (len(win) - low_idx) >= 4 else win[-12:]
        prof = volume_profile(seg, bin_width=50.0)
        if prof:
            feed_status["frvp"] = "OK"
            last_close = float(h1[-1]["close"])
            p_lvl = poor_highs.get("level")
            # True when POC sits in upper half of leg & latest close broke below VAL
            in_upper = p_lvl is None or prof["poc"] >= (min(c["low"] for c in seg) + max(c["high"] for c in seg)) / 2.0
            r3_3 = {
                "frvp_poc": prof["poc"],
                "frvp_vah": prof["vah"],
                "frvp_val": prof["val"],
                "closed_below_upper_val": bool(in_upper and last_close < prof["val"]),
            }

    # R3.4 Anchored VWAP from primary swing low (48h 1H window)
    r3_4: dict[str, Any] = {
        "anchor_type": None,
        "anchor_price": None,
        "avwap_value": None,
        "price_vs_avwap": None,
        "failed_retest_flag": None,
    }
    if len(h1) >= 24:
        win48 = h1[-48:] if len(h1) >= 48 else h1
        anchor_idx = min(range(len(win48) - 2), key=lambda i: float(win48[i]["low"]))
        avwap_val = anchored_vwap(win48, anchor_idx)
        if avwap_val is not None:
            feed_status["avwap"] = "OK"
            last = win48[-1]
            prev = win48[-2]
            price_vs = "ABOVE" if float(last["close"]) >= avwap_val else "BELOW"
            failed_retest = bool(
                float(prev["close"]) < avwap_val
                and float(last["high"]) >= avwap_val * 0.999
                and float(last["close"]) < avwap_val
                and float(last["close"]) < float(last["open"])
            )
            r3_4 = {
                "anchor_type": "PRIMARY_SWING_LOW_1H",
                "anchor_price": round(float(win48[anchor_idx]["low"]), 1),
                "avwap_value": avwap_val,
                "price_vs_avwap": price_vs,
                "failed_retest_flag": failed_retest,
            }

    return (
        {
            "r3_1_cvd": r3_1,
            "r3_2_oi_funding": r3_2,
            "r3_3_p_shape_frvp": r3_3,
            "r3_4_avwap": r3_4,
        },
        feed_status,
    )


def _compute_cortex_11p(
    h1: list[dict[str, Any]],
    h4: list[dict[str, Any]],
    d1: list[dict[str, Any]],
    spot_1h: list[dict[str, Any]],
    deriv: dict[str, Any],
) -> dict[str, Any]:
    """Compute Gate 1 POIs, Gate 2 Symmetrical 11 Patterns (P01..P11), and Gate 3 Rulebook 3."""
    atr_1h = atr(h1, 14) if len(h1) >= 20 else None
    atr_4h = atr(h4, 14) if len(h4) >= 20 else None

    # Gate 1: HTF POIs & local 1H Range (excluding last 3 bars so active sweeps stay visible)
    sh4, sl4 = swing_pivots(h4[-80:], left=3, right=3) if len(h4) >= 20 else ([], [])
    last_close = round(float(h1[-1]["close"]), 1) if h1 else None

    if len(h1) >= 30:
        ref_slice = h1[-48:-2] if len(h1) >= 48 else h1[:-2]
        range_high = round(max(float(c["high"]) for c in ref_slice), 1)
        range_low = round(min(float(c["low"]) for c in ref_slice), 1)
    else:
        range_high = None
        range_low = None

    supply_cluster: dict[str, Any] = {"low": None, "high": None, "status": UNAVAILABLE}
    if sh4 and atr_4h:
        sh_p = float(sh4[-1]["price"])
        sup_lo = round(sh_p - 0.25 * atr_4h, 1)
        sup_hi = round(sh_p + 0.25 * atr_4h, 1)
        in_sup = last_close is not None and sup_lo <= last_close <= sup_hi
        supply_cluster = {
            "low": sup_lo,
            "high": sup_hi,
            "status": "TESTING" if in_sup else ("ABOVE" if (last_close or 0) > sup_hi else "OVERHEAD"),
        }

    demand_cluster: dict[str, Any] = {"low": None, "high": None, "status": UNAVAILABLE}
    if sl4 and atr_4h:
        sl_p = float(sl4[-1]["price"])
        dem_lo = round(sl_p - 0.25 * atr_4h, 1)
        dem_hi = round(sl_p + 0.25 * atr_4h, 1)
        in_dem = last_close is not None and dem_lo <= last_close <= dem_hi
        demand_cluster = {
            "low": dem_lo,
            "high": dem_hi,
            "status": "TESTING" if in_dem else ("BELOW" if (last_close or 0) < dem_lo else "ACTIVE_SUPPORT"),
        }

    sh1, sl1 = swing_pivots(h1[-60:], left=2, right=2) if len(h1) >= 20 else ([], [])
    first_test_high = round(float(sh1[-1]["price"]), 1) if sh1 else range_high

    # Poor Highs cluster: 2+ highs in last 24h within 0.15*ATR_1H of top ceiling
    poor_highs: dict[str, Any] = {"level": None, "touches": None, "swept": None}
    if len(h1) >= 24 and atr_1h:
        win24 = h1[-24:-1]
        max_hi = max(float(c["high"]) for c in win24)
        tol = max(0.18 * atr_1h, max_hi * 0.0008)
        touches = sum(1 for c in win24 if abs(max_hi - float(c["high"])) <= tol)
        swept = bool(float(h1[-1]["high"]) > max_hi and float(h1[-1]["close"]) < max_hi)
        if touches >= 2:
            poor_highs = {"level": round(max_hi, 1), "touches": touches, "swept": swept}
        else:
            poor_highs = {"level": round(max_hi, 1), "touches": touches, "swept": swept}

    price_and_pois = {
        "last_close": last_close,
        "htf_supply_cluster": supply_cluster,
        "htf_demand_cluster": demand_cluster,
        "range_high": range_high,
        "range_low": range_low,
        "first_test_high": first_test_high,
        "poor_highs_cluster": poor_highs,
    }

    rulebook_3, feed_status = _compute_rulebook_3(h1, spot_1h, deriv, range_high, poor_highs)

    # Gate 2: Symmetrical 11-Pattern Evaluation on 1H + 4H
    # Defaults strictly follow null/UNAVAILABLE when history unavailable
    p_flags: dict[str, Any] = {
        "p01_double_bottom_sweep": {"reclaimed_range_low": None, "sweep_wick_low": None},
        "p02_double_top_sweep": {"reclaimed_below_range_high": None, "sweep_wick_high": None},
        "p03_double_bottom_no_sweep": {"front_run_low": None, "footprint_bid_absorption": None},
        "p04_double_top_no_sweep": {"front_run_high": None, "footprint_ask_absorption": None},
        "p05_rounded_retest_long": {"in_demand_cluster": None, "higher_lows_forming": None},
        "p06_rounded_retest_short": {"in_supply_cluster": None, "internal_sfp_closed_below": None},
        "p07_three_drives_long": {"drive_count": None, "third_drive_low": None},
        "p08_three_drives_short": {"drive_count": None, "third_drive_high": None},
        "p09_mouse_trap": {"impulse_speed_flag": None, "swept_poor_highs_reclaimed": None},
        "p10_bullish_div_rsi_ao": {"price_ll": None, "rsi_hl": None, "ao_hl": None},
        "p11_bearish_div_rsi_ao": {"price_hh": None, "rsi_lh": None, "ao_lh": None},
    }

    patterns_list: list[dict[str, Any]] = []
    if len(h1) >= 40 and range_high is not None and range_low is not None and atr_1h:
        recent3 = h1[-3:]
        min_wick_lo = round(min(float(c["low"]) for c in recent3), 1)
        max_wick_hi = round(max(float(c["high"]) for c in recent3), 1)
        lc = float(h1[-1]["close"])

        # P01 Double Bottom Sweep
        p01_reclaimed = bool(min_wick_lo < range_low and lc > range_low)
        p_flags["p01_double_bottom_sweep"] = {
            "reclaimed_range_low": p01_reclaimed,
            "sweep_wick_low": min_wick_lo if min_wick_lo < range_low else None,
        }

        # P02 Double Top Sweep
        p02_reclaimed = bool(max_wick_hi > range_high and lc < range_high)
        p_flags["p02_double_top_sweep"] = {
            "reclaimed_below_range_high": p02_reclaimed,
            "sweep_wick_high": max_wick_hi if max_wick_hi > range_high else None,
        }

        # P03 Double Bottom No Sweep (Front-Run + bar-level Spot/Taker absorption; tick footprint stays null if unverified)
        front_lo = bool(sl1 and abs(float(sl1[-1]["price"]) - range_low) <= 0.6 * atr_1h and float(sl1[-1]["price"]) > range_low and lc > float(h1[-1]["open"]))
        bid_abs: bool | None = None
        if len(spot_1h) >= 3 and spot_1h[-1].get("taker_buy_volume") is not None:
            s_last = spot_1h[-1]
            s_delta = 2.0 * float(s_last["taker_buy_volume"]) - float(s_last["volume"])
            # Negative/heavy selling delta into low that holds above range_low
            bid_abs = bool(s_delta < 0 and float(s_last["close"]) >= float(s_last["open"]) and float(s_last["low"]) > range_low)
        p_flags["p03_double_bottom_no_sweep"] = {
            "front_run_low": round(float(sl1[-1]["price"]), 1) if front_lo and sl1 else None,
            "footprint_bid_absorption": bid_abs,
        }

        # P04 Double Top No Sweep (Front-Run)
        front_hi = bool(sh1 and abs(range_high - float(sh1[-1]["price"])) <= 0.6 * atr_1h and float(sh1[-1]["price"]) < range_high and lc < float(h1[-1]["open"]))
        ask_abs: bool | None = None
        if len(spot_1h) >= 3 and spot_1h[-1].get("taker_buy_volume") is not None:
            s_last = spot_1h[-1]
            s_delta = 2.0 * float(s_last["taker_buy_volume"]) - float(s_last["volume"])
            ask_abs = bool(s_delta > 0 and float(s_last["close"]) <= float(s_last["open"]) and float(s_last["high"]) < range_high)
        p_flags["p04_double_top_no_sweep"] = {
            "front_run_high": round(float(sh1[-1]["price"]), 1) if front_hi and sh1 else None,
            "footprint_ask_absorption": ask_abs,
        }

        # P05 Rounded Retest Long
        in_dem = demand_cluster["status"] == "TESTING"
        hl_forming = bool(len(sl1) >= 2 and sl1[-1]["price"] > sl1[-2]["price"] and h1[-1]["low"] > sl1[-1]["price"] * 0.998)
        p_flags["p05_rounded_retest_long"] = {
            "in_demand_cluster": in_dem,
            "higher_lows_forming": hl_forming,
        }

        # P06 Rounded Retest Short
        in_sup = supply_cluster["status"] == "TESTING"
        internal_sfp = bool(first_test_high and max_wick_hi > first_test_high and lc < first_test_high and in_sup)
        p_flags["p06_rounded_retest_short"] = {
            "in_supply_cluster": in_sup,
            "internal_sfp_closed_below": internal_sfp,
        }

        # P07 Three Drives Long (4H or 1H descending drives separated by lower highs)
        drives_l = 0
        third_l: float | None = None
        if len(sl4) >= 3 and sl4[-1]["price"] < sl4[-2]["price"] < sl4[-3]["price"]:
            drives_l = 3
            third_l = round(float(sl4[-1]["price"]), 1)
        elif len(sl4) >= 2 and sl4[-1]["price"] < sl4[-2]["price"]:
            drives_l = 2
        p_flags["p07_three_drives_long"] = {
            "drive_count": drives_l,
            "third_drive_low": third_l,
        }

        # P08 Three Drives Short
        drives_h = 0
        third_h: float | None = None
        if len(sh4) >= 3 and sh4[-1]["price"] > sh4[-2]["price"] > sh4[-3]["price"]:
            drives_h = 3
            third_h = round(float(sh4[-1]["price"]), 1)
        elif len(sh4) >= 2 and sh4[-1]["price"] > sh4[-2]["price"]:
            drives_h = 2
        p_flags["p08_three_drives_short"] = {
            "drive_count": drives_h,
            "third_drive_high": third_h,
        }

        # P09 The Mouse Trap
        speed_move = ((float(h1[-4]["close"]) / float(h1[-10]["close"]) - 1.0) * 100.0) if h1[-10]["close"] > 0 else 0.0
        speed_flag = bool(speed_move >= 1.2)
        swept_poor = bool(poor_highs.get("swept") and (poor_highs.get("touches") or 0) >= 2)
        p_flags["p09_mouse_trap"] = {
            "impulse_speed_flag": speed_flag,
            "swept_poor_highs_reclaimed": swept_poor,
        }

        # P10 & P11 Dual RSI(14) + AO(5,34) Divergences
        closes1h = [float(x["close"]) for x in h1]
        rsis1h = rsi_series(closes1h, 14)
        ao1h = awesome_oscillator_series(h1, 5, 34)
        r_off = len(h1) - len(rsis1h)
        win_piv_off = max(0, len(h1) - 60)

        p10_ll = p10_r = p10_a = False
        if len(sl1) >= 2 and rsis1h and len(ao1h) == len(h1):
            l1, l2 = sl1[-2], sl1[-1]
            gi1 = win_piv_off + int(l1["idx"])
            gi2 = win_piv_off + int(l2["idx"])
            ri1, ri2 = gi1 - r_off, gi2 - r_off
            if 0 <= ri1 < len(rsis1h) and 0 <= ri2 < len(rsis1h) and ao1h[gi1] is not None and ao1h[gi2] is not None:
                p10_ll = bool(l2["price"] < l1["price"])
                p10_r = bool(rsis1h[ri2] > rsis1h[ri1] + 1.0)
                p10_a = bool(float(ao1h[gi2]) > float(ao1h[gi1]))
        p_flags["p10_bullish_div_rsi_ao"] = {"price_ll": p10_ll, "rsi_hl": p10_r, "ao_hl": p10_a}

        p11_hh = p11_r = p11_a = False
        if len(sh1) >= 2 and rsis1h and len(ao1h) == len(h1):
            h_1, h_2 = sh1[-2], sh1[-1]
            gi1 = win_piv_off + int(h_1["idx"])
            gi2 = win_piv_off + int(h_2["idx"])
            ri1, ri2 = gi1 - r_off, gi2 - r_off
            if 0 <= ri1 < len(rsis1h) and 0 <= ri2 < len(rsis1h) and ao1h[gi1] is not None and ao1h[gi2] is not None:
                p11_hh = bool(h_2["price"] > h_1["price"])
                p11_r = bool(rsis1h[ri2] < rsis1h[ri1] - 1.0)
                p11_a = bool(float(ao1h[gi2]) < float(ao1h[gi1]))
        p_flags["p11_bearish_div_rsi_ao"] = {"price_hh": p11_hh, "rsi_lh": p11_r, "ao_lh": p11_a}

        # Build structured 11-Pattern summary list for Web + Mobile UI
        def _st(active_cond: bool, forming_cond: bool = False) -> str:
            return "ACTIVE" if active_cond else ("FORMING" if forming_cond else "INACTIVE")

        specs = [
            (1, "p01_double_bottom_sweep", "Double Bottom (Sweep)", "LONG", "Range Extreme", _st(p01_reclaimed, lc <= range_low * 1.008), f"RangeLow ${range_low:,.1f} · Wick ${min_wick_lo:,.1f}"),
            (2, "p02_double_top_sweep", "Double Top (Sweep)", "SHORT", "Range Extreme", _st(p02_reclaimed, lc >= range_high * 0.992), f"RangeHigh ${range_high:,.1f} · Wick ${max_wick_hi:,.1f}"),
            (3, "p03_double_bottom_no_sweep", "Double Bottom (Front-Run)", "LONG", "Range Extreme", _st(front_lo and bool(bid_abs), front_lo), f"FrontRun={'Yes' if front_lo else 'No'} · DeltaAbs={bid_abs}"),
            (4, "p04_double_top_no_sweep", "Double Top (Front-Run)", "SHORT", "Range Extreme", _st(front_hi and bool(ask_abs), front_hi), f"FrontRun={'Yes' if front_hi else 'No'} · DeltaAbs={ask_abs}"),
            (5, "p05_rounded_retest_long", "Rounded Retest (Long)", "LONG", "Range Extreme", _st(in_dem and hl_forming, in_dem or hl_forming), f"InDemand={in_dem} · HL={hl_forming}"),
            (6, "p06_rounded_retest_short", "Rounded Retest (Short)", "SHORT", "Range Extreme", _st(internal_sfp, in_sup), f"InSupply={in_sup} · IntSFP={internal_sfp}"),
            (7, "p07_three_drives_long", "Three Drives (Long)", "LONG", "HTF Reversal", _st(drives_l >= 3, drives_l == 2), f"Drives={drives_l}/3" + (f" · Low3 ${third_l:,.1f}" if third_l else "")),
            (8, "p08_three_drives_short", "Three Drives (Short)", "SHORT", "HTF Reversal", _st(drives_h >= 3, drives_h == 2), f"Drives={drives_h}/3" + (f" · High3 ${third_h:,.1f}" if third_h else "")),
            (9, "p09_mouse_trap", "The Mouse Trap", "SHORT", "LTF Execution", _st(speed_flag and swept_poor, speed_flag and (poor_highs.get("touches") or 0) >= 2), f"Speed={speed_flag} · PoorHiTouches={poor_highs.get('touches')}"),
            (10, "p10_bullish_div_rsi_ao", "Bullish Div (RSI & AO)", "LONG", "Momentum Filter", _st(p10_ll and p10_r and p10_a, p10_ll and (p10_r or p10_a)), f"LL={p10_ll} · RSI_HL={p10_r} · AO_HL={p10_a}"),
            (11, "p11_bearish_div_rsi_ao", "Bearish Div (RSI & AO)", "SHORT", "Momentum Filter", _st(p11_hh and p11_r and p11_a, p11_hh and (p11_r or p11_a)), f"HH={p11_hh} · RSI_LH={p11_r} · AO_LH={p11_a}"),
        ]
        for num_i, pid, pname, pdir, ptier, pst, pdet in specs:
            patterns_list.append(
                {
                    "num": num_i,
                    "id": pid,
                    "name": pname,
                    "direction": pdir,
                    "rotation": "USDT -> BTC" if pdir == "LONG" else "BTC -> USDT",
                    "tier": ptier,
                    "status": pst,
                    "detail": pdet,
                }
            )

    return {
        "schema": "cortex_11p_raw_telemetry_v1",
        "symbol": "BTCUSDT",
        "mode": "UNLEVERAGED_SPOT_SWING_BTC_USDT",
        "timeframes_evaluated": ["15m", "1H", "4H", "1D"],
        "feed_status": feed_status,
        "price_and_pois": price_and_pois,
        "pattern_state_flags": p_flags,
        "patterns_11_list": patterns_list,
        "microstructure_rulebook_3": rulebook_3,
    }


def _classify_state_of_regime(
    market: dict[str, Any],
    regime: dict[str, Any],
    kline_10: dict[str, Any],
    cortex_11p: dict[str, Any],
) -> dict[str, Any]:
    """Classify BTC into 5 Core Market Regimes + Volatility & Flow Modifiers."""
    groups = regime.get("groups") or {}
    ts = groups.get("trend_structure") or {}
    mom = groups.get("momentum") or {}
    vl = groups.get("volatility_liquidity") or {}
    deriv = market.get("derivatives") or {}
    spot_1h = (market.get("klines") or {}).get("spot_1h") or []

    price = float((market.get("ticker") or {}).get("price") or 0.0)
    e20_4h = ts.get("ema20_4h")
    e50_4h = ts.get("ema50_4h")
    e50_d = ts.get("ema50_d")
    d_struct = ts.get("daily_structure")
    rsi_4h = mom.get("rsi_4h")
    rsi_d = mom.get("rsi_d")
    roc6 = mom.get("roc6_4h_pct")
    atr_pctile = vl.get("atr_4h_percentile")
    rel_vol_4h = vl.get("rel_volume_4h")
    funding = deriv.get("current_rate_pct")
    reg_score = float(regime.get("score") or 50.0)

    spot_ratio_24h: float | None = None
    if len(spot_1h) >= 24 and all(c.get("taker_buy_volume") is not None for c in spot_1h[-24:]):
        tot_v = sum(float(c["volume"]) for c in spot_1h[-24:])
        tot_tb = sum(float(c["taker_buy_volume"]) for c in spot_1h[-24:])
        if tot_v > 0:
            spot_ratio_24h = round(tot_tb / tot_v, 4)

    # Select 1 of 5 Core Regimes
    if (
        (rsi_4h is not None and rsi_4h < 28.0)
        or (rsi_d is not None and rsi_d < 29.0 and roc6 is not None and roc6 <= -2.5)
        or (roc6 is not None and roc6 <= -4.5 and (atr_pctile or 0.0) >= 75.0)
    ):
        active_code = "R4"
    elif (
        e20_4h is not None
        and price > e20_4h
        and (
            (rsi_4h is not None and rsi_4h > 72.0)
            or (funding is not None and funding >= 0.02 and (spot_ratio_24h is None or spot_ratio_24h < 0.50))
            or ((atr_pctile or 0.0) > 85.0 and roc6 is not None and roc6 >= 3.5)
        )
    ):
        active_code = "R2"
    elif (
        e20_4h is not None
        and e50_4h is not None
        and price > e20_4h > e50_4h
        and 50.0 <= (rsi_4h or 50.0) <= 72.0
        and reg_score >= 58.0
    ):
        active_code = "R1"
    elif (
        e50_4h is not None
        and price < e50_4h
        and (d_struct == "BEARISH_LH_LL" or (e50_d is not None and price < e50_d))
        and (rsi_4h or 50.0) < 50.0
    ):
        active_code = "R5"
    else:
        active_code = "R3"

    # Modifier 1: Volatility Regime
    h4_hits = {p["id"] for p in (kline_10.get("by_timeframe") or {}).get("4h", [])}
    if (atr_pctile is not None and atr_pctile < 32.0) or "INSIDE_BAR" in h4_hits or "NR4_NR7" in h4_hits:
        vol_mod = "COMPRESSION"
    elif (atr_pctile is not None and atr_pctile > 80.0) or (rel_vol_4h is not None and rel_vol_4h >= 1.8):
        vol_mod = "CLIMAX_EXHAUSTION"
    else:
        vol_mod = "EARLY_EXPANSION"

    # Modifier 2: Flow Backing
    spot_lag = bool((((cortex_11p.get("microstructure_rulebook_3") or {}).get("r3_1_cvd") or {}).get("spot_lag_or_divergence_flag")))
    if spot_ratio_24h is not None and spot_ratio_24h >= 0.512:
        flow_mod = "SPOT_LED"
    elif (funding is not None and funding >= 0.015 and (spot_ratio_24h is None or spot_ratio_24h < 0.498)) or spot_lag:
        flow_mod = "LEVERAGE_LED"
    else:
        flow_mod = "DEFENSIVE"

    active_row = next(r for r in REGIME_CATALOG if r[0] == active_code)
    return {
        "code": active_row[0],
        "id": active_row[1],
        "name": active_row[2],
        "bias": active_row[3],
        "volatility_modifier": vol_mod,
        "flow_modifier": flow_mod,
        "spot_taker_buy_ratio_24h": spot_ratio_24h,
        "summary": (
            f"[{active_row[0]}] {active_row[2]} · Vol={vol_mod} · Flow={flow_mod}"
            + (f" · SpotBuy24H={spot_ratio_24h * 100:.1f}%" if spot_ratio_24h is not None else "")
        ),
        "all_regimes": [
            {
                "code": r[0],
                "id": r[1],
                "name": r[2],
                "bias": r[3],
                "criteria": r[4],
                "active": r[0] == active_code,
            }
            for r in REGIME_CATALOG
        ],
    }


def compute_regime_and_kline_playbook(
    market: dict[str, Any],
    regime: dict[str, Any],
    signal: dict[str, Any],
) -> dict[str, Any]:
    """Compute unified State of Regime (5-State + Modifiers), Layer-1 10 Kline Patterns,
    and Layer-2 Symmetrical 11-Pattern Microstructure Playbook."""
    klines = market.get("klines") or {}
    h1 = klines.get("1h") or []
    h4 = klines.get("4h") or []
    d1 = klines.get("1d") or []
    spot_1h = klines.get("spot_1h") or []
    levels = signal.get("structural_levels") or []
    deriv = market.get("derivatives") or {}

    kline_patterns = _build_kline_10(h1, h4, d1, levels)
    cortex_11p = _compute_cortex_11p(h1, h4, d1, spot_1h, deriv)
    state_of_regime = _classify_state_of_regime(market, regime, kline_patterns, cortex_11p)

    return {
        "state_of_regime": state_of_regime,
        "kline_patterns": kline_patterns,
        "cortex_11p": cortex_11p,
    }
