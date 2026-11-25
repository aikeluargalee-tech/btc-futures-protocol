"""Closed-candle Multi-Timeframe S/R Bands & Liquidation Magnet Overlap Engine."""
from __future__ import annotations

import datetime as dt
from typing import Any


CORE_TF_SPECS = [
    ("1W", "1w", "Macro Structural Map", 2, 104),
    ("1D", "1d", "Swing Permission Wall/Floor", 2, 180),
    ("4H", "4h", "Core Swing Structure", 2, 180),
    ("1H", "1h", "Execution Shelf", 2, 168),
]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _calc_atr14(bars: list[dict[str, Any]]) -> float | None:
    if len(bars) < 2:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        cur = bars[i]
        prev_close = float(bars[i - 1]["close"])
        hi = float(cur["high"])
        lo = float(cur["low"])
        trs.append(max(hi - lo, abs(hi - prev_close), abs(lo - prev_close)))
    if not trs:
        return None
    window = trs[-14:]
    return sum(window) / len(window)


def _aggregate_weekly_from_daily(d1_bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate closed ISO weeks from daily bars as fallback if 1W feed is unavailable."""
    if not d1_bars:
        return []
    buckets: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for b in d1_bars:
        ts_sec = int(b["ts"]) / 1000.0
        d = dt.datetime.fromtimestamp(ts_sec, tz=dt.timezone.utc).date()
        iso = d.isocalendar()
        key = (iso.year, iso.week)
        buckets.setdefault(key, []).append(b)
    ordered_keys = sorted(buckets.keys())
    if ordered_keys and len(buckets[ordered_keys[-1]]) < 7:
        # Exclude partial current week so only closed weeks enter S/R math
        ordered_keys = ordered_keys[:-1]
    out: list[dict[str, Any]] = []
    for k in ordered_keys:
        grp = buckets[k]
        out.append({
            "ts": int(grp[0]["ts"]),
            "open": float(grp[0]["open"]),
            "high": max(float(x["high"]) for x in grp),
            "low": min(float(x["low"]) for x in grp),
            "close": float(grp[-1]["close"]),
            "volume": sum(float(x.get("volume") or 0.0) for x in grp),
        })
    return out


def _aggregate_bars(bars: list[dict[str, Any]], factor: int) -> list[dict[str, Any]]:
    """Group consecutive closed bars in chunks of `factor` aligned from the oldest multiple."""
    if factor <= 1 or len(bars) < factor:
        return list(bars)
    usable = len(bars) - (len(bars) % factor)
    trimmed = bars[-usable:] if usable > 0 else []
    out: list[dict[str, Any]] = []
    for i in range(0, len(trimmed), factor):
        grp = trimmed[i : i + factor]
        out.append({
            "ts": int(grp[0]["ts"]),
            "open": float(grp[0]["open"]),
            "high": max(float(x["high"]) for x in grp),
            "low": min(float(x["low"]) for x in grp),
            "close": float(grp[-1]["close"]),
            "volume": sum(float(x.get("volume") or 0.0) for x in grp),
        })
    return out


def compute_tf_sr_bands(
    bars: list[dict[str, Any]],
    ref_price: float,
    tf_label: str,
    role: str = "",
    pivot_span: int = 2,
    max_per_side: int = 3,
    lookback: int = 180,
) -> dict[str, Any]:
    """Compute clustered swing high/low ATR-padded S/R zones for a single closed-candle timeframe."""
    if not bars or ref_price <= 0:
        return {
            "tf": tf_label,
            "label": tf_label,
            "role": role,
            "bars": len(bars or []),
            "atr14_usd": None,
            "atr14_pct": None,
            "resistance": [],
            "support": [],
        }

    window = bars[-lookback:] if len(bars) > lookback else bars
    atr14 = _calc_atr14(window) or (ref_price * 0.015)
    atr14_pct = (atr14 / ref_price) * 100.0 if ref_price > 0 else None
    pad = _clamp(0.18 * atr14, ref_price * 0.0012, ref_price * 0.0085)
    cluster_tol = _clamp(0.55 * atr14, ref_price * 0.005, ref_price * 0.018)

    highs: list[tuple[float, int, str]] = []  # (price, ts, kind)
    lows: list[tuple[float, int, str]] = []
    n = len(window)
    for i in range(pivot_span, n - pivot_span):
        cur_hi = float(window[i]["high"])
        cur_lo = float(window[i]["low"])
        if all(cur_hi >= float(window[j]["high"]) for j in range(i - pivot_span, i + pivot_span + 1)):
            highs.append((cur_hi, int(window[i]["ts"]), "H"))
        if all(cur_lo <= float(window[j]["low"]) for j in range(i - pivot_span, i + pivot_span + 1)):
            lows.append((cur_lo, int(window[i]["ts"]), "L"))

    # Include last closed bar high/low as immediate context touch
    last_bar = window[-1]
    highs.append((float(last_bar["high"]), int(last_bar["ts"]), "H"))
    lows.append((float(last_bar["low"]), int(last_bar["ts"]), "L"))
    all_pivots = highs + lows

    def _cluster_side(points: list[tuple[float, int, str]], side: str) -> list[dict[str, Any]]:
        if not points:
            return []
        ordered = sorted(points, key=lambda x: x[0])
        clusters: list[list[tuple[float, int, str]]] = [[ordered[0]]]
        for pt in ordered[1:]:
            anchor = clusters[-1][0][0]
            if abs(pt[0] - anchor) <= cluster_tol:
                clusters[-1].append(pt)
            else:
                clusters.append([pt])

        zones: list[dict[str, Any]] = []
        for grp in clusters:
            lo_raw = min(p[0] for p in grp)
            hi_raw = max(p[0] for p in grp)
            mid = sum(p[0] for p in grp) / len(grp)
            half_span = min(max((hi_raw - lo_raw) * 0.5 + pad * 0.5, pad * 0.65), ref_price * 0.011)
            low_b = round(mid - half_span, 1)
            high_b = round(mid + half_span, 1)
            mid_r = round(mid, 1)
            last_ts = max(p[1] for p in grp)
            touches = len(grp)
            kinds = {p[2] for p in grp}
            flip_role = "S/R FLIP" if len(kinds) == 2 else ("HIGH" if "H" in kinds else "LOW")
            in_zone = low_b <= ref_price <= high_b

            # Partition strictly by position relative to ref_price (captures polarity flips automatically)
            if side == "resistance" and mid_r < ref_price:
                continue
            if side == "support" and mid_r >= ref_price:
                continue

            dist_pct = round(((mid_r - ref_price) / ref_price) * 100.0, 2)
            zones.append({
                "tf": tf_label,
                "side": side,
                "low": low_b,
                "mid": mid_r,
                "high": high_b,
                "touches": touches,
                "last_ts": last_ts,
                "distance_pct": dist_pct,
                "in_zone": in_zone,
                "pivot_kind": flip_role,
                "strength": "STRONG" if touches >= 3 else ("TESTED" if touches == 2 else "SINGLE"),
            })

        if side == "resistance":
            zones.sort(key=lambda z: z["mid"])
        else:
            zones.sort(key=lambda z: z["mid"], reverse=True)
        return zones[:max_per_side]

    return {
        "tf": tf_label,
        "label": tf_label,
        "role": role,
        "bars": len(window),
        "atr14_usd": round(atr14, 1),
        "atr14_pct": round(atr14_pct, 2) if atr14_pct is not None else None,
        "resistance": _cluster_side(all_pivots, "resistance"),
        "support": _cluster_side(all_pivots, "support"),
    }


def compute_confluence_zones(
    core_timeframes: dict[str, dict[str, Any]],
    ref_price: float,
) -> dict[str, list[dict[str, Any]]]:
    """Group nearby S/R zones across the 4 core timeframes (1W, 1D, 4H, 1H) where >= 2 TFs align."""
    if ref_price <= 0:
        return {"resistance": [], "support": []}

    tol = ref_price * 0.0085
    tf_weight = {"1W": 4, "1D": 3, "4H": 2, "1H": 1}
    out: dict[str, list[dict[str, Any]]] = {"resistance": [], "support": []}

    for side in ("resistance", "support"):
        flat: list[dict[str, Any]] = []
        for tf_key in ("1W", "1D", "4H", "1H"):
            tf_data = core_timeframes.get(tf_key) or {}
            for z in tf_data.get(side) or []:
                flat.append(z)
        if not flat:
            continue
        flat.sort(key=lambda z: z["mid"])
        groups: list[list[dict[str, Any]]] = [[flat[0]]]
        for z in flat[1:]:
            anchor = sum(x["mid"] for x in groups[-1]) / len(groups[-1])
            if abs(z["mid"] - anchor) <= tol:
                groups[-1].append(z)
            else:
                groups.append([z])

        confs: list[dict[str, Any]] = []
        for grp in groups:
            tfs = sorted({x["tf"] for x in grp}, key=lambda k: tf_weight.get(k, 0), reverse=True)
            if len(tfs) < 2:
                continue
            mid = round(sum(x["mid"] for x in grp) / len(grp), 1)
            raw_low = min(x["low"] for x in grp)
            raw_high = max(x["high"] for x in grp)
            half_w = min(max((raw_high - raw_low) * 0.5, ref_price * 0.0035), ref_price * 0.011)
            low = round(mid - half_w, 1)
            high = round(mid + half_w, 1)
            dist_pct = round(((mid - ref_price) / ref_price) * 100.0, 2)
            confs.append({
                "side": side,
                "low": low,
                "mid": mid,
                "high": high,
                "distance_pct": dist_pct,
                "timeframes": tfs,
                "tf_count": len(tfs),
                "total_touches": sum(int(x.get("touches") or 1) for x in grp),
                "label": " + ".join(tfs) + (" Floor" if side == "support" else " Ceiling"),
            })
        confs.sort(key=lambda c: abs(c["distance_pct"]))
        out[side] = confs[:4]

    return out


def compute_magnet_overlaps(
    core_timeframes: dict[str, dict[str, Any]],
    cmc_liq: dict[str, Any] | None,
    spot_magnet: dict[str, Any] | None,
    ref_price: float,
) -> list[dict[str, Any]]:
    """Detect when major liquidation clusters sit just behind 1H/4H S/R shelves (Trap #05 / Trap #03)."""
    if ref_price <= 0:
        return []

    lower_clusters: list[dict[str, Any]] = []
    upper_clusters: list[dict[str, Any]] = []

    if isinstance(cmc_liq, dict):
        for cl in cmc_liq.get("tactical_long_clusters_within_8pct") or []:
            px = cl.get("price")
            sz = cl.get("usd_m")
            if isinstance(px, (int, float)) and isinstance(sz, (int, float)) and sz >= 15.0:
                lower_clusters.append({"source": "CMC Exact Hyperliquid", "price": float(px), "usd_m": float(sz), "label": f"CMC Long Pool ({cl.get('leverage', '?')}x)"})
        for cl in cmc_liq.get("tactical_short_clusters_within_8pct") or []:
            px = cl.get("price")
            sz = cl.get("usd_m")
            if isinstance(px, (int, float)) and isinstance(sz, (int, float)) and sz >= 15.0:
                upper_clusters.append({"source": "CMC Exact Hyperliquid", "price": float(px), "usd_m": float(sz), "label": f"CMC Short Pool ({cl.get('leverage', '?')}x)"})

    ladder = ((spot_magnet or {}).get("magnets") or {}).get("liquidation_ladder") or []
    for row in ladder:
        px = row.get("price")
        sz = row.get("estimated_vol_m")
        if not (isinstance(px, (int, float)) and isinstance(sz, (int, float)) and sz >= 15.0):
            continue
        if row.get("side") == "lower":
            lower_clusters.append({"source": "F3 Modeled Ladder", "price": float(px), "usd_m": float(sz), "label": f"Modeled {row.get('tier', 'Lower Pool')}"})
        elif row.get("side") == "upper":
            upper_clusters.append({"source": "F3 Modeled Ladder", "price": float(px), "usd_m": float(sz), "label": f"Modeled {row.get('tier', 'Upper Pool')}"})

    overlaps: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float]] = set()

    for tf_key in ("1H", "4H"):
        tf_data = core_timeframes.get(tf_key) or {}
        for sup in tf_data.get("support") or []:
            sup_mid = float(sup["mid"])
            for cl in lower_clusters:
                if sup_mid <= 0:
                    continue
                gap_pct = ((sup_mid - cl["price"]) / sup_mid) * 100.0
                if -0.25 <= gap_pct <= 3.5:
                    key = ("LOWER", tf_key, round(cl["price"], 0))
                    if key in seen:
                        continue
                    seen.add(key)
                    gap_desc = f"{gap_pct:.2f}% below" if gap_pct >= 0 else f"inside ({abs(gap_pct):.2f}%)"
                    overlaps.append({
                        "side": "LOWER_BELOW_SUPPORT",
                        "trap_ref": "trap_05",
                        "support_tf": tf_key,
                        "support_mid": sup_mid,
                        "cluster_source": cl["source"],
                        "cluster_label": cl["label"],
                        "cluster_price": round(cl["price"], 1),
                        "cluster_usd_m": round(cl["usd_m"], 1),
                        "gap_below_support_pct": round(gap_pct, 2),
                        "message": (
                            f"{tf_key} Support (${sup_mid:,.0f}) sits just above {cl['label']} "
                            f"(${cl['price']:,.0f}, ${cl['usd_m']:.1f}M, {gap_desc} — Trap #05 magnet risk)."
                        ),
                    })

        for res in tf_data.get("resistance") or []:
            res_mid = float(res["mid"])
            for cl in upper_clusters:
                if res_mid <= 0:
                    continue
                gap_pct = ((cl["price"] - res_mid) / res_mid) * 100.0
                if -0.25 <= gap_pct <= 3.5:
                    key = ("UPPER", tf_key, round(cl["price"], 0))
                    if key in seen:
                        continue
                    seen.add(key)
                    overlaps.append({
                        "side": "UPPER_ABOVE_RESISTANCE",
                        "trap_ref": "trap_03",
                        "support_tf": tf_key,
                        "support_mid": res_mid,
                        "cluster_source": cl["source"],
                        "cluster_label": cl["label"],
                        "cluster_price": round(cl["price"], 1),
                        "cluster_usd_m": round(cl["usd_m"], 1),
                        "gap_below_support_pct": round(gap_pct, 2),
                        "message": (
                            f"{cl['label']} (${cl['price']:,.0f}, ${cl['usd_m']:.1f}M) sits "
                            f"{max(0.0, gap_pct):.2f}% above {tf_key} Resistance (${res_mid:,.0f}) — false breakout wick risk."
                        ),
                    })

    overlaps.sort(key=lambda o: (0 if o["side"] == "LOWER_BELOW_SUPPORT" else 1, -o["cluster_usd_m"]))
    return overlaps[:8]


def compute_sr_bands(
    market: dict[str, Any],
    spot_magnet: dict[str, Any] | None = None,
    now_utc: dt.datetime | None = None,
) -> dict[str, Any]:
    """Build multi-timeframe S/R bands (1W/1D/4H/1H + intraday fallback) and magnet overlap alerts."""
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    klines = market.get("klines") or {}
    ticker = market.get("ticker") or {}
    h1_bars = klines.get("1h") or []
    d1_bars = klines.get("1d") or []
    h4_bars = klines.get("4h") or []
    m15_bars = klines.get("15m") or []
    w1_bars = klines.get("1w") or []
    if len(w1_bars) < 10 and len(d1_bars) >= 14:
        w1_bars = _aggregate_weekly_from_daily(d1_bars)

    ref_price = ticker.get("price")
    if not isinstance(ref_price, (int, float)) or ref_price <= 0:
        for fallback_bars in (h1_bars, h4_bars, d1_bars, w1_bars):
            if fallback_bars:
                ref_price = float(fallback_bars[-1]["close"])
                break
    ref_price = float(ref_price or 0.0)

    bars_by_key = {
        "1w": w1_bars,
        "1d": d1_bars,
        "4h": h4_bars,
        "1h": h1_bars,
    }
    core_timeframes: dict[str, dict[str, Any]] = {}
    for tf_label, k_key, role, span, lookback in CORE_TF_SPECS:
        core_timeframes[tf_label] = compute_tf_sr_bands(
            bars_by_key.get(k_key) or [],
            ref_price=ref_price,
            tf_label=tf_label,
            role=role,
            pivot_span=span,
            max_per_side=3,
            lookback=lookback,
        )

    intraday_snapshot = {
        "12H": compute_tf_sr_bands(
            _aggregate_bars(h4_bars, 3),
            ref_price=ref_price,
            tf_label="12H",
            role="Session Half-Day Bridge (Hourly Snapshot)",
            pivot_span=2,
            max_per_side=3,
            lookback=60,
        ),
        "30m": compute_tf_sr_bands(
            _aggregate_bars(m15_bars, 2),
            ref_price=ref_price,
            tf_label="30m",
            role="Intraday Scalp Noise (Hourly Snapshot)",
            pivot_span=2,
            max_per_side=3,
            lookback=60,
        ),
        "15m": compute_tf_sr_bands(
            m15_bars,
            ref_price=ref_price,
            tf_label="15m",
            role="Micro Execution Noise (Hourly Snapshot)",
            pivot_span=2,
            max_per_side=3,
            lookback=96,
        ),
    }

    confluence_zones = compute_confluence_zones(core_timeframes, ref_price)
    cmc_liq = (market.get("derivatives") or {}).get("cmc_liquidations")
    magnet_overlaps = compute_magnet_overlaps(core_timeframes, cmc_liq, spot_magnet, ref_price)

    all_sup = [z for tf in core_timeframes.values() for z in tf.get("support") or []]
    all_res = [z for tf in core_timeframes.values() for z in tf.get("resistance") or []]
    nearest_sup = max(all_sup, key=lambda z: z["mid"]) if all_sup else None
    nearest_res = min(all_res, key=lambda z: z["mid"]) if all_res else None
    conf_count = len(confluence_zones["support"]) + len(confluence_zones["resistance"])

    sup_str = f"Floor ${nearest_sup['mid']:,.0f} ({nearest_sup['distance_pct']:+.2f}%)" if nearest_sup else "Floor —"
    res_str = f"Ceiling ${nearest_res['mid']:,.0f} ({nearest_res['distance_pct']:+.2f}%)" if nearest_res else "Ceiling —"
    status = "LIVE" if ref_price > 0 and (all_sup or all_res) else "DEGRADED"

    return {
        "status": status,
        "updated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ref_price": round(ref_price, 1) if ref_price > 0 else None,
        "core_order": ["1W", "1D", "4H", "1H"],
        "timeframes": core_timeframes,
        "intraday_snapshot": intraday_snapshot,
        "confluence_zones": confluence_zones,
        "magnet_overlaps": magnet_overlaps,
        "summary_line": f"{conf_count} Confluence Zone(s) · {sup_str} · {res_str}",
        "guardrail": "Closed-candle structural zones & liquidation context only — never issues an automatic entry or leverage instruction.",
    }
