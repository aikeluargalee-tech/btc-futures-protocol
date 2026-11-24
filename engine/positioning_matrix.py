"""Project G — 8-Cell Funding & OI Positioning Decision Matrix (Context Only).

Source Provenance: Empirical 299 non-overlapping weekly BTCUSDT observations (2021-01-08 -> 2026-09-30)
curated from `Project G Funding & Positioning Reference by Milo1` (cell n sum: 0+4+92+70+18+14+64+37 = 299).
Static reference distribution table; live telemetry only selects which cell matches today's state.
"""
from __future__ import annotations

from typing import Any

SOURCE_REFERENCE: dict[str, Any] = {
    "name": "Project G Funding & Positioning Reference by Milo1",
    "window": "2021-01-08 to 2026-09-30",
    "weekly_observations": 299,
    "cell_counts": [0, 4, 92, 70, 18, 14, 64, 37],
    "note": "Non-overlapping weekly forward 7d/14d return statistics; deterministic reference table only.",
}

# Empirical 299 non-overlapping weekly observations (2021-01-08 -> 2026-09-30), forward 7d / 14d returns.
PROJECT_G_MATRIX: list[dict[str, Any]] = [
    {
        "id": "above_200d_crowded_shorts",
        "regime": "above_200d",
        "regime_label": "Above 200D",
        "state": "crowded_shorts",
        "state_label": "Crowded shorts",
        "funding_sign": "negative",
        "oi_sign": "rising",
        "n": 0,
        "mean_7d_pct": None,
        "median_7d_pct": None,
        "hit_rate_pct": None,
        "mean_14d_pct": None,
        "reading": "never occurred in 299 weeks",
    },
    {
        "id": "above_200d_positions_leaving",
        "regime": "above_200d",
        "regime_label": "Above 200D",
        "state": "positions_leaving",
        "state_label": "Positions leaving",
        "funding_sign": "negative",
        "oi_sign": "falling",
        "n": 4,
        "mean_7d_pct": 4.23,
        "median_7d_pct": 0.08,
        "hit_rate_pct": 50,
        "mean_14d_pct": 7.34,
        "reading": "colour only",
    },
    {
        "id": "above_200d_crowded_longs",
        "regime": "above_200d",
        "regime_label": "Above 200D",
        "state": "crowded_longs",
        "state_label": "Crowded longs",
        "funding_sign": "positive",
        "oi_sign": "rising",
        "n": 92,
        "mean_7d_pct": 0.50,
        "median_7d_pct": -0.32,
        "hit_rate_pct": 49,
        "mean_14d_pct": 1.64,
        "reading": "no edge",
    },
    {
        "id": "above_200d_quiet_deleveraging",
        "regime": "above_200d",
        "regime_label": "Above 200D",
        "state": "quiet_deleveraging",
        "state_label": "Quiet deleveraging",
        "funding_sign": "positive",
        "oi_sign": "falling",
        "n": 70,
        "mean_7d_pct": 0.71,
        "median_7d_pct": 0.61,
        "hit_rate_pct": 51,
        "mean_14d_pct": 0.73,
        "reading": "no edge",
    },
    {
        "id": "below_200d_crowded_shorts",
        "regime": "below_200d",
        "regime_label": "Below 200D",
        "state": "crowded_shorts",
        "state_label": "Crowded shorts",
        "funding_sign": "negative",
        "oi_sign": "rising",
        "n": 18,
        "mean_7d_pct": 3.05,
        "median_7d_pct": 3.55,
        "hit_rate_pct": 72,
        "mean_14d_pct": 3.03,
        "reading": "directional colour only",
    },
    {
        "id": "below_200d_positions_leaving",
        "regime": "below_200d",
        "regime_label": "Below 200D",
        "state": "positions_leaving",
        "state_label": "Positions leaving",
        "funding_sign": "negative",
        "oi_sign": "falling",
        "n": 14,
        "mean_7d_pct": 1.10,
        "median_7d_pct": -0.06,
        "hit_rate_pct": 50,
        "mean_14d_pct": 2.21,
        "reading": "colour only",
    },
    {
        "id": "below_200d_crowded_longs",
        "regime": "below_200d",
        "regime_label": "Below 200D",
        "state": "crowded_longs",
        "state_label": "Crowded longs",
        "funding_sign": "positive",
        "oi_sign": "rising",
        "n": 64,
        "mean_7d_pct": 0.07,
        "median_7d_pct": 0.08,
        "hit_rate_pct": 52,
        "mean_14d_pct": 1.00,
        "reading": "no edge",
    },
    {
        "id": "below_200d_quiet_deleveraging",
        "regime": "below_200d",
        "regime_label": "Below 200D",
        "state": "quiet_deleveraging",
        "state_label": "Quiet deleveraging",
        "funding_sign": "positive",
        "oi_sign": "falling",
        "n": 37,
        "mean_7d_pct": -0.62,
        "median_7d_pct": -0.02,
        "hit_rate_pct": 49,
        "mean_14d_pct": -1.02,
        "reading": "no edge",
    },
]

# Study 1 — Daily funding (%/day) across 2,587 days (2019-09 -> 2026-10). Spearman IC = -0.047.
DAILY_FUNDING_BANDS: list[dict[str, Any]] = [
    {"band": "< -0.01%", "min": None, "max": -0.01, "n": 146, "mean_7d_pct": 4.68, "median_7d_pct": 2.95, "hit_rate_pct": 66.4},
    {"band": "-0.01% .. 0%", "min": -0.01, "max": 0.0, "n": 178, "mean_7d_pct": 1.19, "median_7d_pct": 0.49, "hit_rate_pct": 54.4},
    {"band": "0 .. +0.01%", "min": 0.0, "max": 0.01, "n": 386, "mean_7d_pct": 0.99, "median_7d_pct": 0.71, "hit_rate_pct": 55.1},
    {"band": "+0.01% .. +0.03%", "min": 0.01, "max": 0.03, "n": 829, "mean_7d_pct": 0.15, "median_7d_pct": -0.03, "hit_rate_pct": 49.5},
    {"band": "> +0.03%", "min": 0.03, "max": None, "n": 1041, "mean_7d_pct": 0.93, "median_7d_pct": 0.43, "hit_rate_pct": 52.0},
]


def _match_funding_band(daily_pct: float) -> dict[str, Any]:
    if daily_pct < -0.01:
        return dict(DAILY_FUNDING_BANDS[0])
    if daily_pct <= 0.0:
        return dict(DAILY_FUNDING_BANDS[1])
    if daily_pct <= 0.01:
        return dict(DAILY_FUNDING_BANDS[2])
    if daily_pct <= 0.03:
        return dict(DAILY_FUNDING_BANDS[3])
    return dict(DAILY_FUNDING_BANDS[4])


def _resolve_200d_regime(market: dict[str, Any], cortex_rhyme: dict[str, Any] | None) -> tuple[str | None, float | None]:
    if isinstance(cortex_rhyme, dict):
        reg = ((cortex_rhyme.get("current_state") or {}).get("regime_context") or {})
        tr = str(reg.get("trend_regime") or "")
        sma200 = reg.get("sma_200d")
        if tr == "ABOVE_200D_SMA":
            return "above_200d", float(sma200) if isinstance(sma200, (int, float)) else None
        if tr == "BELOW_200D_SMA":
            return "below_200d", float(sma200) if isinstance(sma200, (int, float)) else None

    d1 = (market.get("klines") or {}).get("1d") or []
    price = (market.get("ticker") or {}).get("price")
    if len(d1) >= 200 and isinstance(price, (int, float)):
        closes = [float(b["close"]) for b in d1[-200:] if isinstance(b.get("close"), (int, float))]
        if len(closes) == 200:
            sma200 = sum(closes) / 200.0
            return ("above_200d" if float(price) >= sma200 else "below_200d"), round(sma200, 1)
    if isinstance(d1, list) and d1 and isinstance(price, (int, float)):
        # Fewer than 200 bars fallback only if cortex_rhyme missing: return unknown cleanly
        return None, None
    return None, None


def compute_positioning_matrix_g(
    market: dict[str, Any],
    cortex_rhyme: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate Project G 8-cell (200D Regime x Funding x OI) context flag without issuing trades."""
    drv = market.get("derivatives") or {}
    funding_8h = drv.get("current_rate_pct")

    oi_delta: float | None = None
    oi_window: str | None = None
    if isinstance(drv.get("btc_oi_change_pct_3d"), (int, float)):
        oi_delta = float(drv["btc_oi_change_pct_3d"])
        oi_window = "3d"
    elif isinstance(drv.get("btc_oi_change_pct_24h"), (int, float)):
        oi_delta = float(drv["btc_oi_change_pct_24h"])
        oi_window = "24h"
    elif isinstance(cortex_rhyme, dict):
        raw_oi = ((cortex_rhyme.get("current_state") or {}).get("raw_metrics") or {}).get("oi_delta_24h_pct")
        if isinstance(raw_oi, (int, float)):
            oi_delta = float(raw_oi)
            oi_window = "24h"

    regime_key, sma_200d = _resolve_200d_regime(market, cortex_rhyme)

    if not isinstance(funding_8h, (int, float)) or oi_delta is None or regime_key is None:
        return {
            "status": "unavailable",
            "reason": "Missing funding_8h, OI delta, or 200D SMA regime",
            "guardrail": "Context only — no cell authorizes a trade or position size.",
            "matrix_rows": PROJECT_G_MATRIX,
        }

    f8 = float(funding_8h)
    f_daily = round(f8 * 3.0, 5)
    f_ann = round(f_daily * 365.0, 2)

    if f8 < 0.0 and oi_delta > 0.0:
        state_key = "crowded_shorts"
    elif f8 < 0.0:
        state_key = "positions_leaving"
    elif oi_delta > 0.0:
        state_key = "crowded_longs"
    else:
        state_key = "quiet_deleveraging"

    active_cell = next(
        (c for c in PROJECT_G_MATRIX if c["regime"] == regime_key and c["state"] == state_key),
        PROJECT_G_MATRIX[0],
    )
    band = _match_funding_band(f_daily)
    extreme_tail = bool(f_daily < -0.01 and oi_delta > 0.0)

    n_str = f"n={active_cell['n']}"
    hit_str = f", {active_cell['hit_rate_pct']}% hit" if active_cell["hit_rate_pct"] is not None else ""
    summary_line = (
        f"{active_cell['regime_label']} · {active_cell['state_label']} -> "
        f"{active_cell['reading'].upper()} ({n_str}{hit_str})"
    )

    return {
        "status": "LIVE",
        "regime_200d": regime_key,
        "sma_200d": sma_200d,
        "funding_8h_pct": round(f8, 5),
        "funding_daily_pct": f_daily,
        "funding_annualized_pct": f_ann,
        "oi_delta_pct": round(oi_delta, 2),
        "oi_window": oi_window,
        "leverage_state": state_key,
        "leverage_state_label": active_cell["state_label"],
        "extreme_short_tail_active": extreme_tail,
        "daily_funding_band": band,
        "active_cell": active_cell,
        "summary_line": summary_line,
        "guardrail": "Context only — no cell authorizes a trade or position size.",
        "matrix_rows": PROJECT_G_MATRIX,
    }
