"""BTC Magnet Monitor Engine — DIBSE Dual-Sleeve Spot Swing, Majority-Voting 5-Regime Radar,
Bidirectional LSCE Sweep Confirmation & 10x–100x Liquidation Magnet Hierarchy.

Ported cleanly into btc-futures-protocol from btc-magnet with strict Zero-Fabrication semantics.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

from .indicators import realized_vol_annualized, sma, volume_profile


def _calc_vwap_since(candles: list[dict[str, Any]], since_ms: int, fallback: float) -> float:
    """Compute cumulative typical-price VWAP from `since_ms` UTC onward."""
    pv = 0.0
    vv = 0.0
    for c in candles:
        if int(c.get("ts") or 0) >= since_ms:
            vol = float(c.get("volume") or 0.0)
            if vol <= 0:
                continue
            tp = (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0
            pv += tp * vol
            vv += vol
    if vv > 0:
        return round(pv / vv, 2)
    return round(float(candles[-1]["close"]), 2) if candles else round(fallback, 2)


def _calc_spot_metrics(
    market: dict[str, Any],
    regime: dict[str, Any],
    signal: dict[str, Any],
) -> dict[str, Any] | None:
    """Assemble verified Spot Magnet microstructure metrics across 4 on-exchange feeds."""
    klines = market.get("klines") or {}
    spot_1d = klines.get("spot_1d") or []
    spot_4h = klines.get("spot_4h") or []
    spot_1h = klines.get("spot_1h") or []

    # Require spot bars or standard closed klines for price anchors; never invent missing data
    d1 = spot_1d if len(spot_1d) >= 20 else (klines.get("1d") or [])
    h4 = spot_4h if len(spot_4h) >= 18 else (klines.get("4h") or [])
    h1 = spot_1h if len(spot_1h) >= 24 else (klines.get("1h") or [])
    if len(h4) < 6 or len(h1) < 24 or len(d1) < 20:
        return None

    xv = market.get("spot_cross_venue") or {}
    deriv = market.get("derivatives") or {}
    extras = market.get("extras") or {}
    etf = market.get("etf") or {}
    ob = deriv.get("orderbook_1pct") or {}

    price = float(
        xv.get("binance_spot_price")
        or (market.get("ticker") or {}).get("price")
        or h1[-1]["close"]
    )
    if price <= 0:
        return None

    now = dt.datetime.now(dt.timezone.utc)
    midnight_ms = int(dt.datetime(now.year, now.month, now.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
    monday = now - dt.timedelta(days=now.weekday())
    monday_ms = int(dt.datetime(monday.year, monday.month, monday.day, tzinfo=dt.timezone.utc).timestamp() * 1000)

    daily_vwap = _calc_vwap_since(h1, midnight_ms, price)
    weekly_vwap = _calc_vwap_since(h4, monday_ms, price)

    # 30D VWAP + Dual 30D VPOCs from closed daily candles
    win30 = d1[-30:] if len(d1) >= 30 else d1
    vwap_30d: float | None = None
    pv30 = sum(((float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0) * float(c["volume"]) for c in win30)
    vv30 = sum(float(c["volume"]) for c in win30)
    if vv30 > 0:
        vwap_30d = round(pv30 / vv30, 2)

    bin_step = 250.0
    vol_bins: dict[float, float] = {}
    for c in list(win30) + list(h4[-60:]):
        v = float(c.get("volume") or 0.0)
        if v <= 0:
            continue
        tp = (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0
        b = round(tp / bin_step) * bin_step
        vol_bins[b] = vol_bins.get(b, 0.0) + v
    vpoc_1: float | None = None
    vpoc_2: float | None = None
    if vol_bins:
        ranked = sorted(vol_bins.items(), key=lambda x: x[1], reverse=True)
        vpoc_1 = round(ranked[0][0], 2)
        for cand_p, _ in ranked[1:]:
            if abs(cand_p - vpoc_1) / max(vpoc_1, 1.0) >= 0.015:
                vpoc_2 = round(cand_p, 2)
                break

    # Spot Volume 24H vs 20D baseline (from Binance spot 1d when available)
    d_vols = [float(c.get("volume") or 0.0) for c in d1]
    spot_vol_ma20 = round(sma(d_vols, 20) or 0.0, 2)
    spot_vol_24h = float(xv.get("spot_vol_24h_btc") or sum(float(c.get("volume") or 0.0) for c in spot_1h[-24:]))
    spot_vol_ratio = round(spot_vol_24h / spot_vol_ma20, 2) if spot_vol_ma20 > 0 and spot_vol_24h > 0 else 1.0

    # Spot CVD Ratio & 7D/14D slopes from BinanceVision taker_buy_volume
    has_taker_1h = len(spot_1h) >= 24 and all(c.get("taker_buy_volume") is not None for c in spot_1h[-24:])
    if not has_taker_1h:
        return None
    tb_24 = sum(float(c["taker_buy_volume"]) for c in spot_1h[-24:])
    tv_24 = sum(float(c["volume"]) for c in spot_1h[-24:])
    ts_24 = max(1e-6, tv_24 - tb_24)
    spot_cvd_ratio = round(tb_24 / ts_24, 3)

    d_deltas = [
        (2.0 * float(c["taker_buy_volume"]) - float(c["volume"]))
        for c in spot_1d
        if c.get("taker_buy_volume") is not None
    ]
    slope_7d = round(sum(d_deltas[-7:]), 1) if len(d_deltas) >= 7 else 0.0
    slope_14d = round(sum(d_deltas[-14:]), 1) if len(d_deltas) >= 14 else 0.0

    # Perp CVD / mark divergence proxy
    mark_px = float(deriv.get("mark_price") or price)
    perp_slope = round(mark_px - price, 2)
    h1_bars = klines.get("1h") or []
    if len(h1_bars) >= 24:
        first12 = sum(
            float(c["volume"]) * ((float(c["close"]) - float(c["open"])) / max(float(c["high"]) - float(c["low"]), 1e-6))
            for c in h1_bars[-24:-12]
        )
        last12 = sum(
            float(c["volume"]) * ((float(c["close"]) - float(c["open"])) / max(float(c["high"]) - float(c["low"]), 1e-6))
            for c in h1_bars[-12:]
        )
        d24 = first12 + last12
        if last12 > first12 + 500:
            perp_trend = "surging"
        elif d24 > 0:
            perp_trend = "positive"
        elif last12 < first12 - 500:
            perp_trend = "lower_lows"
        else:
            perp_trend = "declining"
    else:
        perp_trend = "positive" if perp_slope > 0 else "declining"

    # Price deltas & closed extremes
    prev_1h_close = float(h1[-1]["close"])
    chg_1h_pct = round(((price - prev_1h_close) / prev_1h_close) * 100.0, 2) if prev_1h_close > 0 else 0.0
    chg_24h_pct = float(xv.get("spot_chg_24h_pct") if xv.get("spot_chg_24h_pct") is not None else ((market.get("ticker") or {}).get("chg24_pct") or 0.0))

    swing_low_4h = round(min(float(c["low"]) for c in h4[-6:]), 2)
    swing_high_4h = round(max(float(c["high"]) for c in h4[-6:]), 2)
    base_floor = round(min(float(c["low"]) for c in h4[-18:]), 2)
    base_ceiling = round(max(float(c["high"]) for c in h4[-18:]), 2)
    cap_wick_low = round(min(float(c["low"]) for c in h1[-24:]), 2)
    euph_wick_high = round(max(float(c["high"]) for c in h1[-24:]), 2)

    # Derivatives positioning & volatility
    cur_oi = float(deriv.get("oi_btc") or deriv.get("total_oi_btc") or 0.0)
    oi_1h = deriv.get("btc_oi_change_pct_1h")
    oi_4h = deriv.get("btc_oi_change_pct_4h")
    oi_24h = deriv.get("btc_oi_change_pct_24h")
    oi_3d = deriv.get("btc_oi_change_pct_3d")

    fund_8h_pct = deriv.get("current_rate_pct")
    fund_dec = (float(fund_8h_pct) / 100.0) if fund_8h_pct is not None else 0.0
    fund_ann_pct = round(fund_dec * 3.0 * 365.0 * 100.0, 2)
    basis_ann_pct = round(((mark_px - price) / price) * 100.0 * (365.0 / 30.0), 2)

    ls_ratio = deriv.get("long_short_account_ratio")
    ls_pct = deriv.get("ls_ratio_percentile_72h")
    ls_avail = ls_ratio is not None
    depth_ratio = float(ob.get("imbalance_ratio")) if ob.get("imbalance_ratio") is not None else 1.0

    # Realized Vol vs Implied DVOL Variance Risk Premium
    d_closes = [float(c["close"]) for c in d1]
    rvol_raw = realized_vol_annualized(d_closes, 30, periods_per_year=365.0)
    rvol_pct = round(rvol_raw, 2) if rvol_raw is not None else None
    dvol_pct = extras.get("dvol")
    var_prem = round(float(dvol_pct) - float(rvol_pct), 2) if (dvol_pct is not None and rvol_pct is not None) else None

    return {
        "price": round(price, 2),
        "price_change_1h_pct": chg_1h_pct,
        "price_change_24h_pct": round(chg_24h_pct, 2),
        "daily_vwap": daily_vwap,
        "weekly_vwap": weekly_vwap,
        "vwap_30d": vwap_30d,
        "vpoc_30d_primary": vpoc_1,
        "vpoc_30d_secondary": vpoc_2,
        "spot_vol_24h": round(spot_vol_24h, 2),
        "spot_vol_ma20": spot_vol_ma20,
        "spot_vol_ratio": spot_vol_ratio,
        "spot_cvd_ratio": spot_cvd_ratio,
        "spot_cvd_slope_7d": slope_7d,
        "spot_cvd_slope_14d": slope_14d,
        "perp_cvd_slope_24h": perp_slope,
        "perp_cvd_trend": perp_trend,
        "open_interest_btc": round(cur_oi, 1) if cur_oi > 0 else None,
        "oi_change_1h_pct": oi_1h,
        "oi_change_4h_pct": oi_4h,
        "oi_change_24h_pct": oi_24h,
        "oi_change_3d_pct": oi_3d,
        "funding_rate_8h_pct": round(float(fund_8h_pct), 5) if fund_8h_pct is not None else None,
        "funding_rate_decimal": round(fund_dec, 7),
        "funding_rate_annualized_pct": fund_ann_pct,
        "futures_basis_annualized_pct": basis_ann_pct,
        "long_short_account_ratio": float(ls_ratio) if ls_avail else None,
        "ls_ratio_percentile_72h": ls_pct,
        "ls_ratio_available": ls_avail,
        "oi_history_available": oi_24h is not None,
        "bids_asks_depth_ratio": round(depth_ratio, 2),
        "swing_low_4h": swing_low_4h,
        "swing_high_4h": swing_high_4h,
        "base_floor": base_floor,
        "base_ceiling": base_ceiling,
        "capitulation_wick_low": cap_wick_low,
        "euphoria_wick_high": euph_wick_high,
        "coinbase_spot_price": xv.get("coinbase_spot_price"),
        "okx_spot_price": xv.get("okx_spot_price"),
        "coinbase_premium_usd": xv.get("coinbase_premium_usd"),
        "coinbase_premium_bps": xv.get("coinbase_premium_bps"),
        "realized_vol_30d_pct": rvol_pct,
        "implied_vol_dvol_pct": dvol_pct,
        "variance_premium_pts": var_prem,
        "etf_net_inflow_latest_m": etf.get("latest_usd_m"),
        "etf_sum5_usd_m": etf.get("sum5_usd_m"),
    }


def _calc_modeled_clusters(m: dict[str, Any], h4: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Derive nearest upper short & lower long modeled liquidation clusters (with >=0.45% clearance)."""
    price = float(m["price"])
    total_oi = float(m.get("open_interest_btc") or 25000.0)
    recent_highs = [float(c["high"]) for c in h4[-40:]]
    recent_lows = [float(c["low"]) for c in h4[-40:]]

    tiers = [(100, 0.008, 0.15), (50, 0.018, 0.30), (25, 0.038, 0.35), (10, 0.095, 0.20)]
    bin_size = max(100.0, round(price * 0.0015, -1))
    upper_bins: dict[float, float] = {}
    lower_bins: dict[float, float] = {}

    for low_v in set(recent_lows):
        for _, off, share in tiers:
            tgt = low_v * (1.0 + off)
            if tgt > price:
                bp = round(tgt / bin_size) * bin_size
                upper_bins[bp] = upper_bins.get(bp, 0.0) + (total_oi * 0.02 * price * share)
        for off in (0.005, 0.012, 0.025):
            tgt = low_v * (1.0 - off)
            if tgt < price:
                bp = round(tgt / bin_size) * bin_size
                lower_bins[bp] = lower_bins.get(bp, 0.0) + (total_oi * 0.03 * price)

    for hi_v in set(recent_highs):
        for _, off, share in tiers:
            tgt = hi_v * (1.0 - off)
            if tgt < price:
                bp = round(tgt / bin_size) * bin_size
                lower_bins[bp] = lower_bins.get(bp, 0.0) + (total_oi * 0.02 * price * share)
        for off in (0.005, 0.012, 0.025):
            tgt = hi_v * (1.0 + off)
            if tgt > price:
                bp = round(tgt / bin_size) * bin_size
                upper_bins[bp] = upper_bins.get(bp, 0.0) + (total_oi * 0.03 * price)

    min_clear = price * 0.0045
    all_u = [x for x in sorted(upper_bins.items(), key=lambda i: i[0]) if x[0] > price]
    clr_u = [x for x in all_u if x[0] >= price + min_clear]
    pick_u = clr_u[0] if clr_u else (all_u[0] if all_u else None)

    all_l = [x for x in sorted(lower_bins.items(), key=lambda i: i[0], reverse=True) if x[0] < price]
    clr_l = [x for x in all_l if x[0] <= price - min_clear]
    pick_l = clr_l[0] if clr_l else (all_l[0] if all_l else None)

    upper = (
        {
            "price_level": round(pick_u[0], 2),
            "distance_pct": round(((pick_u[0] - price) / price) * 100.0, 2),
            "estimated_vol_usd": round(pick_u[1], 0),
            "side": "upper",
            "cluster_type": "Modeled Short Liquidity Pool",
        }
        if pick_u
        else None
    )
    lower = (
        {
            "price_level": round(pick_l[0], 2),
            "distance_pct": round(((price - pick_l[0]) / price) * 100.0, 2),
            "estimated_vol_usd": round(pick_l[1], 0),
            "side": "lower",
            "cluster_type": "Modeled Long Liquidity Pool",
        }
        if pick_l
        else None
    )
    return upper, lower


def _eval_lsce(m: dict[str, Any], lower: dict[str, Any] | None, upper: dict[str, Any] | None) -> dict[str, Any]:
    """Bidirectional Liquidation Sweep Confirmation Engine (LSCE)."""
    cur_p = float(m["price"])
    wick_hi = float(m["euphoria_wick_high"]) or cur_p
    wick_lo = float(m["capitulation_wick_low"]) or cur_p
    l_p = float(lower["price_level"]) if lower else float(m["swing_low_4h"])
    u_p = float(upper["price_level"]) if upper else float(m["swing_high_4h"])
    cvd = float(m["spot_cvd_ratio"])
    depth = float(m["bids_asks_depth_ratio"])
    fund_dec = float(m["funding_rate_decimal"])

    if lower and wick_lo <= l_p * 1.002 and (l_p < cur_p <= l_p * 1.015) and cvd >= 1.05 and depth >= 0.50:
        return {
            "status": "SWEEP_AND_RECLAIM_CONFIRMED",
            "side": "LOWER",
            "cluster_tested": f"Lower Longs (${l_p:,.0f})",
            "sweep_depth_pct": round(((cur_p - l_p) / cur_p) * 100.0, 2),
            "reclaim_level": round(l_p, 2),
            "spot_absorption": f"Strong Bid Absorption (CVD {cvd:.2f}, Depth {depth:.2f})",
            "action_verdict": f"Lower long shelf (${l_p:,.0f}) swept & reclaimed with spot buying. Loop A (USDT -> BTC) confirmed.",
        }

    u_ref = u_p if (upper and wick_hi >= u_p * 0.998) else float(m["swing_high_4h"])
    if upper and u_ref > 0 and wick_hi >= u_ref * 0.998 and (u_ref * 0.985 <= cur_p < u_ref) and (cvd < 1.08 or depth < 0.75 or fund_dec >= 0.0001):
        return {
            "status": "UPPER_SWEEP_REJECTION_CONFIRMED",
            "side": "UPPER",
            "cluster_tested": f"Upper Shorts (${u_ref:,.0f})",
            "sweep_depth_pct": round(((wick_hi - u_ref) / cur_p) * 100.0, 2),
            "reclaim_level": round(u_ref, 2),
            "spot_absorption": f"Upper Rejection (CVD {cvd:.2f}, Depth {depth:.2f})",
            "action_verdict": f"Upper short liquidity (${u_ref:,.0f}) swept (wick ${wick_hi:,.0f}) & rejected. Loop B (BTC -> USDT) active.",
        }

    if lower:
        dist_l = ((cur_p - l_p) / cur_p) * 100.0
        if abs(cur_p - l_p) / cur_p <= 0.002 or (l_p * 0.990 <= cur_p < l_p):
            return {
                "status": "SWEEP_IN_PROGRESS",
                "side": "LOWER",
                "cluster_tested": f"Lower Longs (${l_p:,.0f})",
                "sweep_depth_pct": round(dist_l, 2),
                "reclaim_level": round(l_p, 2),
                "spot_absorption": f"Testing (CVD {cvd:.2f}, Depth {depth:.2f})",
                "action_verdict": f"Testing/piercing ${l_p:,.0f} lower shelf. Wait for reclaim > ${l_p:,.0f} + CVD >= 1.05 before firing Loop A.",
            }
        if cur_p < l_p * 0.990 or (cur_p < float(m["swing_low_4h"]) and depth < 0.35):
            return {
                "status": "SWEEP_FAILED_BREAKDOWN",
                "side": "LOWER",
                "cluster_tested": f"Lower Longs (${l_p:,.0f})",
                "sweep_depth_pct": round(dist_l, 2),
                "reclaim_level": round(float(m["swing_low_4h"]), 2),
                "spot_absorption": f"Thin Bids (Depth {depth:.2f})",
                "action_verdict": f"Lower shelf (${l_p:,.0f}) broke down. Hold 10% USDT dry; zero forced stop-loss on 10% BTC inventory.",
            }

    if upper:
        dist_u = ((cur_p - u_p) / cur_p) * 100.0
        if abs(u_p - cur_p) / cur_p <= 0.002 or (u_p < cur_p <= u_p * 1.010):
            return {
                "status": "UPPER_SWEEP_IN_PROGRESS",
                "side": "UPPER",
                "cluster_tested": f"Upper Shorts (${u_p:,.0f})",
                "sweep_depth_pct": round(dist_u, 2),
                "reclaim_level": round(u_p, 2),
                "spot_absorption": f"Testing Ceiling (CVD {cvd:.2f}, Depth {depth:.2f})",
                "action_verdict": f"Probing upper short pool (${u_p:,.0f}). Prepare Loop B (BTC -> USDT) into rejection.",
            }

    dist_l_pct = ((cur_p - l_p) / cur_p) * 100.0
    dist_u_pct = ((u_p - cur_p) / cur_p) * 100.0
    return {
        "status": "UNTESTED",
        "side": "NONE",
        "cluster_tested": f"Lower ${l_p:,.0f} | Upper ${u_p:,.0f}",
        "sweep_depth_pct": round(dist_l_pct, 2),
        "reclaim_level": round(l_p, 2),
        "spot_absorption": "Balanced / Mid-Range",
        "action_verdict": f"Spot sits +{dist_l_pct:.2f}% above lower pool (${l_p:,.0f}) and -{dist_u_pct:.2f}% below upper pool (${u_p:,.0f}). Hold both sleeves.",
    }


def _evaluate_magnets(
    m: dict[str, Any],
    upper: dict[str, Any] | None,
    lower: dict[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate 6-Factor Dominant Magnet and build canonical 10x-100x liquidation ladder."""
    cur_p = float(m["price"])
    u_vol = float(upper["estimated_vol_usd"]) / 1e6 if upper else 0.0
    l_vol = float(lower["estimated_vol_usd"]) / 1e6 if lower else 0.0
    oi_m = max(10.0, (float(m.get("open_interest_btc") or 25000.0) * cur_p) / 1e6)

    ls = float(m["long_short_account_ratio"]) if m["ls_ratio_available"] and (m.get("long_short_account_ratio") or 0) > 0 else 1.0
    long_share = ls / (1.0 + ls)
    l_w = max(0.50, long_share / 0.50)
    u_w = max(0.50, (1.0 - long_share) / 0.50)

    u_25 = round(max(1.0, oi_m * 0.032 * u_w), 1)
    u_10 = round(max(1.0, oi_m * 0.024 * u_w), 1)
    l_25 = round(max(1.0, oi_m * 0.040 * l_w), 1)
    l_10 = round(max(1.0, oi_m * 0.028 * l_w), 1)

    tot_u = round(u_10 + u_25 + u_vol, 1)
    tot_l = round(l_10 + l_25 + l_vol, 1)
    imm_ratio = round(l_vol / max(u_vol, 0.1), 1)
    tot_ratio = round(tot_l / max(tot_u, 0.1), 2)

    sh4 = float(m["swing_high_4h"])
    sl4 = float(m["swing_low_4h"])
    u_near_p = float(upper["price_level"]) if upper else round(sh4 * 1.005, 2)
    l_near_p = float(lower["price_level"]) if lower else round(sl4 * 0.995, 2)

    def _row(tier: str, lev: str, side: str, px: float, vol_m: float, is_nearest: bool = False) -> dict[str, Any]:
        return {
            "tier": tier,
            "leverage": lev,
            "side": side,
            "price": round(px, 2),
            "distance_pct": round(((px - cur_p) / cur_p) * 100.0, 2),
            "estimated_vol_m": round(vol_m, 1),
            "is_nearest": is_nearest,
        }

    ladder = [
        _row("10x Shorts", "10x", "upper", sh4 * 1.025, u_10),
        _row("25x Shorts", "25x", "upper", sh4 * 1.012, u_25),
        _row("50-100x Shorts", "50-100x", "upper", u_near_p, u_vol, is_nearest=True),
        _row("100x Longs", "100x", "lower", l_near_p, l_vol, is_nearest=True),
        _row("25x Longs", "25x", "lower", sl4 * 0.988, l_25),
        _row("10x Longs", "10x", "lower", sl4 * 0.975, l_10),
    ]

    u_dist = max(0.04, float(upper["distance_pct"]) if upper else 1.5)
    l_dist = max(0.04, float(lower["distance_pct"]) if lower else 1.5)
    pull_u = (u_vol / 1e6) / (u_dist ** 1.15)
    pull_l = (l_vol / 1e6) / (l_dist ** 1.15)
    if m["ls_ratio_available"] and ls >= 1.6:
        pull_l *= 1.85
    if float(m["spot_cvd_ratio"]) >= 1.15:
        pull_u *= 1.40
    if imm_ratio >= 3.0:
        pull_l *= 1.50

    if not upper and not lower:
        dom = "Neutral / None"
        reason = "No clear liquidation clusters"
    elif pull_l >= pull_u and lower:
        dom = "Lower Long Sweep Magnet"
        crowd = f"{long_share * 100:.1f}% long crowded" if m["ls_ratio_available"] else "lower OI density"
        reason = f"LOWER (${lower['price_level']:,.0f}, Immediate {imm_ratio:.1f}x / Ladder {tot_ratio:.2f}x; {crowd})"
    else:
        dom = "Upper Short Squeeze Magnet"
        reason = f"UPPER (${upper['price_level']:,.0f} if swept, +{upper['distance_pct']:.2f}%)" if upper else "UPPER"

    range_w_pct = ((sh4 - sl4) / cur_p) * 100.0
    wick_span_pct = ((float(m["euphoria_wick_high"]) - float(m["capitulation_wick_low"])) / cur_p) * 100.0
    factors = {
        "factor_1_size": f"Immediate L vs S: ${l_vol:.1f}M vs ${u_vol:.1f}M ({imm_ratio:.1f}x) | 10x–100x Ladder: ${tot_l:.1f}M vs ${tot_u:.1f}M ({tot_ratio:.2f}x)",
        "factor_2_spot_leadership": f"Spot CVD Ratio {m['spot_cvd_ratio']:.2f} vs Perp Trend {m['perp_cvd_trend']}",
        "factor_3_crowding_fuel": (
            f"Funding {m.get('funding_rate_8h_pct') or 0:+.4f}% | Retail L/S {ls:.2f} ({long_share * 100:.1f}% long)"
            if m["ls_ratio_available"]
            else f"Funding {m.get('funding_rate_8h_pct') or 0:+.4f}% | Retail L/S UNAVAILABLE"
        ),
        "factor_4_regime_structure": (
            "Sub-Daily-VWAP structure (overhead supply active)"
            if cur_p < float(m["daily_vwap"])
            else "Above Daily VWAP (supportive spot floor)"
        ),
        "factor_5_asymmetry": f"LOWER -{l_dist:.2f}% away vs UPPER +{u_dist:.2f}% away",
        "factor_6_range_compression": f"Closed 4H Range {range_w_pct:.2f}% | 24H Wick Span {wick_span_pct:.2f}% | Depth {m['bids_asks_depth_ratio']:.2f}",
    }

    return {
        "dominant_magnet": dom,
        "dominant_magnet_reason": reason,
        "nearest_upper_cluster": upper,
        "nearest_lower_cluster": lower,
        "immediate_imbalance_ratio": imm_ratio,
        "total_ladder_upper_vol_m": tot_u,
        "total_ladder_lower_vol_m": tot_l,
        "total_ladder_imbalance_ratio": tot_ratio,
        "magnet_factors": factors,
        "liquidation_ladder": ladder,
    }


def _classify_5_regimes(m: dict[str, Any], lsce: dict[str, Any]) -> dict[str, Any]:
    """Run BTC Magnet Majority-Voting (>=3 of 4) 5-Regime Spot Radar + Sub-VWAP Conflict Gate."""
    p = float(m["price"])
    d_vwap = float(m["daily_vwap"])
    w_vwap = float(m["weekly_vwap"])
    cvd = float(m["spot_cvd_ratio"])
    s7 = float(m["spot_cvd_slope_7d"])
    s14 = float(m["spot_cvd_slope_14d"])
    s_vol = float(m["spot_vol_ratio"])
    fund = float(m["funding_rate_decimal"])
    basis = float(m["futures_basis_annualized_pct"])
    oi1h = float(m.get("oi_change_1h_pct") or 0.0)
    oi4h = float(m.get("oi_change_4h_pct") or 0.0)
    oi24h = float(m.get("oi_change_24h_pct") or 0.0)
    oi3d = float(m.get("oi_change_3d_pct") or 0.0)
    sh4 = float(m["swing_high_4h"])
    sl4 = float(m["swing_low_4h"])
    depth = float(m["bids_asks_depth_ratio"])
    ls = float(m["long_short_account_ratio"] or 1.0)
    ls_avail = bool(m["ls_ratio_available"])
    lsce_st = lsce["status"]

    # 1. Spot-Led Expansion
    m1 = []
    if p > d_vwap and p > w_vwap:
        m1.append("Price holding above Daily and Weekly VWAP")
    if cvd >= 1.05 and (s7 > 0 or s14 > 0):
        m1.append(f"Spot CVD leading (Ratio {cvd:.2f}, Slope 7D {s7:+.0f})")
    if fund <= 0.00012 and oi24h <= 3.5:
        m1.append(f"Funding & OI controlled (Fund {fund * 100:.3f}%, OI24h {oi24h:+.1f}%)")
    if s_vol >= 1.0:
        m1.append(f"Spot volume confirmed ({s_vol:.2f}x 20D baseline)")
    if lsce_st == "UPPER_SWEEP_REJECTION_CONFIRMED":
        s1, sig1, rot1, act1, pb1 = 0.50, "LOOP B: BTC -> USDT", "BTC -> USDT", "Loop B: Harvest 50% of 10% BTC Sleeve into Upper Sweep", "Spot Expansion Exhaustion -> Loop B Trim (0.50x)"
    elif lsce_st == "SWEEP_AND_RECLAIM_CONFIRMED" or p <= d_vwap * 1.004:
        s1, sig1, rot1, act1, pb1 = 0.75, "LOOP A: USDT -> BTC", "USDT -> BTC", "Loop A: Deploy 75% of 10% USDT Sleeve on VWAP Pullback", "Spot-Led Pullback -> Loop A Accumulate (0.75x)"
    else:
        s1, sig1, rot1, act1, pb1 = 0.0, "HOLD BOTH SLEEVES", "Hold Both Sleeves", "Hold Both Sleeves (Zero Upside Stop-Buy)", "Ride 10% BTC Sleeve; Keep 10% USDT Dry"
    c1 = {"regime_id": "SPOT_LED_EXPANSION", "name": "Spot-Led Expansion", "priority": 4, "matched": m1, "matches_count": len(m1), "sizing": s1, "dibse": sig1, "rotation": rot1, "action": act1, "playbook": pb1, "suitability": "Trend Environment (Zero Chase Rule)", "diagnosis": "Genuine spot demand supporting upside"}

    # 2. Leveraged / Fragile Upside
    m2 = []
    if m["price_change_24h_pct"] > 0.8 and cvd < 1.12:
        m2.append(f"Price rising ({m['price_change_24h_pct']:+.2f}%) while Spot CVD lags ({cvd:.2f})")
    if oi24h >= 4.0 or m["perp_cvd_trend"] == "surging" or oi3d >= 10.0:
        m2.append(f"Futures leverage expanding (OI24h {oi24h:+.2f}%, Perp {m['perp_cvd_trend']})")
    if fund >= 0.00015 or basis >= 12.0:
        m2.append(f"Funding elevated ({fund * 100:.3f}%) or basis wide ({basis:+.1f}%)")
    if s_vol < 1.0:
        m2.append(f"Spot volume failing to confirm ({s_vol:.2f}x 20D baseline)")
    c2 = {"regime_id": "LEVERAGED_FRAGILE_UPSIDE", "name": "Leveraged / Fragile Upside", "priority": 2, "matched": m2, "matches_count": len(m2), "sizing": 1.0, "dibse": "LOOP B: BTC -> USDT", "rotation": "BTC -> USDT", "action": "Loop B: Sell 10% BTC Sleeve into Squeeze", "playbook": "Loop B: Rotate 10% BTC Sleeve -> USDT", "suitability": "Loop B Distribution Harvest Zone", "diagnosis": "Upside driven mainly by futures leverage / crowding"}

    # 3. Range / Liquidation Magnet
    m3 = []
    rw = ((sh4 - sl4) / p) * 100.0
    if rw <= 4.5 and (sl4 * 0.985 <= p <= sh4 * 1.015):
        m3.append(f"Closed 4H channel ({rw:.2f}% width: ${sl4:,.0f}–${sh4:,.0f})")
    if 0.90 <= cvd <= 1.25:
        m3.append(f"Spot CVD balanced inside range (Ratio {cvd:.2f})")
    if (ls_avail and ls >= 1.6) or fund >= 0.00008 or fund <= -0.00004:
        m3.append(f"Positioning skewed (L/S {ls:.2f}, Fund {fund * 100:.3f}%)" if ls_avail else f"Funding skewed ({fund * 100:.3f}%)")
    m3.append("Symmetrical liquidation pools active above & below spot")
    if lsce_st == "SWEEP_AND_RECLAIM_CONFIRMED":
        s3, sig3, rot3, act3, pb3 = 0.75, "LOOP A: USDT -> BTC", "USDT -> BTC", "Loop A: Buy Spot (75% of 10% USDT Sleeve)", "Range Washout Reclaim -> Loop A Entry"
    elif lsce_st == "UPPER_SWEEP_REJECTION_CONFIRMED" or p >= sh4 * 0.992:
        s3, sig3, rot3, act3, pb3 = 0.75, "LOOP B: BTC -> USDT", "BTC -> USDT", "Loop B: Sell Spot (75% of 10% BTC Sleeve)", "Range Ceiling / Upper Squeeze -> Loop B Harvest"
    else:
        s3, sig3, rot3, act3, pb3 = 0.0, "HOLD BOTH SLEEVES", "Hold Both Sleeves", "Hold Both Sleeves (Wait Range Edge)", "Dual-Sleeve Standby: 10% USDT + 10% BTC"
    c3 = {"regime_id": "RANGE_LIQUIDATION_MAGNET", "name": "Range / Liquidation Magnet", "priority": 3, "matched": m3, "matches_count": len(m3), "sizing": s3, "dibse": sig3, "rotation": rot3, "action": act3, "playbook": pb3, "suitability": "Core Bidirectional DIBSE Habitat", "diagnosis": "Defined 4H channel with liquidation clusters on both edges"}

    # 4. Cascade / Forced Deleveraging
    m4 = []
    if m["price_change_1h_pct"] <= -2.8 or m["price_change_24h_pct"] <= -6.0:
        m4.append(f"Sharp price plunge ({m['price_change_1h_pct']:+.2f}% 1h / {m['price_change_24h_pct']:+.2f}% 24h)")
    if oi1h <= -3.5 or oi4h <= -7.0:
        m4.append(f"OI unwinding sharply ({oi1h:+.2f}% 1h / {oi4h:+.2f}% 4h)")
    if fund <= -0.00005:
        m4.append(f"Funding deeply negative ({fund * 100:.3f}%)")
    if basis < 1.0:
        m4.append(f"Basis compressed / backwardation ({basis:+.2f}%)")
    c4 = {"regime_id": "CASCADE_FORCED_DELEVERAGING", "name": "Cascade / Forced Deleveraging", "priority": 1, "matched": m4, "matches_count": len(m4), "sizing": 0.0, "dibse": "HOLD BOTH SLEEVES", "rotation": "Hold Both Sleeves", "action": "Hold Both Sleeves (Wait Exhaustion)", "playbook": "Pause Loop A Entries; Hold Existing Inventory", "suitability": "Waterfall Protection Mode", "diagnosis": "Forced derivatives unwind in progress"}

    # 5. Distribution / Bear Continuation
    m5 = []
    if p < d_vwap and p < w_vwap and p < sh4 * 0.99:
        m5.append("Price trapped below Daily VWAP, Weekly VWAP & closed 4H ceiling")
    if s7 < 0 or cvd <= 0.88:
        m5.append(f"Spot CVD persistently negative (7D {s7:+.0f} / Ratio {cvd:.2f})")
    if s_vol < 0.95:
        m5.append(f"Spot volume depressed ({s_vol:.2f}x 20D baseline)")
    if fund >= 0.00002 or basis < 4.0:
        m5.append(f"Funding {fund * 100:+.4f}% / compressed basis ({basis:+.2f}%)")
    if lsce_st == "UPPER_SWEEP_REJECTION_CONFIRMED" or p >= d_vwap * 0.998:
        s5, sig5, rot5, act5, pb5 = 0.50, "LOOP B: BTC -> USDT", "BTC -> USDT", "Loop B: Trim 50% of 10% BTC Sleeve into Bounce", "Distribution Bounce -> Loop B Trim (0.50x)"
    else:
        s5, sig5, rot5, act5, pb5 = 0.0, "HOLD BOTH SLEEVES", "Hold Both Sleeves", "Hold Both Sleeves (Protect 10% USDT Sleeve)", "Guard 10% USDT; Hold BTC Inventory (No Stop-Loss)"
    c5 = {"regime_id": "DISTRIBUTION_BEAR_CONTINUATION", "name": "Distribution / Bear Continuation", "priority": 2, "matched": m5, "matches_count": len(m5), "sizing": s5, "dibse": sig5, "rotation": rot5, "action": act5, "playbook": pb5, "suitability": "Loop B Bounce Harvest / Loop A Patient", "diagnosis": "Weak spot demand / active overhead distribution"}

    candidates = [c1, c2, c3, c4, c5]
    valid = [c for c in candidates if c["matches_count"] >= 3]
    has_edge = lsce_st in ("SWEEP_AND_RECLAIM_CONFIRMED", "UPPER_SWEEP_REJECTION_CONFIRMED")
    is_conflicted = p < d_vwap and p < w_vwap and basis < 0.0 and depth < 0.35 and not has_edge

    if is_conflicted and any(c["regime_id"] == "RANGE_LIQUIDATION_MAGNET" for c in valid):
        best = {
            "regime_id": "TRANSITION_MIXED",
            "name": "Transition / Mixed",
            "matched": [
                f"Sub-VWAP Conflict Gate: Spot (${p:,.2f}) < Daily (${d_vwap:,.2f}) & Weekly (${w_vwap:,.2f})",
                f"Backwardation ({basis:+.2f}%) + Thin Orderbook Depth ({depth:.2f} < 0.35)",
            ],
            "matches_count": 2,
            "sizing": 0.0,
            "dibse": "HOLD BOTH SLEEVES",
            "rotation": "Hold Both Sleeves",
            "action": "Hold Both Sleeves (Conflict Override)",
            "playbook": "Hold Both Sleeves (10% USDT + 10% BTC)",
            "suitability": "Neutral Dual-Sleeve Standby",
            "diagnosis": "Conflicted sub-VWAP & negative-basis structure",
            "majority_score": "Conflict Override (Sub-VWAP + Negative Basis)",
        }
    elif valid:
        valid.sort(key=lambda x: (x["priority"], -x["matches_count"]))
        best = {**valid[0], "majority_score": f"{valid[0]['matches_count']}/4 observations confirmed"}
    else:
        top_c = max(candidates, key=lambda x: x["matches_count"])
        best = {
            "regime_id": "TRANSITION_MIXED",
            "name": "Transition / Mixed",
            "matched": [
                f"Top candidate ({top_c['name']}) scored {top_c['matches_count']}/4 (< 3 required)",
                f"Spot ${p:,.2f} vs Daily VWAP ${d_vwap:,.2f} | CVD {cvd:.2f} | Basis {basis:+.2f}%",
            ],
            "matches_count": top_c["matches_count"],
            "sizing": 0.0,
            "dibse": "HOLD BOTH SLEEVES",
            "rotation": "Hold Both Sleeves",
            "action": "Hold Both Sleeves (Wait Edge)",
            "playbook": "Hold Both Sleeves (10% USDT + 10% BTC)",
            "suitability": "Neutral Dual-Sleeve Standby",
            "diagnosis": "Signals mixed or transitioning (awaiting Loop A/B edge)",
            "majority_score": f"Mixed ({top_c['matches_count']}/4 max)",
        }

    return {
        "best": best,
        "all_5_candidates": [
            {
                "id": c["regime_id"],
                "name": c["name"],
                "matches_count": c["matches_count"],
                "required": 3,
                "matched": c["matched"],
                "active": c["regime_id"] == best["regime_id"],
            }
            for c in candidates
        ],
    }


def compute_spot_magnet(
    market: dict[str, Any],
    regime: dict[str, Any],
    signal: dict[str, Any],
) -> dict[str, Any]:
    """Compute complete BTC Magnet Monitor Spot Radar & DIBSE Dual-Sleeve telemetry."""
    m = _calc_spot_metrics(market, regime, signal)
    if m is None:
        return {
            "data_quality": "DATA_UNAVAILABLE",
            "metrics": None,
            "lsce": {"status": "UNAVAILABLE", "side": "NONE", "action_verdict": "Spot taker / candle telemetry unavailable."},
            "magnets": None,
            "regime_diagnosis": {
                "regime_id": "DATA_INCOMPLETE",
                "name": "DATA UNAVAILABLE",
                "majority_score": "0/4",
                "matched_criteria": [],
                "all_5_candidates": [],
                "plain_english_verdict": "Telemetry incomplete. Holding 10% USDT + 10% BTC sleeves passively.",
            },
            "dibse": {
                "dibse_signal": "HOLD BOTH SLEEVES",
                "rotation": "Hold Both Sleeves",
                "sizing_factor": 0.0,
                "actionable_trade_instruction": "DATA UNAVAILABLE — Hold both 10% USDT & 10% BTC sleeves passively.",
            },
        }

    klines = market.get("klines") or {}
    h4 = klines.get("spot_4h") if len(klines.get("spot_4h") or []) >= 18 else (klines.get("4h") or [])
    upper, lower = _calc_modeled_clusters(m, h4)
    lsce = _eval_lsce(m, lower, upper)
    magnets = _evaluate_magnets(m, upper, lower)
    cls_res = _classify_5_regimes(m, lsce)
    best = cls_res["best"]

    sizing = float(best["sizing"])
    sig_str = best["dibse"]
    if sig_str == "LOOP A: USDT -> BTC" and sizing > 0:
        eq_pct = round(sizing * 10.0, 1)
        tgt_btc = round(10.0 + eq_pct, 1)
        tgt_usdt = round(10.0 - eq_pct, 1)
        deploy_pct = round(sizing * 100.0, 1)
        instr = f"LOOP A (USDT -> BTC): Deploy {deploy_pct:.0f}% of 10% USDT Sleeve ({eq_pct:.1f}% equity) on reclaim; exit > P_buy."
    elif sig_str == "LOOP B: BTC -> USDT" and sizing > 0:
        eq_pct = round(sizing * 10.0, 1)
        tgt_btc = round(10.0 - eq_pct, 1)
        tgt_usdt = round(10.0 + eq_pct, 1)
        deploy_pct = round(sizing * 100.0, 1)
        instr = f"LOOP B (BTC -> USDT): Rotate {deploy_pct:.0f}% of 10% BTC Sleeve ({eq_pct:.1f}% equity) into USDT; rebuy < P_sell."
    else:
        tgt_btc, tgt_usdt, deploy_pct = 10.0, 10.0, 0.0
        instr = "HOLD BOTH SLEEVES: Keep permanent 10% USDT + 10% BTC Sandbox balanced (80% Core untouched) until Loop A/B confirms."

    l_entry = float(lower["price_level"]) if lower else float(m["swing_low_4h"])
    u_entry = float(upper["price_level"]) if upper else float(m["swing_high_4h"])
    loop_a_zone = f"Washout ${min(l_entry, m['swing_low_4h']):,.0f}–${max(l_entry, m['swing_low_4h']):,.0f} -> Profit Exit > ${max(m['daily_vwap'], m['swing_high_4h']):,.0f}"
    loop_b_zone = f"Squeeze ${min(u_entry, m['swing_high_4h']):,.0f}–${max(u_entry, m['swing_high_4h']):,.0f} -> Rebuy < ${min(m['daily_vwap'], m['swing_low_4h']):,.0f}"

    verdict = f"[{best['name']}] {best['diagnosis']}. {instr}"
    notes = f"{best['diagnosis']}. Rule Score: {best['majority_score']}. LSCE: {lsce['status']}. Dominant Magnet: {magnets['dominant_magnet_reason']}."

    return {
        "data_quality": "LIVE",
        "metrics": m,
        "lsce": lsce,
        "magnets": magnets,
        "regime_diagnosis": {
            "regime_id": best["regime_id"],
            "name": best["name"],
            "diagnosis": best["diagnosis"],
            "playbook": best["playbook"],
            "suitability": best["suitability"],
            "majority_score": best["majority_score"],
            "matched_criteria": best["matched"],
            "all_5_candidates": cls_res["all_5_candidates"],
            "notes": notes,
            "plain_english_verdict": verdict,
        },
        "dibse": {
            "dibse_signal": sig_str,
            "dibse_headline": best["action"],
            "rotation": best["rotation"],
            "sizing_factor": sizing,
            "recommended_cash_deploy_pct": deploy_pct,
            "active_sandbox_pct": 20.0,
            "usdt_sleeve_pct": 10.0,
            "btc_sleeve_pct": 10.0,
            "untouched_core_pct": 80.0,
            "target_btc_allocation_pct": tgt_btc,
            "target_usdt_reserve_pct": tgt_usdt,
            "loop_a_zone": loop_a_zone,
            "loop_b_zone": loop_b_zone,
            "sleeve_allocation": "10% USDT Sleeve + 10% BTC Sleeve (20% Active Sandbox | 80% Untouched Core)",
            "actionable_trade_instruction": instr,
            "stop_rule": "ZERO STOP-LOSSES (DIBSE Asymmetric Self-Healing Inventory)",
            "structural_invalidation_level": m["swing_low_4h"],
            "failure_protocol": "Underwater Loop A holds Spot BTC inventory (> P_buy); bypassed Loop B holds Spot USDT (< P_sell).",
        },
    }
