"""4H Multi-Factor Regime Engine (Section 4 of BTC Short-Term Futures + Inventory Protocol v4.0)."""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Any

from .indicators import (
    analyze_structure,
    atr,
    atr_series,
    ema_series,
    percentile_rank,
    roc,
    rsi,
    sma,
)


def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


def _map_linear(val: float, low_in: float, high_in: float, low_out: float = 0.0, high_out: float = 100.0) -> float:
    if high_in == low_in:
        return 50.0
    t = (val - low_in) / (high_in - low_in)
    return _clamp(low_out + t * (high_out - low_out), min(low_out, high_out), max(low_out, high_out))


def _score_trend_structure(d1: list[dict[str, float]], h4: list[dict[str, float]], price: float) -> dict[str, Any]:
    """Group 1 (30%): 4H swing structure + alignment with daily bias (1D structure + 50/200 EMA)."""
    d_closes = [c["close"] for c in d1]
    h4_closes = [c["close"] for c in h4]

    h4_struct = analyze_structure(h4[-120:], left=3, right=3)
    d_struct = analyze_structure(d1[-90:], left=3, right=3)

    ema50_d = ema_series(d_closes, 50)
    ema200_d = ema_series(d_closes, 200)
    ema20_4h = ema_series(h4_closes, 20)
    ema50_4h = ema_series(h4_closes, 50)

    e50_d = ema50_d[-1] if ema50_d else None
    e200_d = ema200_d[-1] if ema200_d else None
    e20_4h = ema20_4h[-1] if ema20_4h else None
    e50_4h = ema50_4h[-1] if ema50_4h else None

    daily_ema_score = 50.0
    if e50_d is not None and e200_d is not None:
        pts = 50.0
        pts += 16.0 if price > e50_d else -16.0
        pts += 14.0 if price > e200_d else -14.0
        pts += 12.0 if e50_d > e200_d else -12.0
        if len(ema50_d) >= 5:
            pts += 8.0 if ema50_d[-1] > ema50_d[-5] else -8.0
        daily_ema_score = _clamp(pts)
    elif e50_d is not None:
        daily_ema_score = _clamp(50.0 + (22.0 if price > e50_d else -22.0))

    h4_ema_score = 50.0
    if e20_4h is not None and e50_4h is not None:
        pts4 = 50.0
        pts4 += 18.0 if price > e20_4h else -18.0
        pts4 += 16.0 if price > e50_4h else -16.0
        pts4 += 16.0 if e20_4h > e50_4h else -16.0
        h4_ema_score = _clamp(pts4)

    daily_bias_score = round(0.50 * d_struct["score"] + 0.50 * daily_ema_score, 2)
    daily_bias = "BULL" if daily_bias_score >= 58.0 else ("BEAR" if daily_bias_score <= 42.0 else "NEUTRAL")

    # 4H swing structure (40%), 4H EMA alignment (25%), Daily bias & EMA alignment (35%)
    score = round(
        0.40 * h4_struct["score"] + 0.25 * h4_ema_score + 0.35 * daily_bias_score,
        2,
    )
    return {
        "score": score,
        "daily_bias": daily_bias,
        "daily_bias_score": daily_bias_score,
        "daily_structure": d_struct["state"],
        "h4_structure": h4_struct["state"],
        "ema20_4h": round(e20_4h, 1) if e20_4h else None,
        "ema50_4h": round(e50_4h, 1) if e50_4h else None,
        "ema50_d": round(e50_d, 1) if e50_d else None,
        "ema200_d": round(e200_d, 1) if e200_d else None,
        "components": {
            "h4_structure_score": h4_struct["score"],
            "h4_ema_score": round(h4_ema_score, 1),
            "daily_structure_score": d_struct["score"],
            "daily_ema_score": round(daily_ema_score, 1),
        },
        "summary": f"4H={h4_struct['state']}, 1D={d_struct['state']} ({daily_bias})",
    }


def _score_rsi_4h(val: float | None) -> float:
    if val is None:
        return 50.0
    if 54.0 <= val <= 72.0:
        return _map_linear(val, 54.0, 72.0, 68.0, 90.0)
    if val > 72.0:
        return _map_linear(val, 72.0, 90.0, 90.0, 68.0)
    if 28.0 <= val < 46.0:
        return _map_linear(val, 28.0, 46.0, 10.0, 32.0)
    if val < 28.0:
        return _map_linear(val, 10.0, 28.0, 32.0, 10.0)
    return _map_linear(val, 46.0, 54.0, 32.0, 68.0)


def _score_momentum_4h(h4: list[dict[str, float]], d1: list[dict[str, float]]) -> dict[str, Any]:
    """Group 2 (25%): 4H momentum regime (RSI 14) and 4H rate-of-change (6p/12p/20p)."""
    h4_closes = [c["close"] for c in h4]
    d_closes = [c["close"] for c in d1]

    rsi_4h = rsi(h4_closes, 14)
    rsi_d = rsi(d_closes, 14)
    osc_score = 0.70 * _score_rsi_4h(rsi_4h) + 0.30 * _score_rsi_4h(rsi_d)

    roc6_4h = roc(h4_closes, 6)    # 24h
    roc12_4h = roc(h4_closes, 12)  # 48h
    roc20_4h = roc(h4_closes, 20)  # ~3.3d

    roc_parts: list[float] = []
    if roc6_4h is not None:
        roc_parts.append(_map_linear(roc6_4h, -4.5, 4.5))
    if roc12_4h is not None:
        roc_parts.append(_map_linear(roc12_4h, -6.5, 6.5))
    if roc20_4h is not None:
        roc_parts.append(_map_linear(roc20_4h, -9.0, 9.0))
    roc_score = sum(roc_parts) / len(roc_parts) if roc_parts else 50.0

    score = round(0.45 * osc_score + 0.55 * roc_score, 2)
    return {
        "score": score,
        "rsi_4h": rsi_4h,
        "rsi_d": rsi_d,
        "roc6_4h_pct": round(roc6_4h, 2) if roc6_4h is not None else None,
        "roc12_4h_pct": round(roc12_4h, 2) if roc12_4h is not None else None,
        "roc20_4h_pct": round(roc20_4h, 2) if roc20_4h is not None else None,
        "components": {
            "h4_oscillator_score": round(osc_score, 1),
            "h4_roc_score": round(roc_score, 1),
        },
        "summary": f"RSI4H={rsi_4h}, ROC6(24h)={roc6_4h:.2f}%" if roc6_4h is not None else "4H Momentum partial",
    }


def _score_volatility_liquidity_4h(h4: list[dict[str, float]], derivatives: dict[str, Any]) -> dict[str, Any]:
    """Group 3 (25%): 4H ATR percentile, 4H relative volume, and perpetual funding."""
    h4_atrs = atr_series(h4, 14)
    atr_cur = h4_atrs[-1] if h4_atrs else atr(h4, 14)
    price = h4[-1]["close"] if h4 else 1.0
    atr_pct = (atr_cur / price * 100.0) if (atr_cur and price) else None
    atr_pct_series = (
        [a / max(c["close"], 1.0) * 100.0 for c, a in zip(h4[-len(h4_atrs):], h4_atrs)]
        if h4_atrs
        else []
    )
    atr_pctile = percentile_rank(atr_pct, atr_pct_series[-120:]) if (atr_pct is not None and atr_pct_series) else None

    # Contained-to-healthy 4H ATR (20th-65th pctile) scores high; extreme expansion (>85th) or dead chop (<10th) scores low
    atr_score = 50.0
    if atr_pctile is not None:
        if 20.0 <= atr_pctile <= 65.0:
            atr_score = 78.0
        elif atr_pctile < 20.0:
            atr_score = _map_linear(atr_pctile, 0.0, 20.0, 35.0, 74.0)
        elif atr_pctile <= 85.0:
            atr_score = _map_linear(atr_pctile, 65.0, 85.0, 78.0, 48.0)
        else:
            atr_score = _map_linear(atr_pctile, 85.0, 100.0, 48.0, 15.0)

    # Relative 4H volume vs 20-bar SMA
    vols = [c["volume"] for c in h4]
    vol_sma = sma(vols[:-1], 20)
    vol_ratio = (vols[-1] / vol_sma) if (vols and vol_sma) else 1.0
    if 0.85 <= vol_ratio <= 2.0:
        vol_score = _map_linear(vol_ratio, 0.85, 2.0, 58.0, 84.0)
    elif vol_ratio < 0.85:
        vol_score = _map_linear(vol_ratio, 0.30, 0.85, 22.0, 58.0)
    else:
        vol_score = _map_linear(vol_ratio, 2.0, 4.0, 76.0, 36.0)

    # Funding rate extremity relative to 30d history
    cur_fund = derivatives.get("current_rate_pct")
    fund_hist = derivatives.get("history_pct") or []
    fund_pctile = percentile_rank(cur_fund, fund_hist) if (cur_fund is not None and fund_hist) else None
    fund_score = 55.0
    if cur_fund is not None:
        if fund_pctile is not None:
            if 20.0 <= fund_pctile <= 80.0:
                fund_score = 72.0
            elif fund_pctile > 90.0 or cur_fund >= 0.03:
                fund_score = 22.0
            elif fund_pctile < 10.0 or cur_fund <= -0.02:
                fund_score = 34.0
            else:
                fund_score = 54.0
        else:
            fund_score = 68.0 if -0.005 <= cur_fund <= 0.015 else 35.0

    quality_score = round(0.45 * atr_score + 0.35 * vol_score + 0.20 * fund_score, 2)
    return {
        "quality_score": quality_score,
        "atr_4h_usd": round(atr_cur, 1) if atr_cur else None,
        "atr_4h_pct": round(atr_pct, 2) if atr_pct else None,
        "atr_4h_percentile": atr_pctile,
        "rel_volume_4h": round(vol_ratio, 2),
        "funding_rate_pct": cur_fund,
        "funding_30d_percentile": fund_pctile,
        "components": {
            "atr_4h_percentile_score": round(atr_score, 1),
            "rel_volume_4h_score": round(vol_score, 1),
            "funding_score": round(fund_score, 1),
        },
        "summary": f"ATR4Hp={atr_pctile}, RelVol4H={vol_ratio:.2f}x, Fund={cur_fund}%",
    }


def _score_session_context(
    now_utc: dt.datetime,
    calendar: list[dict[str, Any]],
    macro: dict[str, Any],
    etf: dict[str, Any] | None,
) -> dict[str, Any]:
    """Group 4 (20%): Session quality (London/NY liquidity vs weekend) + event proximity + macro context."""
    hr = now_utc.hour + now_utc.minute / 60.0
    is_weekend = now_utc.weekday() >= 5

    # Active sessions in UTC: Asia 00-08, London 08-16, NY 13-21, overlap 13-16
    if is_weekend:
        session_name = "WEEKEND"
        session_q = 38.0
    elif 13.0 <= hr < 17.0:
        session_name = "LONDON_NY_OVERLAP"
        session_q = 82.0
    elif 8.0 <= hr < 13.0 or 17.0 <= hr < 21.0:
        session_name = "LONDON_OR_NY"
        session_q = 72.0
    else:
        session_name = "ASIA_OR_OFFHOURS"
        session_q = 58.0

    # Event proximity (60m blackout window, 180m caution)
    next_ev = min(calendar, key=lambda e: abs(e.get("minutes_away", 9999))) if calendar else None
    ev_min = next_ev["minutes_away"] if next_ev else None
    if ev_min is not None and 0.0 <= ev_min <= 60.0:
        event_q = 15.0
    elif ev_min is not None and 60.0 < ev_min <= 180.0:
        event_q = 45.0
    else:
        event_q = 72.0

    # Directional external context (VIX, SPX, DXY, ETF 5d)
    ext_parts: list[float] = []
    if (macro.get("spx") or {}).get("vs_sma20_pct") is not None:
        ext_parts.append(_map_linear(macro["spx"]["vs_sma20_pct"], -3.5, 3.5))
    if (macro.get("dxy") or {}).get("roc10_pct") is not None:
        ext_parts.append(_map_linear(macro["dxy"]["roc10_pct"], 2.0, -2.0, 20.0, 80.0))
    if etf and etf.get("sum5_usd_m") is not None:
        ext_parts.append(_map_linear(etf["sum5_usd_m"], -900.0, 900.0, 15.0, 85.0))
    ext_score = sum(ext_parts) / len(ext_parts) if ext_parts else 50.0

    quality_score = round(0.55 * session_q + 0.45 * event_q, 2)
    return {
        "quality_score": quality_score,
        "external_context_score": round(ext_score, 1),
        "session_name": session_name,
        "is_weekend_utc": is_weekend,
        "next_macro_event": next_ev["title"] if next_ev else None,
        "next_macro_minutes": ev_min,
        "vix": (macro.get("vix") or {}).get("value"),
        "dxy": (macro.get("dxy") or {}).get("value"),
        "etf_5d_usd_m": etf.get("sum5_usd_m") if etf else None,
        "components": {
            "session_quality": round(session_q, 1),
            "event_proximity": round(event_q, 1),
            "external_context": round(ext_score, 1),
        },
        "summary": f"{session_name}, NextEv={f'{ev_min:.0f}m' if ev_min is not None else 'none'}",
    }


def compute_regime(
    market_data: dict[str, Any],
    cfg: dict[str, Any],
    dd_tier1_active: bool = False,
    prev_regime: dict[str, Any] | None = None,
    now_utc: dt.datetime | None = None,
) -> dict[str, Any]:
    """Compute 4H Multi-Factor Regime score (0-100) per Version 4.0."""
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    d1 = market_data["klines"]["1d"]
    h4 = market_data["klines"]["4h"]
    price = market_data["ticker"].get("price") or (h4[-1]["close"] if h4 else 0.0)

    if len(d1) < 30 or len(h4) < 30 or not price:
        return {
            "ok": False,
            "score": 50.0,
            "bias": "FLAT",
            "reason": "Insufficient 1D/4H OHLCV history",
            "groups": {},
            "dominant_factors": [],
        }

    g1 = _score_trend_structure(d1, h4, price)
    g2 = _score_momentum_4h(h4, d1)
    g3_raw = _score_volatility_liquidity_4h(h4, market_data.get("derivatives") or {})
    g4_raw = _score_session_context(
        now,
        market_data.get("macro_calendar") or [],
        market_data.get("macro") or {},
        market_data.get("etf"),
    )

    weights = cfg["regime"]["weights"]
    # Directional anchor from Trend (30%) + Momentum (25%) + External context lean
    dir_core = (
        weights["trend_structure"] * g1["score"]
        + weights["momentum"] * g2["score"]
        + 0.10 * g4_raw["external_context_score"]
    ) / (weights["trend_structure"] + weights["momentum"] + 0.10)
    lean = max(-1.0, min(1.0, (dir_core - 50.0) / 14.0))

    # Quality modulators (Volatility & Liquidity 25%, Session/Context 20%) reinforce clean directional trends & damp poor conditions toward 50
    vol_dir_score = round(50.0 + lean * (g3_raw["quality_score"] - 50.0), 2)
    sess_blend = 0.65 * g4_raw["quality_score"] + 0.35 * g4_raw["external_context_score"]
    sess_dir_score = round(50.0 + lean * (sess_blend - 50.0) * 0.8 + 0.2 * (g4_raw["external_context_score"] - 50.0), 2)
    sess_dir_score = _clamp(sess_dir_score)

    g3 = {**g3_raw, "score": vol_dir_score}
    g4 = {**g4_raw, "score": sess_dir_score}

    total = round(
        weights["trend_structure"] * g1["score"]
        + weights["momentum"] * g2["score"]
        + weights["volatility_liquidity"] * g3["score"]
        + weights["session_context"] * g4["score"],
        2,
    )

    long_th = (
        cfg["circuit_breakers"]["drawdown_tier1_long_threshold"]
        if dd_tier1_active
        else cfg["regime"]["long_threshold"]
    )
    short_th = (
        cfg["circuit_breakers"]["drawdown_tier1_short_threshold"]
        if dd_tier1_active
        else cfg["regime"]["short_threshold"]
    )

    if total >= long_th:
        bias = "LONG"
    elif total <= short_th:
        bias = "SHORT"
    else:
        bias = "FLAT"

    groups = {
        "trend_structure": {"weight": weights["trend_structure"], **g1},
        "momentum": {"weight": weights["momentum"], **g2},
        "volatility_liquidity": {"weight": weights["volatility_liquidity"], **g3},
        "session_context": {"weight": weights["session_context"], **g4},
    }

    labels = {
        "trend_structure": "Trend Structure",
        "momentum": "Momentum",
        "volatility_liquidity": "Volatility & Liquidity",
        "session_context": "Session / Context",
    }
    contributions = []
    for k, g in groups.items():
        impact = round(g["weight"] * (g["score"] - 50.0), 2)
        contributions.append(
            {
                "key": k,
                "label": labels[k],
                "score": g["score"],
                "weight": g["weight"],
                "weighted_impact_vs_50": impact,
            }
        )
    contributions.sort(key=lambda x: abs(x["weighted_impact_vs_50"]), reverse=True)
    dominant = [
        f"{c['label']} ({c['score']:.1f}/100, {c['weighted_impact_vs_50']:+.1f} pts)"
        for c in contributions[:2]
    ]

    last_4h_ts = h4[-1]["ts"]
    last_4h_iso = dt.datetime.fromtimestamp(last_4h_ts / 1000.0, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    htf_break = False
    if prev_regime:
        prev_h4 = ((prev_regime.get("groups") or {}).get("trend_structure") or {}).get("h4_structure")
        if prev_h4 and prev_h4 != g1["h4_structure"]:
            htf_break = True

    return {
        "ok": True,
        "score": total,
        "bias": bias,
        "daily_bias": g1["daily_bias"],
        "thresholds": {
            "long": long_th,
            "short": short_th,
            "dd_tier1_active": dd_tier1_active,
            "weekend_long": cfg["timeframe_and_hold"]["weekend_extreme_long"],
            "weekend_short": cfg["timeframe_and_hold"]["weekend_extreme_short"],
        },
        "groups": groups,
        "contributions": contributions,
        "dominant_factors": dominant,
        "last_4h_close_ts": last_4h_ts,
        "last_4h_close_utc": last_4h_iso,
        "recalc_utc_day": now.strftime("%Y-%m-%d"),
        "recalc_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_weekend_utc": g4_raw["is_weekend_utc"],
        "htf_structural_break": htf_break,
    }
