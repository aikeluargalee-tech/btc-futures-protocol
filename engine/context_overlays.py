"""Zero-API deterministic context overlays: Project ETF, Project L (Market Time), and Project H (Patient Money)."""
from __future__ import annotations

import datetime as dt
from typing import Any

# Project L — Independently verified on 16,570 hourly BTCUSDT bars (Zero directional edge).
EXPECTED_DAY_RANGE_PCT: dict[int, tuple[str, float]] = {
    0: ("Mon", 3.65),
    1: ("Tue", 3.30),
    2: ("Wed", 3.45),
    3: ("Thu", 3.50),
    4: ("Fri", 3.98),
    5: ("Sat", 1.91),
    6: ("Sun", 2.79),
}


def compute_etf_flow_regime(
    market: dict[str, Any],
    spot_magnet: dict[str, Any] | None = None,
    news_macro: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify Spot ETF flows against OI, funding, and Spot CVD (Project ETF)."""
    farside = market.get("etf") or {}
    cmc_etf = ((news_macro or {}).get("crypto_pulse") or {}).get("cmc_etf") or {}
    drv = market.get("derivatives") or {}
    sm_m = (spot_magnet or {}).get("metrics") or {}

    etf_1d = farside.get("latest_usd_m")
    if etf_1d in (None, 0.0) and cmc_etf.get("btc_latest_usd_m") is not None:
        etf_1d = cmc_etf.get("btc_latest_usd_m")
    etf_5d = farside.get("sum5_usd_m")
    if etf_5d is None and cmc_etf.get("btc_5d_sum_usd_m") is not None:
        etf_5d = cmc_etf.get("btc_5d_sum_usd_m")

    oi_delta = sm_m.get("oi_change_24h_pct")
    if oi_delta is None:
        oi_delta = drv.get("btc_oi_change_pct_24h")
    if oi_delta is None:
        oi_delta = drv.get("btc_oi_change_pct_3d")

    funding_8h = drv.get("current_rate_pct")
    spot_cvd_ratio = sm_m.get("spot_cvd_ratio")
    spot_cvd_7d = sm_m.get("spot_cvd_slope_7d")

    if etf_5d is None or oi_delta is None or funding_8h is None:
        return {
            "status": "unavailable",
            "regime": "UNAVAILABLE",
            "reason": "Missing ETF 5D flow, OI delta, or funding rate",
            "guardrail": "Diagnostic flow regime only — never issue a trade or size from ETF flows alone.",
        }

    e5 = float(etf_5d)
    e1 = float(etf_1d) if isinstance(etf_1d, (int, float)) else None
    oi = float(oi_delta)
    f8 = float(funding_8h)
    cvd_r = float(spot_cvd_ratio) if isinstance(spot_cvd_ratio, (int, float)) else None
    cvd_7 = float(spot_cvd_7d) if isinstance(spot_cvd_7d, (int, float)) else None

    outflow_heavy = e5 <= -150.0 or (e1 is not None and e1 <= -100.0 and e5 < 0.0)
    inflow_heavy = e5 >= 150.0 or (e1 is not None and e1 >= 100.0 and e5 > 0.0)
    spot_absorbing = (cvd_r is not None and cvd_r >= 1.03) and (cvd_7 is None or cvd_7 >= -1000.0)

    if outflow_heavy:
        if f8 < 0.0 and spot_absorbing:
            regime = "ABSORPTION"
            detail = "Heavy ETF outflows while funding < 0 and Spot CVD improves — possible selling exhaustion / spot absorption."
        elif oi > 1.0:
            regime = "NEW SHORTS"
            detail = "Heavy ETF outflows paired with expanding perp OI — directional short leverage building alongside redemptions."
        elif oi < -1.0 and f8 <= 0.01:
            regime = "CARRY UNWIND"
            detail = "ETF outflows + falling OI + muted/negative funding — consistent with price-insensitive cash-and-carry basis unwinding, not pure panic."
        else:
            regime = "MIXED"
            detail = "Heavy ETF outflows without uniform OI contraction or spot absorption."
    elif inflow_heavy:
        if oi > 1.0 and f8 > 0.015:
            regime = "CARRY BUILD"
            detail = "ETF inflows alongside rising OI and elevated positive funding — likely mixed institutional demand + fresh basis carry."
        else:
            regime = "SPOT-LED INFLOWS"
            detail = "Net positive ETF inflows without extreme perp leverage buildup."
    else:
        regime = "NEUTRAL"
        detail = "ETF flows balanced; neither large basis unwind nor aggressive institutional creation."

    return {
        "status": "LIVE",
        "regime": regime,
        "detail": detail,
        "inputs": {
            "etf_1d_usd_m": round(e1, 1) if e1 is not None else None,
            "etf_5d_usd_m": round(e5, 1),
            "oi_delta_pct": round(oi, 2),
            "funding_8h_pct": round(f8, 5),
            "spot_cvd_ratio": round(cvd_r, 3) if cvd_r is not None else None,
            "spot_cvd_slope_7d": round(cvd_7, 1) if cvd_7 is not None else None,
        },
        "summary_line": f"ETF Flow Regime: {regime} (5D ${e5:+,.1f}M | OI {oi:+.2f}% | Fund {f8:+.4f}%)",
        "guardrail": "Diagnostic label only — must display raw inputs and never issues an entry.",
    }


def compute_market_time_profile(
    market: dict[str, Any],
    signal: dict[str, Any] | None = None,
    now_utc: dt.datetime | None = None,
) -> dict[str, Any]:
    """Evaluate Project L session activity & expected day range vs stop width (zero directional edge)."""
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    day_name, exp_day_pct = EXPECTED_DAY_RANGE_PCT[now.weekday()]
    is_weekend = now.weekday() >= 5
    hr = now.hour

    if now.weekday() == 0 and hr in (0, 1):
        awake_state = "MON_GAP_RISK"
        exp_hour_pct = 1.05
    elif not is_weekend and 13 <= hr <= 16:
        awake_state = "PEAK_AWAKE"
        exp_hour_pct = 1.01
    elif not is_weekend and 4 <= hr <= 7:
        awake_state = "QUIET_EXEC"
        exp_hour_pct = 0.52
    elif hr in (10, 11) or is_weekend:
        awake_state = "QUIET_THIN"
        exp_hour_pct = 0.38 if is_weekend else 0.46
    else:
        awake_state = "ACTIVE"
        exp_hour_pct = 0.70

    # Volatility clustering check: after > 2% closed 1H bar, next hour averages 1.69% vs 0.62% baseline.
    h1_bars = (market.get("klines") or {}).get("1h") or []
    last_1h_range_pct: float | None = None
    vol_cluster = False
    if h1_bars:
        last_h1 = h1_bars[-1]
        op = float(last_h1.get("open") or 0.0)
        hi = float(last_h1.get("high") or 0.0)
        lo = float(last_h1.get("low") or 0.0)
        if op > 0:
            last_1h_range_pct = round(((hi - lo) / op) * 100.0, 2)
            vol_cluster = last_1h_range_pct >= 2.0

    prop = (signal or {}).get("proposal") or {}
    stop_pct = prop.get("stop_distance_pct")
    stop_vs_day_x: float | None = None
    stop_noise_warning = False
    if isinstance(stop_pct, (int, float)) and exp_day_pct > 0:
        stop_vs_day_x = round(float(stop_pct) / exp_day_pct, 2)
        stop_noise_warning = stop_vs_day_x < 0.55

    return {
        "status": "LIVE",
        "day_of_week": day_name,
        "hour_utc": hr,
        "is_weekend_utc": is_weekend,
        "is_monday_gap_risk": now.weekday() == 0 and hr in (0, 1),
        "is_quiet_exec_window": (not is_weekend) and 4 <= hr <= 7,
        "awake_state": awake_state,
        "expected_day_range_pct": exp_day_pct,
        "expected_hour_range_pct": exp_hour_pct,
        "weekday_vs_weekend_mult": 1.61,
        "last_1h_range_pct": last_1h_range_pct,
        "vol_cluster_active": vol_cluster,
        "proposal_stop_vs_day_range_x": stop_vs_day_x,
        "stop_noise_warning": stop_noise_warning,
        "summary_line": f"{day_name} ~{exp_day_pct:.2f}% day · {hr:02d}Z {awake_state}" + (" · >2% 1H VOL CLUSTER" if vol_cluster else ""),
        "guardrail": "Tells whether liquidity is awake & if stop is tight vs day range — zero directional prediction.",
    }


def compute_patient_money_h(
    market: dict[str, Any],
    cortex_rhyme: dict[str, Any] | None = None,
    spot_magnet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute Project H zero-API proxies: Dollar-Weighted Funding ($/8h) and Aggression x OI state."""
    drv = market.get("derivatives") or {}
    sm_m = (spot_magnet or {}).get("metrics") or {}
    cr_m = ((cortex_rhyme or {}).get("current_state") or {}).get("raw_metrics") or {}
    price = (market.get("ticker") or {}).get("price") or sm_m.get("price")

    funding_8h = drv.get("current_rate_pct")
    cmc_real = ((drv.get("cmc_liquidations") or {}).get("realized") or {})
    oi_usd_b = cmc_real.get("global_btc_oi_usd_b")
    if isinstance(oi_usd_b, (int, float)) and oi_usd_b > 0:
        oi_usd = float(oi_usd_b) * 1e9
        oi_source = "CMC Global BTC OI"
    elif isinstance(drv.get("total_oi_btc"), (int, float)) and isinstance(price, (int, float)) and price > 0:
        oi_usd = float(drv["total_oi_btc"]) * float(price)
        oi_source = "Multi-Venue Tracked OI"
    else:
        oi_usd = None
        oi_source = "unavailable"

    funding_8h_usd: float | None = None
    funding_24h_usd: float | None = None
    crowd_payer: str | None = None
    if isinstance(funding_8h, (int, float)) and oi_usd is not None:
        funding_8h_usd = round((float(funding_8h) / 100.0) * oi_usd, 0)
        funding_24h_usd = funding_8h_usd * 3.0
        crowd_payer = "Longs paying Shorts" if funding_8h_usd >= 0 else "Shorts paying Longs"

    carry_apr_pct: float | None = None
    carry_status = "UNAVAILABLE"
    carry_summary: str | None = None
    if isinstance(funding_8h, (int, float)):
        carry_apr_pct = round(float(funding_8h) * 3.0 * 365.0, 2)
        if carry_apr_pct < 2.0:
            carry_status = "DEAD (<2%)"
        elif carry_apr_pct < 6.0:
            carry_status = "BELOW T-BILL (2-6%)"
        elif carry_apr_pct < 10.0:
            carry_status = "MODERATE (6-10%)"
        else:
            carry_status = "ATTRACTIVE (>=10%)"
        carry_summary = f"Carry APR {carry_apr_pct:+.2f}% ({carry_status})"

    tbr = cr_m.get("taker_buy_ratio")
    if tbr is None and isinstance(sm_m.get("spot_cvd_ratio"), (int, float)) and sm_m["spot_cvd_ratio"] > 0:
        r = float(sm_m["spot_cvd_ratio"])
        tbr = round(r / (1.0 + r), 4)

    oi_delta = drv.get("btc_oi_change_pct_24h")
    if oi_delta is None:
        oi_delta = cr_m.get("oi_delta_24h_pct")
    if oi_delta is None:
        oi_delta = drv.get("btc_oi_change_pct_3d")

    aggression_state = "UNAVAILABLE"
    if isinstance(tbr, (int, float)) and isinstance(oi_delta, (int, float)):
        tb = float(tbr)
        od = float(oi_delta)
        if abs(tb - 0.50) < 0.015 or abs(od) < 0.4:
            aggression_state = "BALANCED"
        elif tb > 0.50 and od > 0.0:
            aggression_state = "NEW LONGS ENTERING"
        elif tb > 0.50 and od < 0.0:
            aggression_state = "SHORT COVERING"
        elif tb < 0.50 and od > 0.0:
            aggression_state = "NEW SHORTS ENTERING"
        else:
            aggression_state = "LONG UNWIND"

    return {
        "status": "LIVE" if (funding_8h_usd is not None or carry_apr_pct is not None or aggression_state != "UNAVAILABLE") else "unavailable",
        "oi_usd_b": round(oi_usd / 1e9, 2) if oi_usd else None,
        "oi_source": oi_source,
        "funding_8h_usd": funding_8h_usd,
        "funding_24h_usd": funding_24h_usd,
        "crowd_payer": crowd_payer,
        "carry_apr_pct": carry_apr_pct,
        "carry_status": carry_status,
        "carry_summary": carry_summary,
        "taker_buy_ratio": round(float(tbr), 4) if isinstance(tbr, (int, float)) else None,
        "oi_delta_24h_pct": round(float(oi_delta), 2) if isinstance(oi_delta, (int, float)) else None,
        "aggression_oi_state": aggression_state,
        "guardrail": "Dollar crowding & aggression-vs-OI context — complements Project G without predicting direction.",
    }


def compute_context_overlays(
    market: dict[str, Any],
    signal: dict[str, Any] | None = None,
    spot_magnet: dict[str, Any] | None = None,
    cortex_rhyme: dict[str, Any] | None = None,
    news_macro: dict[str, Any] | None = None,
    now_utc: dt.datetime | None = None,
) -> dict[str, Any]:
    """Compute Project ETF, Project L, and Project H micro-integrations."""
    return {
        "etf_flow_regime": compute_etf_flow_regime(market, spot_magnet=spot_magnet, news_macro=news_macro),
        "market_time_l": compute_market_time_profile(market, signal=signal, now_utc=now_utc),
        "patient_money_h": compute_patient_money_h(market, cortex_rhyme=cortex_rhyme, spot_magnet=spot_magnet),
    }
