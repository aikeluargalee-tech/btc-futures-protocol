"""Multi-Factor Regime Analysis Engine (Section 3 of BTC Futures Swing Protocol v1.0)."""
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
    realized_vol_annualized,
    roc,
    rolling_rv_series,
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
    """Group 1 (30%): Daily & 4H HH/HL structure, 50/200 EMA alignment, swing anchor location."""
    d_closes = [c["close"] for c in d1]
    h4_closes = [c["close"] for c in h4]

    d_struct = analyze_structure(d1[-90:], left=3, right=3)
    h4_struct = analyze_structure(h4[-120:], left=3, right=3)

    ema50_d = ema_series(d_closes, 50)
    ema200_d = ema_series(d_closes, 200)
    e50 = ema50_d[-1] if ema50_d else None
    e200 = ema200_d[-1] if ema200_d else None

    ema_score = 50.0
    ema_detail = "Insufficient daily bars for 50/200 EMA"
    if e50 is not None and e200 is not None:
        pts = 50.0
        pts += 15.0 if price > e50 else -15.0
        pts += 15.0 if price > e200 else -15.0
        pts += 12.0 if e50 > e200 else -12.0
        if len(ema50_d) >= 6:
            pts += 8.0 if ema50_d[-1] > ema50_d[-6] else -8.0
        ema_score = _clamp(pts)
        ema_detail = f"P={price:,.0f} vs EMA50={e50:,.0f}, EMA200={e200:,.0f}"
    elif e50 is not None:
        pts = 50.0 + (20.0 if price > e50 else -20.0)
        ema_score = _clamp(pts)
        ema_detail = f"P={price:,.0f} vs EMA50={e50:,.0f} (EMA200 unavailable)"

    # Location relative to key swing anchors (60d range + weekly open)
    anchor_score = 50.0
    recent_d = d1[-60:] if len(d1) >= 60 else d1
    hi60 = max(c["high"] for c in recent_d)
    lo60 = min(c["low"] for c in recent_d)
    rng_pos = (price - lo60) / (hi60 - lo60) if hi60 > lo60 else 0.5
    anchor_score = _clamp(rng_pos * 100.0)

    # Combine: Daily structure (35%), 4H structure (25%), 50/200 EMA alignment (25%), Swing anchor location (15%)
    score = round(
        0.35 * d_struct["score"]
        + 0.25 * h4_struct["score"]
        + 0.25 * ema_score
        + 0.15 * anchor_score,
        2,
    )
    return {
        "score": score,
        "daily_structure": d_struct["state"],
        "h4_structure": h4_struct["state"],
        "ema50_d": round(e50, 1) if e50 else None,
        "ema200_d": round(e200, 1) if e200 else None,
        "range_60d_pct": round(rng_pos * 100.0, 1),
        "components": {
            "daily_structure_score": d_struct["score"],
            "h4_structure_score": h4_struct["score"],
            "ema_alignment_score": round(ema_score, 1),
            "swing_anchor_score": round(anchor_score, 1),
        },
        "summary": f"1D={d_struct['state']}, 4H={h4_struct['state']}, {ema_detail}",
    }


def _score_rsi_regime(val: float | None) -> float:
    """Oscillator in regime (healthy trend zone scores higher than extreme overbought/oversold)."""
    if val is None:
        return 50.0
    if 55.0 <= val <= 72.0:
        return _map_linear(val, 55.0, 72.0, 68.0, 88.0)
    if val > 72.0:
        # Overbought tempering (still bullish, capped from overheating)
        return _map_linear(val, 72.0, 90.0, 88.0, 66.0)
    if 28.0 <= val < 45.0:
        return _map_linear(val, 28.0, 45.0, 12.0, 32.0)
    if val < 28.0:
        return _map_linear(val, 10.0, 28.0, 34.0, 12.0)
    return _map_linear(val, 45.0, 55.0, 32.0, 68.0)


def _score_momentum_breadth(
    d1: list[dict[str, float]],
    h4: list[dict[str, float]],
    eth_d1: list[dict[str, float]],
    macro: dict[str, Any],
) -> dict[str, Any]:
    """Group 2 (25%): Daily & 4H oscillators, 10-20p ROC, relative strength vs SPX/NDX & ETH."""
    d_closes = [c["close"] for c in d1]
    h4_closes = [c["close"] for c in h4]

    rsi_d = rsi(d_closes, 14)
    rsi_4h = rsi(h4_closes, 14)
    osc_score = 0.55 * _score_rsi_regime(rsi_d) + 0.45 * _score_rsi_regime(rsi_4h)

    roc10_d = roc(d_closes, 10)
    roc20_d = roc(d_closes, 20)
    roc10_4h = roc(h4_closes, 10)
    roc20_4h = roc(h4_closes, 20)

    roc_scores: list[float] = []
    if roc10_d is not None:
        roc_scores.append(_map_linear(roc10_d, -12.0, 12.0))
    if roc20_d is not None:
        roc_scores.append(_map_linear(roc20_d, -18.0, 18.0))
    if roc10_4h is not None:
        roc_scores.append(_map_linear(roc10_4h, -6.0, 6.0))
    if roc20_4h is not None:
        roc_scores.append(_map_linear(roc20_4h, -10.0, 10.0))
    roc_score = sum(roc_scores) / len(roc_scores) if roc_scores else 50.0

    # Relative strength vs risk assets (SPX/NDX) and BTC dominance proxy (BTC vs ETH)
    rs_parts: list[float] = []
    btc_vs_spx = None
    if roc10_d is not None and (macro.get("spx") or {}).get("roc10_pct") is not None:
        btc_vs_spx = round(roc10_d - macro["spx"]["roc10_pct"], 2)
        rs_parts.append(_map_linear(btc_vs_spx, -10.0, 10.0))
    btc_vs_eth = None
    if roc10_d is not None and len(eth_d1) > 12:
        eth_roc10 = roc([c["close"] for c in eth_d1], 10)
        if eth_roc10 is not None:
            btc_vs_eth = round(roc10_d - eth_roc10, 2)
            # Outperforming ETH adds resilience; mild weight
            rs_parts.append(_map_linear(btc_vs_eth, -8.0, 8.0, 35.0, 65.0))
    rs_score = sum(rs_parts) / len(rs_parts) if rs_parts else 50.0

    score = round(0.35 * osc_score + 0.40 * roc_score + 0.25 * rs_score, 2)
    return {
        "score": score,
        "rsi_d": rsi_d,
        "rsi_4h": rsi_4h,
        "roc10_d_pct": round(roc10_d, 2) if roc10_d is not None else None,
        "roc20_d_pct": round(roc20_d, 2) if roc20_d is not None else None,
        "roc10_4h_pct": round(roc10_4h, 2) if roc10_4h is not None else None,
        "btc_vs_spx_10d_pct": btc_vs_spx,
        "btc_vs_eth_10d_pct": btc_vs_eth,
        "components": {
            "oscillator_score": round(osc_score, 1),
            "roc_score": round(roc_score, 1),
            "relative_strength_score": round(rs_score, 1),
        },
        "summary": f"RSI(1D/4H)={rsi_d}/{rsi_4h}, ROC10D={roc10_d:.1f}%" if roc10_d is not None else "Momentum partial",
    }


def _score_volatility_liquidity(
    d1: list[dict[str, float]],
    h4: list[dict[str, float]],
    derivatives: dict[str, Any],
) -> dict[str, Any]:
    """Group 3 (25%): 20/60p RV percentile, ATR regime, volume participation, funding extremity."""
    d_closes = [c["close"] for c in d1]

    rv20_series = rolling_rv_series(d_closes, 20, 365.0)
    rv60_series = rolling_rv_series(d_closes, 60, 365.0)
    rv20 = rv20_series[-1] if rv20_series else realized_vol_annualized(d_closes, 20, 365.0)
    rv60 = rv60_series[-1] if rv60_series else realized_vol_annualized(d_closes, 60, 365.0)
    rv20_pct = percentile_rank(rv20, rv20_series[-252:]) if (rv20 is not None and rv20_series) else None
    rv60_pct = percentile_rank(rv60, rv60_series[-252:]) if (rv60 is not None and rv60_series) else None

    # Contained volatility (20th-60th percentile) scores high (70-85); extreme expansion (>85th) or drought (<10th) scores low
    def _rv_score(p: float | None) -> float:
        if p is None:
            return 50.0
        if 20.0 <= p <= 60.0:
            return 78.0
        if p < 20.0:
            # Compression / low liquidity drought
            return _map_linear(p, 0.0, 20.0, 35.0, 72.0)
        if p <= 80.0:
            return _map_linear(p, 60.0, 80.0, 78.0, 48.0)
        return _map_linear(p, 80.0, 100.0, 48.0, 12.0)

    rv_score = 0.55 * _rv_score(rv20_pct) + 0.45 * _rv_score(rv60_pct)

    # ATR regime: current ATR(14) vs 60d median ATR
    atrs = atr_series(d1, 14)
    atr_cur = atrs[-1] if atrs else atr(d1, 14)
    atr_pct_price = (atr_cur / d_closes[-1] * 100.0) if (atr_cur and d_closes) else None
    atr_ratio = None
    atr_score = 50.0
    if len(atrs) >= 30 and atr_cur:
        med_atr = statistics.median(atrs[-60:])
        atr_ratio = round(atr_cur / med_atr, 2) if med_atr > 0 else 1.0
        if 0.75 <= atr_ratio <= 1.20:
            atr_score = 75.0
        elif atr_ratio < 0.75:
            atr_score = _map_linear(atr_ratio, 0.4, 0.75, 42.0, 72.0)
        else:
            atr_score = _map_linear(atr_ratio, 1.20, 2.0, 72.0, 18.0)

    # Volume participation on 1D & 4H vs 20-period SMA
    d_vols = [c["volume"] for c in d1]
    h4_vols = [c["volume"] for c in h4]
    d_vol_sma = sma(d_vols[:-1], 20)
    h4_vol_sma = sma(h4_vols[:-1], 20)
    d_vol_ratio = (d_vols[-1] / d_vol_sma) if (d_vols and d_vol_sma) else None
    h4_vol_ratio = (h4_vols[-1] / h4_vol_sma) if (h4_vols and h4_vol_sma) else None
    vol_ratios = [x for x in (d_vol_ratio, h4_vol_ratio) if x is not None]
    vol_avg_ratio = sum(vol_ratios) / len(vol_ratios) if vol_ratios else 1.0
    if 0.85 <= vol_avg_ratio <= 1.80:
        vol_score = _map_linear(vol_avg_ratio, 0.85, 1.80, 58.0, 82.0)
    elif vol_avg_ratio < 0.85:
        vol_score = _map_linear(vol_avg_ratio, 0.30, 0.85, 22.0, 58.0)
    else:
        # Blow-off / climax volume
        vol_score = _map_linear(vol_avg_ratio, 1.80, 3.50, 75.0, 38.0)

    # Funding rate extremity relative to 30d history (90 x 8h periods)
    cur_fund = derivatives.get("current_rate_pct")
    fund_hist = derivatives.get("history_pct") or []
    fund_pct_rank = percentile_rank(cur_fund, fund_hist) if (cur_fund is not None and fund_hist) else None
    fund_score = 50.0
    if cur_fund is not None:
        if fund_pct_rank is not None:
            # Neutral-to-mildly positive balanced funding (25th-75th pct) = healthy
            if 25.0 <= fund_pct_rank <= 75.0:
                fund_score = 68.0
            elif fund_pct_rank > 90.0 or cur_fund >= 0.03:
                fund_score = 22.0  # Overheated crowded longs
            elif fund_pct_rank < 10.0 or cur_fund <= -0.02:
                fund_score = 35.0  # Crowded shorts / cascade stress
            else:
                fund_score = 52.0
        else:
            fund_score = 65.0 if -0.005 <= cur_fund <= 0.015 else 35.0

    score = round(0.35 * rv_score + 0.25 * atr_score + 0.25 * vol_score + 0.15 * fund_score, 2)
    return {
        "score": score,
        "rv20_ann_pct": round(rv20, 1) if rv20 is not None else None,
        "rv60_ann_pct": round(rv60, 1) if rv60 is not None else None,
        "rv20_percentile": rv20_pct,
        "rv60_percentile": rv60_pct,
        "atr14_d_usd": round(atr_cur, 1) if atr_cur else None,
        "atr14_d_pct": round(atr_pct_price, 2) if atr_pct_price else None,
        "atr_vs_60d_med": atr_ratio,
        "volume_ratio_1d": round(d_vol_ratio, 2) if d_vol_ratio is not None else None,
        "volume_ratio_4h": round(h4_vol_ratio, 2) if h4_vol_ratio is not None else None,
        "funding_rate_pct": cur_fund,
        "funding_30d_percentile": fund_pct_rank,
        "components": {
            "rv_percentile_score": round(rv_score, 1),
            "atr_regime_score": round(atr_score, 1),
            "volume_participation_score": round(vol_score, 1),
            "funding_extremity_score": round(fund_score, 1),
        },
        "summary": f"RV20pct={rv20_pct}, ATRx={atr_ratio}, Vol={vol_avg_ratio:.2f}x, Fund={cur_fund}%",
    }


def _score_macro_external(
    macro: dict[str, Any],
    etf: dict[str, Any] | None,
    stables: dict[str, Any] | None,
) -> dict[str, Any]:
    """Group 4 (20%): Risk-on/risk-off backdrop, DXY & US10Y trend, ETF & stablecoin flows."""
    # Equities & VIX
    eq_parts: list[float] = []
    for k in ("spx", "ndx"):
        item = macro.get(k)
        if item and item.get("vs_sma20_pct") is not None:
            eq_parts.append(_map_linear(item["vs_sma20_pct"], -4.0, 4.0))
    vix = (macro.get("vix") or {}).get("value")
    if vix is not None:
        # Low VIX (<16) risk-on -> ~75; elevated VIX (>28) risk-off -> ~20
        eq_parts.append(_map_linear(vix, 30.0, 14.0, 15.0, 82.0))
    risk_score = sum(eq_parts) / len(eq_parts) if eq_parts else 50.0

    # Dollar (DXY) & US 10Y yield trend (falling = supportive for BTC)
    rates_parts: list[float] = []
    dxy = macro.get("dxy")
    if dxy and dxy.get("roc10_pct") is not None:
        rates_parts.append(_map_linear(dxy["roc10_pct"], 2.5, -2.5, 15.0, 85.0))
    us10y = macro.get("us10y")
    if us10y and us10y.get("roc10_pct") is not None:
        rates_parts.append(_map_linear(us10y["roc10_pct"], 8.0, -8.0, 20.0, 80.0))
    rates_score = sum(rates_parts) / len(rates_parts) if rates_parts else 50.0

    # ETF & Stablecoin flows
    flow_parts: list[float] = []
    if etf and etf.get("sum5_usd_m") is not None:
        flow_parts.append(_map_linear(etf["sum5_usd_m"], -1000.0, 1000.0, 12.0, 88.0))
    if stables and stables.get("chg7d_pct") is not None:
        flow_parts.append(_map_linear(stables["chg7d_pct"], -1.5, 1.5, 20.0, 80.0))
    flow_score = sum(flow_parts) / len(flow_parts) if flow_parts else 50.0

    # Weighted blend within Macro/External
    score = round(0.40 * risk_score + 0.30 * rates_score + 0.30 * flow_score, 2)
    return {
        "score": score,
        "vix": vix,
        "dxy": (dxy or {}).get("value"),
        "us10y": (us10y or {}).get("value"),
        "spx_vs_20d_pct": (macro.get("spx") or {}).get("vs_sma20_pct"),
        "etf_5d_usd_m": etf.get("sum5_usd_m") if etf else None,
        "stables_7d_pct": stables.get("chg7d_pct") if stables else None,
        "components": {
            "risk_on_off_score": round(risk_score, 1),
            "yield_dollar_score": round(rates_score, 1),
            "etf_stable_flow_score": round(flow_score, 1),
        },
        "summary": f"VIX={vix}, DXY={(dxy or {}).get('value')}, ETF5d={etf.get('sum5_usd_m') if etf else 'n/a'}M",
    }


def compute_regime(
    market_data: dict[str, Any],
    cfg: dict[str, Any],
    dd_tier1_active: bool = False,
    prev_regime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute continuous 0-100 multi-factor regime score and dominant factors."""
    d1 = market_data["klines"]["1d"]
    h4 = market_data["klines"]["4h"]
    eth_d1 = market_data["klines"].get("eth_1d") or []
    price = market_data["ticker"].get("price") or (d1[-1]["close"] if d1 else 0.0)

    if len(d1) < 30 or len(h4) < 30 or not price:
        return {
            "ok": False,
            "score": 50.0,
            "bias": "NEUTRAL",
            "reason": "Insufficient OHLCV history",
            "groups": {},
            "dominant_factors": [],
        }

    g1 = _score_trend_structure(d1, h4, price)
    g2 = _score_momentum_breadth(d1, h4, eth_d1, market_data.get("macro") or {})
    g3_raw = _score_volatility_liquidity(d1, h4, market_data.get("derivatives") or {})
    g4 = _score_macro_external(
        market_data.get("macro") or {},
        market_data.get("etf"),
        market_data.get("stables"),
    )

    weights = cfg["regime"]["weights"]
    dir_weight_sum = weights["trend_structure"] + weights["momentum_breadth"] + weights["macro_external"]
    dir_mean = (
        weights["trend_structure"] * g1["score"]
        + weights["momentum_breadth"] * g2["score"]
        + weights["macro_external"] * g4["score"]
    ) / max(dir_weight_sum, 1e-6)
    # Volatility & Liquidity quality (0-100): high quality reinforces directional bias; extreme vol/drought dampens toward 50
    lean = max(-1.0, min(1.0, (dir_mean - 50.0) / 15.0))
    vol_quality = g3_raw["score"]
    vol_directional = round(50.0 + lean * (vol_quality - 50.0), 2)
    g3 = {**g3_raw, "quality_score": vol_quality, "score": vol_directional}

    total = round(
        weights["trend_structure"] * g1["score"]
        + weights["momentum_breadth"] * g2["score"]
        + weights["volatility_liquidity"] * g3["score"]
        + weights["macro_external"] * g4["score"],
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
        bias = "LONG_ELIGIBLE"
    elif total <= short_th:
        bias = "SHORT_ELIGIBLE"
    else:
        bias = "NEUTRAL"

    groups = {
        "trend_structure": {"weight": weights["trend_structure"], **g1},
        "momentum_breadth": {"weight": weights["momentum_breadth"], **g2},
        "volatility_liquidity": {"weight": weights["volatility_liquidity"], **g3},
        "macro_external": {"weight": weights["macro_external"], **g4},
    }

    # Dominant factors driving the score away from 50
    contributions = []
    labels = {
        "trend_structure": "Trend Structure",
        "momentum_breadth": "Momentum & Breadth",
        "volatility_liquidity": "Volatility & Liquidity",
        "macro_external": "Macro / External Context",
    }
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

    # Track UTC daily recalculation + HTF structural break
    now_utc = dt.datetime.now(dt.timezone.utc)
    utc_day = now_utc.strftime("%Y-%m-%d")
    htf_break = False
    if prev_regime:
        prev_ds = ((prev_regime.get("groups") or {}).get("trend_structure") or {}).get("daily_structure")
        prev_h4 = ((prev_regime.get("groups") or {}).get("trend_structure") or {}).get("h4_structure")
        if (prev_ds and prev_ds != g1["daily_structure"]) or (prev_h4 and prev_h4 != g1["h4_structure"]):
            htf_break = True

    return {
        "ok": True,
        "score": total,
        "bias": bias,
        "thresholds": {
            "long": long_th,
            "short": short_th,
            "dd_tier1_active": dd_tier1_active,
            "strong_long": cfg["regime"]["strong_alignment_long"],
            "strong_short": cfg["regime"]["strong_alignment_short"],
        },
        "groups": groups,
        "contributions": contributions,
        "dominant_factors": dominant,
        "recalc_utc_day": utc_day,
        "recalc_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "htf_structural_break": htf_break,
    }
