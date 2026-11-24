"""Self-contained S2 CORTEX-RHYME v1.2.0 (MOD 63) Engine for btc-futures-protocol.

Reads static 2-year SQLite archive (`data/cortex_rhyme_base.db`) + append-only hourly
text delta (`data/rhyme_delta.jsonl`), incrementally syncs new closed 1H OKX bars,
and evaluates Dual-Lens Regularized Mahalanobis state-space analogues (5D & 3D 2Y)
with causal 168h normalization, 24h de-clustering, 72h forward embargo, and
causal 200D SMA trend-regime conditioning. Zero external dependencies.
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BASE_DB_PATH = ROOT / "data" / "cortex_rhyme_base.db"
DELTA_JSONL_PATH = ROOT / "data" / "rhyme_delta.jsonl"

OKX_BASE = "https://www.okx.com"
HEADERS = {
    "User-Agent": "CORTEX-RHYME-OpenTelemetry/1.2",
    "Accept": "application/json",
}

FEATURES_5D = [
    "funding_rate",
    "basis_bps",
    "oi_delta_24h",
    "gk_vol_24h",
    "taker_buy_ratio",
]
PRIOR_SCALES_5D = [1.15, 1.0, 1.15, 1.0, 1.10]

FEATURES_3D = [
    "funding_rate",
    "basis_bps",
    "gk_vol_24h",
]
PRIOR_SCALES_3D = [1.20, 1.05, 1.10]

SMA_200D_HOURS = 4800


def _floor_hour_ms(ts_ms: int) -> int:
    return (ts_ms // 3_600_000) * 3_600_000


def _okx_get(path: str, params: dict[str, Any] | None = None, retries: int = 3) -> dict[str, Any]:
    url = f"{OKX_BASE}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url = f"{url}?{urllib.parse.urlencode(clean)}"
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                if payload.get("code") == "0":
                    return payload
                raise RuntimeError(f"OKX API error {payload.get('code')}: {payload.get('msg')}")
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, TimeoutError) as exc:
            if attempt == retries - 1:
                raise exc
            time.sleep(1.0 * (2**attempt))
    return {"data": []}


def _fetch_paginated_candles(endpoint: str, inst_id: str, target_bars: int) -> dict[int, list[float]]:
    records: dict[int, list[float]] = {}
    after_cursor: str | None = None
    while len(records) < target_bars:
        res = _okx_get(endpoint, {"instId": inst_id, "bar": "1H", "limit": "100", "after": after_cursor})
        rows = res.get("data", [])
        if not rows:
            break
        for r in rows:
            ts = _floor_hour_ms(int(r[0]))
            vals = [float(r[1]), float(r[2]), float(r[3]), float(r[4])]
            if len(r) > 6:
                vals.append(float(r[6]))
            records[ts] = vals
        oldest_ts = str(int(rows[-1][0]))
        if after_cursor == oldest_ts:
            break
        after_cursor = oldest_ts
        time.sleep(0.15)
    return records


def _fetch_funding_history(inst_id: str = "BTC-USDT-SWAP", pages: int = 2) -> dict[int, float]:
    out: dict[int, float] = {}
    after_cursor: str | None = None
    for _ in range(pages):
        res = _okx_get("/api/v5/public/funding-rate-history", {"instId": inst_id, "limit": "100", "after": after_cursor})
        rows = res.get("data", [])
        if not rows:
            break
        for r in rows:
            ts = _floor_hour_ms(int(r["fundingTime"]))
            out[ts] = float(r["realizedRate"] or r["fundingRate"])
        after_cursor = rows[-1]["fundingTime"]
        time.sleep(0.15)
    return out


def _fetch_oi_history(target_bars: int) -> dict[int, float]:
    oi_map: dict[int, float] = {}
    end_cursor: str | None = None
    while len(oi_map) < target_bars:
        res = _okx_get("/api/v5/rubik/stat/contracts/open-interest-history", {"instId": "BTC-USDT-SWAP", "period": "1H", "end": end_cursor})
        rows = res.get("data", [])
        if not rows:
            break
        for r in rows:
            oi_map[_floor_hour_ms(int(r[0]))] = float(r[3])
        oldest_ts = str(int(rows[-1][0]))
        if end_cursor == oldest_ts:
            break
        end_cursor = oldest_ts
        time.sleep(0.15)
    return oi_map


def _fetch_taker_history(target_bars: int) -> dict[int, float]:
    taker_map: dict[int, float] = {}
    end_cursor: str | None = None
    while len(taker_map) < target_bars:
        res = _okx_get("/api/v5/rubik/stat/taker-volume", {"ccy": "BTC", "instType": "CONTRACTS", "period": "1H", "end": end_cursor})
        rows = res.get("data", [])
        if not rows:
            break
        for r in rows:
            sell_v = float(r[1])
            buy_v = float(r[2])
            tot = buy_v + sell_v
            taker_map[_floor_hour_ms(int(r[0]))] = (buy_v / tot) if tot > 0 else 0.5
        oldest_ts = str(int(rows[-1][0]))
        if end_cursor == oldest_ts:
            break
        end_cursor = oldest_ts
        time.sleep(0.15)
    return taker_map


def _fetch_live_l2(inst_id: str = "BTC-USDT-SWAP", depth: int = 20) -> float | None:
    try:
        res = _okx_get("/api/v5/market/books", {"instId": inst_id, "sz": str(depth)})
        book = (res.get("data") or [{}])[0]
        bid_n = sum(float(p) * float(sz) for p, sz, *_ in (book.get("bids") or []))
        ask_n = sum(float(p) * float(sz) for p, sz, *_ in (book.get("asks") or []))
        tot = bid_n + ask_n
        return round((bid_n - ask_n) / tot, 4) if tot > 0 else 0.0
    except Exception:
        return None


def compute_garman_klass_24h(ohlc_window: list[dict[str, Any]]) -> float:
    if len(ohlc_window) < 2:
        return 0.0
    sum_gk = 0.0
    c1 = 0.5
    c2 = 2.0 * math.log(2.0) - 1.0
    for row in ohlc_window:
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
            continue
        sum_gk += c1 * (math.log(h / l) ** 2) - c2 * (math.log(c / o) ** 2)
    return math.sqrt(max(sum_gk / len(ohlc_window), 0.0) * 8760.0)


def _load_base_and_delta() -> tuple[dict[int, dict[str, Any]], int, int]:
    """Load baseline SQLite rows overlaid with append-only JSONL delta."""
    by_ts: dict[int, dict[str, Any]] = {}
    base_max_ts = 0
    if BASE_DB_PATH.exists():
        conn = sqlite3.connect(str(BASE_DB_PATH))
        conn.row_factory = sqlite3.Row
        for r in conn.execute(
            """
            SELECT ts_ms, iso_utc, open, high, low, close, volume_ccy,
                   mark_close, index_close, basis_bps, funding_rate,
                   oi_usd, oi_delta_24h, taker_buy_ratio, gk_vol_24h, live_l2_imbalance
            FROM hourly_state ORDER BY ts_ms ASC
            """
        ):
            d = dict(r)
            ts = int(d["ts_ms"])
            by_ts[ts] = d
            if ts > base_max_ts:
                base_max_ts = ts
        conn.close()

    if DELTA_JSONL_PATH.exists():
        for line in DELTA_JSONL_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                ts = int(d["ts_ms"])
                by_ts[ts] = d
            except Exception:
                continue

    max_ts = max(by_ts.keys()) if by_ts else 0
    return by_ts, base_max_ts, max_ts


def _save_delta(by_ts: dict[int, dict[str, Any]], base_max_ts: int) -> None:
    DELTA_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    delta_rows = [by_ts[ts] for ts in sorted(by_ts.keys()) if ts > base_max_ts]
    with open(DELTA_JSONL_PATH, "w", encoding="utf-8") as f:
        for row in delta_rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")


def sync_and_load_rows() -> tuple[list[dict[str, Any]], str]:
    """Incrementally sync new closed 1H OKX bars into delta JSONL and return aligned chronological rows."""
    by_ts, base_max_ts, max_ts = _load_base_and_delta()
    if not by_ts:
        return [], "unavailable"

    sync_status = "live"
    now_hour_ms = _floor_hour_ms(int(time.time() * 1000))
    hours_behind = max(0, int((now_hour_ms - max_ts) // 3_600_000))
    gap_bars = max(24, min(400, hours_behind + 12))

    # Only fetch from OKX if we are missing the latest closed hour (or need initial catch-up)
    if hours_behind >= 2 or not DELTA_JSONL_PATH.exists():
        try:
            swap = _fetch_paginated_candles("/api/v5/market/history-candles", "BTC-USDT-SWAP", gap_bars)
            mark = _fetch_paginated_candles("/api/v5/market/history-mark-price-candles", "BTC-USDT-SWAP", gap_bars)
            idx_c = _fetch_paginated_candles("/api/v5/market/history-index-candles", "BTC-USDT", gap_bars)
            funding = _fetch_funding_history("BTC-USDT-SWAP", pages=2 if gap_bars <= 200 else 3)
            oi_map = _fetch_oi_history(gap_bars)
            taker_map = _fetch_taker_history(gap_bars)
            live_l2 = _fetch_live_l2("BTC-USDT-SWAP", depth=20)

            sorted_new_ts = sorted(ts for ts in swap.keys() if ts < now_hour_ms)
            sorted_fund_ts = sorted(funding.keys())
            last_fund = (
                float(by_ts[max_ts]["funding_rate"])
                if by_ts.get(max_ts) and by_ts[max_ts].get("funding_rate") is not None
                else (funding[sorted_fund_ts[0]] if sorted_fund_ts else 0.0)
            )
            # If fetched funding history extends before sorted_new_ts, seed with latest rate at/before start
            if sorted_fund_ts and sorted_new_ts:
                prior_f = [ft for ft in sorted_fund_ts if ft <= sorted_new_ts[0]]
                if prior_f:
                    last_fund = funding[prior_f[-1]]

            first_touched_ts: int | None = None
            for ts in sorted_new_ts:
                if ts in funding:
                    last_fund = funding[ts]
                o, h, l, c = swap[ts][:4]
                vol = swap[ts][4] if len(swap[ts]) > 4 else 0.0
                mc = mark[ts][3] if ts in mark else c
                ic = idx_c[ts][3] if ts in idx_c else c
                basis = round(((mc - ic) / ic) * 10_000.0, 3) if ic > 0 else 0.0
                existing = by_ts.get(ts) or {}
                oi_usd = oi_map.get(ts) if ts in oi_map else oi_map.get(ts - 3_600_000) or existing.get("oi_usd")
                tr = taker_map.get(ts) if ts in taker_map else taker_map.get(ts - 3_600_000) or existing.get("taker_buy_ratio")
                l2 = live_l2 if ts == sorted_new_ts[-1] else existing.get("live_l2_imbalance")
                row = {
                    "ts_ms": ts,
                    "iso_utc": datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume_ccy": vol,
                    "mark_close": mc,
                    "index_close": ic,
                    "basis_bps": basis,
                    "funding_rate": last_fund,
                    "oi_usd": oi_usd,
                    "oi_delta_24h": existing.get("oi_delta_24h"),
                    "taker_buy_ratio": round(float(tr), 6) if tr is not None else None,
                    "gk_vol_24h": existing.get("gk_vol_24h"),
                    "live_l2_imbalance": l2,
                }
                if ts > base_max_ts:
                    by_ts[ts] = row
                    if first_touched_ts is None:
                        first_touched_ts = ts

            all_ts = sorted(by_ts.keys())
            start_recalc = 0
            if first_touched_ts is not None:
                idx_pos = all_ts.index(first_touched_ts)
                start_recalc = max(0, idx_pos - 2)
            for idx in range(start_recalc, len(all_ts)):
                ts = all_ts[idx]
                if ts <= base_max_ts:
                    continue
                cur_row = by_ts[ts]
                win24 = [by_ts[all_ts[j]] for j in range(max(0, idx - 23), idx + 1)]
                cur_row["gk_vol_24h"] = round(compute_garman_klass_24h(win24), 5)
                oi_now = cur_row.get("oi_usd")
                oi_prev = by_ts[all_ts[idx - 24]].get("oi_usd") if idx >= 24 else None
                if oi_now is not None and oi_prev is not None and oi_prev > 0:
                    cur_row["oi_delta_24h"] = round((float(oi_now) - float(oi_prev)) / float(oi_prev) * 100.0, 4)

            _save_delta(by_ts, base_max_ts)
        except Exception:
            sync_status = "cached"

    aligned = [
        by_ts[ts]
        for ts in sorted(by_ts.keys())
        if by_ts[ts].get("funding_rate") is not None
        and by_ts[ts].get("basis_bps") is not None
        and by_ts[ts].get("oi_delta_24h") is not None
        and by_ts[ts].get("gk_vol_24h") is not None
        and by_ts[ts].get("taker_buy_ratio") is not None
    ]
    return aligned, sync_status


def _causal_z_scores(values: list[float], window: int = 168) -> list[float | None]:
    z_out: list[float | None] = []
    for i in range(len(values)):
        prior = values[max(0, i - window) : i]
        if len(prior) < 24:
            z_out.append(None)
            continue
        mu = statistics.fmean(prior)
        sigma = statistics.stdev(prior)
        raw_z = (values[i] - mu) / sigma if sigma > 1e-12 else 0.0
        z_out.append(max(-4.0, min(4.0, raw_z)))
    return z_out


def _compute_causal_sma_regimes(closes: list[float], window: int = SMA_200D_HOURS) -> list[tuple[float, str]]:
    n = len(closes)
    prefix = [0.0] * (n + 1)
    for i in range(n):
        prefix[i + 1] = prefix[i] + closes[i]
    out: list[tuple[float, str]] = []
    for i in range(n):
        start = max(0, i - window + 1)
        sma_val = (prefix[i + 1] - prefix[start]) / (i - start + 1)
        if i < window - 1:
            out.append((sma_val, "UNKNOWN"))
        else:
            out.append((sma_val, "ABOVE_200D_SMA" if closes[i] >= sma_val else "BELOW_200D_SMA"))
    return out


def _has_genuine_5d_telemetry(row: dict[str, Any]) -> bool:
    if row.get("oi_usd") is not None:
        return True
    if abs(float(row["oi_delta_24h"])) > 1e-9:
        return True
    if abs(float(row["taker_buy_ratio"]) - 0.5) > 1e-9:
        return True
    return False


def _invert_matrix_gauss_jordan(matrix: list[list[float]]) -> list[list[float]]:
    n = len(matrix)
    aug = [[float(matrix[r][c]) for c in range(n)] + [1.0 if r == c else 0.0 for c in range(n)] for r in range(n)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot_row][col]) < 1e-12:
            raise ValueError("Singular covariance matrix")
        aug[col], aug[pivot_row] = aug[pivot_row], aug[col]
        pv = aug[col][col]
        aug[col] = [val / pv for val in aug[col]]
        for r in range(n):
            if r != col:
                f = aug[r][col]
                if f != 0.0:
                    aug[r] = [aug[r][c] - f * aug[col][c] for c in range(2 * n)]
    return [row[n:] for row in aug]


def _precision_matrix(vectors: list[list[float]], dim_fallback: int, ridge: float = 0.05) -> dict[str, Any]:
    dim = len(vectors[0]) if vectors else dim_fallback
    n = len(vectors)
    if n < 30:
        return {"inv_cov": [[1.0 if r == c else 0.0 for c in range(dim)] for r in range(dim)], "funding_basis_corr": 0.0}
    means = [sum(v[d] for v in vectors) / n for d in range(dim)]
    cov = [[0.0] * dim for _ in range(dim)]
    for v in vectors:
        diffs = [v[d] - means[d] for d in range(dim)]
        for r in range(dim):
            for c in range(r, dim):
                cov[r][c] += diffs[r] * diffs[c]
    denom = max(n - 1, 1)
    for r in range(dim):
        for c in range(r, dim):
            cov[r][c] /= denom
            cov[c][r] = cov[r][c]
    fb_corr = cov[0][1] / (math.sqrt(max(cov[0][0], 1e-12)) * math.sqrt(max(cov[1][1], 1e-12))) if dim >= 2 else 0.0
    for d in range(dim):
        cov[d][d] = max(cov[d][d], 1.0) + ridge
    return {"inv_cov": _invert_matrix_gauss_jordan(cov), "funding_basis_corr": round(fb_corr, 3)}


def _mahalanobis_dist(a: list[float], b: list[float], inv_cov: list[list[float]]) -> float:
    diff = [x - y for x, y in zip(a, b)]
    dim = len(diff)
    q = sum(diff[r] * sum(inv_cov[r][c] * diff[c] for c in range(dim)) for r in range(dim))
    return math.sqrt(max(q, 0.0))


def _grade_quality(n: int, avg_dist: float, history_days: float, dim: int) -> str:
    thin_d = 2.35 if dim == 5 else 1.85
    solid_d = 1.65 if dim == 5 else 1.25
    if n < 10 or avg_dist > thin_d:
        return "thin"
    if n < 18 or avg_dist > solid_d or history_days < 90.0:
        return "moderate"
    return "solid"


def _summarize_horizon(returns: list[float]) -> dict[str, Any]:
    if not returns:
        return {"median_pct": 0.0, "up_share": 0.0, "median_up_pct": 0.0, "median_down_pct": 0.0, "tail_skew_ratio": 0.0}
    ups = [r for r in returns if r > 0]
    downs = [r for r in returns if r < 0]
    med_up = statistics.median(ups) if ups else 0.0
    med_dn = statistics.median(downs) if downs else 0.0
    skew = round(abs(med_up / med_dn), 2) if abs(med_dn) > 1e-9 else 0.0
    return {
        "median_pct": round(statistics.median(returns), 2),
        "up_share": round((len(ups) / len(returns)) * 100.0, 1),
        "median_up_pct": round(med_up, 2),
        "median_down_pct": round(med_dn, 2),
        "tail_skew_ratio": skew,
    }


def _lift_se_pts(n_sub: int, n_base: int) -> float | None:
    if n_sub <= 0 or n_base <= 0:
        return None
    return round(100.0 * math.sqrt(0.25 * ((1.0 / n_sub) + (1.0 / n_base))), 2)


def _derive_posture(
    quality: str,
    summary_24h: dict[str, Any],
    lift_24h: float,
    lift_se_24h: float | None = None,
) -> tuple[float, str]:
    if quality == "thin":
        return 0.0, "OUTLIER_THIN_ZERO_WEIGHT"
    p_up = summary_24h["up_share"] / 100.0
    ev = round((p_up * summary_24h["median_up_pct"]) + ((1.0 - p_up) * summary_24h["median_down_pct"]), 3)
    min_sig_lift = max(5.0, 2.0 * lift_se_24h) if lift_se_24h is not None else 22.4
    if ev >= 0.25 and lift_24h >= min_sig_lift and summary_24h["tail_skew_ratio"] >= 0.90:
        return ev, "POSITIVE_SKEW_LOOP_A"
    if ev <= -0.25 and lift_24h <= -min_sig_lift:
        return ev, "NEGATIVE_SKEW_LOOP_B"
    return ev, "NEUTRAL_CHOP"


def _decluster_select(cands: list[dict[str, Any]], k: int, min_gap: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for c in sorted(cands, key=lambda x: x["distance"]):
        if all(abs(c["idx"] - s["idx"]) >= min_gap for s in selected):
            selected.append(c)
        if len(selected) == k:
            break
    return selected


def _evaluate_lens(
    lens_id: str,
    features: list[str],
    scales: list[float],
    rows: list[dict[str, Any]],
    z_matrix: dict[str, list[float | None]],
    sma_regimes: list[tuple[float, str]],
    eligible_mask: list[bool],
    current_idx: int,
    cutoff_idx: int,
    z_window: int,
    k: int,
    declustering_hours: int,
    embargo_hours: int,
    max_distance: float,
) -> dict[str, Any]:
    dim = len(features)

    def get_vec(idx: int) -> list[float]:
        return [float(z_matrix[f][idx] if z_matrix[f][idx] is not None else 0.0) * s for f, s in zip(features, scales)]

    cur_vec = get_vec(current_idx)
    cur_reg = sma_regimes[current_idx][1]
    eligible = [
        i
        for i in range(z_window, cutoff_idx)
        if eligible_mask[i] and all(z_matrix[f][i] is not None for f in features)
    ]
    cov_stats = _precision_matrix([get_vec(i) for i in eligible], dim_fallback=dim, ridge=0.05)
    inv_cov = cov_stats["inv_cov"]

    base_all: dict[int, list[float]] = {4: [], 24: [], 72: []}
    base_reg: dict[int, list[float]] = {4: [], 24: [], 72: []}
    cand_all: list[dict[str, Any]] = []
    cand_reg: list[dict[str, Any]] = []

    for i in eligible:
        p0 = float(rows[i]["close"])
        if p0 <= 0:
            continue
        r4 = ((float(rows[i + 4]["close"]) - p0) / p0) * 100.0
        r24 = ((float(rows[i + 24]["close"]) - p0) / p0) * 100.0
        r72 = ((float(rows[i + 72]["close"]) - p0) / p0) * 100.0
        r_reg = sma_regimes[i][1]
        base_all[4].append(r4)
        base_all[24].append(r24)
        base_all[72].append(r72)
        if cur_reg != "UNKNOWN" and r_reg == cur_reg:
            base_reg[4].append(r4)
            base_reg[24].append(r24)
            base_reg[72].append(r72)
        d = _mahalanobis_dist(cur_vec, get_vec(i), inv_cov)
        if d <= max_distance:
            item = {
                "idx": i,
                "iso_utc": rows[i]["iso_utc"],
                "close": round(p0, 2),
                "trend_regime": r_reg,
                "distance": d,
                "ret_4h": r4,
                "ret_24h": r24,
                "ret_72h": r72,
            }
            cand_all.append(item)
            if cur_reg != "UNKNOWN" and r_reg == cur_reg:
                cand_reg.append(item)

    sel_all = _decluster_select(cand_all, k, declustering_hours)
    sel_reg = _decluster_select(cand_reg, k, declustering_hours)
    hist_days = round(sum(1 for f in eligible_mask if f) / 24.0, 1)

    n_found = len(sel_all)
    avg_dist = statistics.fmean([s["distance"] for s in sel_all]) if n_found else 999.0
    quality = _grade_quality(n_found, avg_dist, hist_days, dim)

    n_reg = len(sel_reg)
    avg_reg_d = statistics.fmean([s["distance"] for s in sel_reg]) if n_reg else 999.0
    reg_quality = _grade_quality(n_reg, avg_reg_d, hist_days, dim)

    after_all = {h_k: _summarize_horizon([s[f"ret_{h_k}"] for s in sel_all]) for h_k in ("4h", "24h", "72h")}
    b_all = {h_k: _summarize_horizon(base_all[int(h_k[:-1])]) for h_k in ("4h", "24h", "72h")}
    edge_all = {}
    for h_k in ("4h", "24h", "72h"):
        lift_pts = round(after_all[h_k]["up_share"] - b_all[h_k]["up_share"], 1)
        se_pts = _lift_se_pts(n_found, len(base_all[int(h_k[:-1])]))
        edge_all[h_k] = {
            "up_share_lift_pts": lift_pts,
            "lift_se_pts": se_pts,
            "lift_z_score": round(lift_pts / se_pts, 2) if se_pts else 0.0,
            "median_lift_pct": round(after_all[h_k]["median_pct"] - b_all[h_k]["median_pct"], 2),
        }

    after_reg = {h_k: _summarize_horizon([s[f"ret_{h_k}"] for s in sel_reg]) for h_k in ("4h", "24h", "72h")}
    b_reg = {h_k: _summarize_horizon(base_reg[int(h_k[:-1])]) for h_k in ("4h", "24h", "72h")}
    edge_reg = {}
    for h_k in ("4h", "24h", "72h"):
        lift_pts = round(after_reg[h_k]["up_share"] - b_reg[h_k]["up_share"], 1)
        se_pts = _lift_se_pts(n_reg, len(base_reg[int(h_k[:-1])]))
        edge_reg[h_k] = {
            "up_share_lift_pts": lift_pts,
            "lift_se_pts": se_pts,
            "lift_z_score": round(lift_pts / se_pts, 2) if se_pts else 0.0,
            "median_lift_pct": round(after_reg[h_k]["median_pct"] - b_reg[h_k]["median_pct"], 2),
        }

    ev24, posture = _derive_posture(
        quality,
        after_all["24h"],
        edge_all["24h"]["up_share_lift_pts"],
        edge_all["24h"]["lift_se_pts"],
    )
    return {
        "lens_id": lens_id,
        "dimensions": features,
        "diagnostics": {
            "analogues_found": n_found,
            "target_k": k,
            "history_days": hist_days,
            "total_archive_bars": len(rows),
            "baseline_hours_evaluated": len(base_all[24]),
            "sample_quality": quality,
            "avg_vector_distance": round(avg_dist, 3),
            "funding_basis_correlation": cov_stats["funding_basis_corr"],
            "conditional_ev_24h_pct": ev24,
            "posture_verdict": posture,
            "regime_analogues_found": n_reg,
            "regime_sample_quality": reg_quality,
            "regime_avg_distance": round(avg_reg_d, 3),
            "embargo_hours": embargo_hours,
            "declustering_hours": declustering_hours,
        },
        "after_similar_setups": after_all,
        "baseline_all_hours": b_all,
        "edge_vs_baseline": edge_all,
        "regime_matched_setups": after_reg,
        "regime_baseline_hours": b_reg,
        "regime_edge_vs_baseline": edge_reg,
        "top_analogues": [
            {
                "timestamp_utc": s["iso_utc"],
                "btc_price": s["close"],
                "trend_regime": s["trend_regime"],
                "distance": round(s["distance"], 3),
                "ret_4h_pct": round(s["ret_4h"], 2),
                "ret_24h_pct": round(s["ret_24h"], 2),
                "ret_72h_pct": round(s["ret_72h"], 2),
            }
            for s in sel_all[:10]
        ],
    }


def compute_cortex_rhyme(
    k: int = 20,
    z_window: int = 168,
    embargo_hours: int = 72,
    declustering_hours: int = 24,
) -> dict[str, Any]:
    """Run S2 CORTEX-RHYME v1.2.0 and return compact dual-lens payload for state.json."""
    rows, sync_status = sync_and_load_rows()
    n_total = len(rows)
    if n_total < (z_window + embargo_hours + 48):
        return {
            "meta": {
                "engine": "CORTEX-RHYME",
                "version": "1.2.0",
                "status": "unavailable",
                "disclaimer": "Observational historical statistics only. Not a prediction or financial advice.",
            }
        }

    z_matrix = {feat: _causal_z_scores([float(r[feat]) for r in rows], window=z_window) for feat in FEATURES_5D}
    closes = [float(r["close"]) for r in rows]
    sma_regimes = _compute_causal_sma_regimes(closes, window=SMA_200D_HOURS)

    current_idx = n_total - 1
    current_row = rows[current_idx]
    cutoff_idx = current_idx - embargo_hours
    cur_sma, cur_trend_regime = sma_regimes[current_idx]
    sma_dist_pct = ((closes[current_idx] - cur_sma) / cur_sma) * 100.0 if cur_sma > 0 else 0.0

    mask_5d = [_has_genuine_5d_telemetry(r) for r in rows]
    mask_3d = [True] * n_total

    lens_5d = _evaluate_lens(
        "5D_MICROSTRUCTURE", FEATURES_5D, PRIOR_SCALES_5D, rows, z_matrix, sma_regimes,
        mask_5d, current_idx, cutoff_idx, z_window, k, declustering_hours, embargo_hours, 2.65,
    )
    lens_3d = _evaluate_lens(
        "3D_DEEP_CARRY_VOL", FEATURES_3D, PRIOR_SCALES_3D, rows, z_matrix, sma_regimes,
        mask_3d, current_idx, cutoff_idx, z_window, k, declustering_hours, embargo_hours, 2.05,
    )

    q5, q3 = lens_5d["diagnostics"]["sample_quality"], lens_3d["diagnostics"]["sample_quality"]
    n5, n3 = lens_5d["diagnostics"]["analogues_found"], lens_3d["diagnostics"]["analogues_found"]
    fallback_triggered = False
    fallback_reason: str | None = None
    active_lens = lens_5d
    if q5 == "thin" and (q3 in ("solid", "moderate") or n3 > n5):
        active_lens = lens_3d
        fallback_triggered = True
        fallback_reason = f"5D lens graded THIN (n={n5}); promoted {lens_3d['diagnostics']['history_days']}d 3D Carry-Vol lens (grade={q3.upper()}, n={n3})."

    active_diag = dict(active_lens["diagnostics"])
    active_diag["active_lens"] = active_lens["lens_id"]
    active_diag["fallback_triggered"] = fallback_triggered
    active_diag["fallback_reason"] = fallback_reason

    return {
        "meta": {
            "engine": "CORTEX-RHYME",
            "version": "1.2.0",
            "active_lens": active_lens["lens_id"],
            "distance_metric": "regularized_mahalanobis_dual_lens",
            "instrument": "BTC-USDT-SWAP",
            "status": sync_status,
            "as_of_utc": current_row["iso_utc"],
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "history_sources": ["OKX Public v5 Keyless Archive"],
            "disclaimer": "Observational historical statistics only. Never issues a trade, size, or permission.",
        },
        "current_state": {
            "btc_price": round(float(current_row["close"]), 2),
            "regime_context": {
                "trend_regime": cur_trend_regime,
                "sma_200d": round(cur_sma, 2),
                "distance_from_sma_200d_pct": round(sma_dist_pct, 2),
            },
            "raw_metrics": {
                "funding_rate_pct": round(float(current_row["funding_rate"]) * 100.0, 4),
                "basis_bps": round(float(current_row["basis_bps"]), 2),
                "oi_delta_24h_pct": round(float(current_row["oi_delta_24h"]), 2),
                "gk_vol_24h_ann_pct": round(float(current_row["gk_vol_24h"]) * 100.0, 2),
                "taker_buy_ratio": round(float(current_row["taker_buy_ratio"]), 4),
                "live_l2_imbalance": current_row.get("live_l2_imbalance"),
            },
            "z_vector": {
                feat: round(v, 3) if isinstance(v, (int, float)) else None
                for feat in FEATURES_5D
                for v in (z_matrix[feat][current_idx],)
            },
        },
        "diagnostics": active_diag,
        "after_similar_setups": active_lens["after_similar_setups"],
        "baseline_all_hours": active_lens["baseline_all_hours"],
        "edge_vs_baseline": active_lens["edge_vs_baseline"],
        "regime_matched_setups": active_lens["regime_matched_setups"],
        "regime_baseline_hours": active_lens["regime_baseline_hours"],
        "regime_edge_vs_baseline": active_lens["regime_edge_vs_baseline"],
        "top_analogues": active_lens["top_analogues"],
        "lenses": {
            "5D_MICROSTRUCTURE": lens_5d,
            "3D_DEEP_CARRY_VOL": lens_3d,
        },
    }
