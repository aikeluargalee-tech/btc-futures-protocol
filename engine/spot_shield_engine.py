"""Project F: Dual-Sleeve Spot Shield (80/20) causal signal engine in pure Python stdlib."""
from __future__ import annotations

import datetime as dt
import json
import math
import time
import urllib.request
from typing import Any

BINANCE_VISION = "https://data-api.binance.vision/api/v3"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) btc-futures-protocol/1.0"}

SLEEVE1_PARAMS: dict[str, Any] = {
    "weight_pct": 80,
    "timeframe": "4h",
    "vwap_window": 90,
    "slope_window": 12,
    "macro_ema_days": 120,
    "atr_len": 14,
    "buffer_atr": 0.50,
    "atr_sl_mult": 3.0,
}

SLEEVE2_PARAMS: dict[str, Any] = {
    "weight_pct": 20,
    "timeframe": "1d",
    "bb_len": 20,
    "bb_mult": 2.0,
    "kc_len": 20,
    "kc_mult": 1.50,
    "squeeze_bars": 3,
    "mom_len": 20,
    "exit_sma_len": 21,
    "atr_sl_len": 14,
    "atr_sl_mult": 2.0,
}


def fetch_binance_spot_closed_klines(
    interval: str,
    limit: int,
    errors: list[str],
    now_ms: int | None = None,
) -> list[dict[str, float]]:
    """Fetch strictly closed Binance Spot BTCUSDT OHLCV bars."""
    url = f"{BINANCE_VISION}/klines?symbol=BTCUSDT&interval={interval}&limit={min(limit, 1000)}"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=12) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        code = getattr(exc, "code", "")
        errors.append(f"SpotShield BinanceVision {interval}: {type(exc).__name__} {code}".strip())
        return []

    if not isinstance(rows, list) or len(rows) < 5:
        errors.append(f"SpotShield BinanceVision {interval}: empty klines response")
        return []

    cutoff_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    out: list[dict[str, float]] = []
    for row in rows:
        close_ms = int(row[6])
        if close_ms > cutoff_ms:
            continue
        out.append(
            {
                "ts": int(row[0]),
                "close_ts": close_ms,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )
    return out


def _ewm_adjust_false(values: list[float | None], alpha: float, min_periods: int) -> list[float | None]:
    """Exact pandas `ewm(alpha=alpha, adjust=False, min_periods=min_periods).mean()` replica."""
    out: list[float | None] = [None] * len(values)
    state: float | None = None
    count = 0
    for i, v in enumerate(values):
        if v is None or math.isnan(v):
            continue
        count += 1
        state = v if state is None else (alpha * v + (1.0 - alpha) * state)
        if count >= min_periods:
            out[i] = state
    return out


def _ema(values: list[float | None], length: int) -> list[float | None]:
    return _ewm_adjust_false(values, 2.0 / (float(length) + 1.0), length)


def _rma(values: list[float | None], length: int) -> list[float | None]:
    return _ewm_adjust_false(values, 1.0 / float(length), length)


def _true_range(bars: list[dict[str, float]]) -> list[float | None]:
    out: list[float | None] = []
    for i, b in enumerate(bars):
        if i == 0:
            out.append(b["high"] - b["low"])
        else:
            prev_c = bars[i - 1]["close"]
            out.append(max(b["high"] - b["low"], abs(b["high"] - prev_c), abs(b["low"] - prev_c)))
    return out


def _atr_wilder(bars: list[dict[str, float]], length: int) -> list[float | None]:
    return _rma(_true_range(bars), length)


def _rolling_sma_and_std_pop(values: list[float], window: int) -> tuple[list[float | None], list[float | None]]:
    """Causal rolling mean and population std (ddof=0)."""
    n = len(values)
    means: list[float | None] = [None] * n
    stds: list[float | None] = [None] * n
    if n < window or window <= 0:
        return means, stds
    for i in range(window - 1, n):
        chunk = values[i - window + 1 : i + 1]
        m = sum(chunk) / float(window)
        var = sum((x - m) ** 2 for x in chunk) / float(window)
        means[i] = m
        stds[i] = math.sqrt(max(0.0, var))
    return means, stds


def _rolling_linreg_endpoint(values: list[float | None], window: int = 20) -> list[float | None]:
    """Strictly causal OLS linear-regression endpoint value over `window` closed bars."""
    n = len(values)
    out: list[float | None] = [None] * n
    if n < window or window < 2:
        return out
    x_mean = (window - 1) / 2.0
    s_xx = sum((k - x_mean) ** 2 for k in range(window))
    weights = [(1.0 / float(window)) + ((k - x_mean) * (float(window - 1) - x_mean) / s_xx) for k in range(window)]

    for i in range(window - 1, n):
        seg = values[i - window + 1 : i + 1]
        if any(v is None or math.isnan(v) for v in seg):
            continue
        out[i] = sum(float(v) * w for v, w in zip(seg, weights))
    return out


def _iso_from_ms(ts_ms: int | float) -> str:
    return dt.datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _simulate_4state_action(
    bars: list[dict[str, float]],
    signals: list[int],
    stops: list[float | None],
) -> dict[str, Any]:
    """Replay strictly causal bar t+1 fills + intrabar stops to determine latest 4-state posture."""
    n = len(bars)
    if n == 0:
        return {
            "action": "HOLD USDT",
            "position_state": "FLAT",
            "active_stop_loss": None,
            "entry_price": None,
            "entry_utc": None,
            "last_flip_utc": None,
            "days_in_state": 0.0,
        }

    holding_btc = False
    active_stop: float | None = None
    entry_price: float | None = None
    entry_ts: int | None = None
    last_flip_ts: int = int(bars[0]["ts"])

    prev_sig = 0
    prev_stop: float | None = None

    for i in range(n):
        b = bars[i]
        ts = int(b["ts"])
        if i > 0:
            if prev_sig == 1 and not holding_btc:
                holding_btc = True
                active_stop = prev_stop
                entry_price = float(b["open"])
                entry_ts = ts
                last_flip_ts = ts
            elif prev_sig == -1 and holding_btc:
                holding_btc = False
                active_stop = None
                entry_price = None
                entry_ts = None
                last_flip_ts = ts

        if holding_btc and active_stop is not None and b["low"] <= active_stop:
            holding_btc = False
            active_stop = None
            entry_price = None
            entry_ts = None
            last_flip_ts = ts

        prev_sig = signals[i]
        prev_stop = stops[i]

    last_bar = bars[-1]
    last_sig = signals[-1]
    pending_stop = stops[-1]
    last_close_ts = int(last_bar.get("close_ts") or (int(last_bar["ts"]) + 1))

    if last_sig == 1:
        if not holding_btc:
            action = "BUY BTC"
            shown_stop = pending_stop
        else:
            action = "HOLD BTC"
            shown_stop = active_stop
    elif last_sig == -1:
        action = "SELL BTC" if holding_btc else "HOLD USDT"
        shown_stop = None
    else:
        action = "HOLD BTC" if holding_btc else "HOLD USDT"
        shown_stop = active_stop if holding_btc else None

    days_in_state = round(max(0.0, (last_close_ts - last_flip_ts) / 86_400_000.0), 1)
    return {
        "action": action,
        "position_state": "LONG" if holding_btc else "FLAT",
        "active_stop_loss": round(shown_stop, 2) if shown_stop is not None else None,
        "entry_price": round(entry_price, 2) if entry_price is not None else None,
        "entry_utc": _iso_from_ms(entry_ts) if entry_ts is not None else None,
        "last_flip_utc": _iso_from_ms(last_flip_ts),
        "days_in_state": days_in_state,
    }


def evaluate_sleeve1_vwap_shield(
    bars_4h: list[dict[str, float]],
    bars_1d: list[dict[str, float]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute strictly causal 4H Rolling VWAP + 120D EMA Shield signals and live state."""
    p = {**SLEEVE1_PARAMS, **(params or {})}
    n4 = len(bars_4h)
    vwap_win = int(p["vwap_window"])
    slope_win = int(p["slope_window"])
    ema_days = int(p["macro_ema_days"])
    atr_len = int(p["atr_len"])
    buf_atr = float(p["buffer_atr"])
    sl_mult = float(p["atr_sl_mult"])

    if n4 < vwap_win + slope_win or len(bars_1d) < ema_days:
        return {"status": "unavailable", "reason": "Insufficient warmup bars for Sleeve #1"}

    # Daily 120-EMA aligned strictly from completed prior UTC days (no intrabar daily peek).
    d_closes: list[float | None] = [float(b["close"]) for b in bars_1d]
    d_ema = _ema(d_closes, ema_days)
    daily_points: list[tuple[int, float]] = []
    for db, ev in zip(bars_1d, d_ema):
        if ev is None:
            continue
        # Day bar at `ts` completes at `day_start + 86_400_000` ms.
        d_day_end = (int(db["ts"]) // 86_400_000 + 1) * 86_400_000
        daily_points.append((d_day_end, ev))

    macro_1d_ema: list[float | None] = [None] * n4
    dp_idx = 0
    for i, b in enumerate(bars_4h):
        bar_ts = int(b["ts"])
        while dp_idx + 1 < len(daily_points) and daily_points[dp_idx + 1][0] <= bar_ts:
            dp_idx += 1
        if daily_points and daily_points[dp_idx][0] <= bar_ts:
            macro_1d_ema[i] = daily_points[dp_idx][1]

    rolling_vwap: list[float | None] = [None] * n4
    for i in range(vwap_win - 1, n4):
        pv = 0.0
        vs = 0.0
        for j in range(i - vwap_win + 1, i + 1):
            bj = bars_4h[j]
            tp = (bj["high"] + bj["low"] + bj["close"]) / 3.0
            vol = bj["volume"]
            pv += tp * vol
            vs += vol
        if vs > 0.0:
            rolling_vwap[i] = pv / vs

    vwap_slope: list[float | None] = [None] * n4
    for i in range(slope_win, n4):
        cur_v = rolling_vwap[i]
        prev_v = rolling_vwap[i - slope_win]
        if cur_v is not None and prev_v is not None:
            vwap_slope[i] = cur_v - prev_v

    atr14 = _atr_wilder(bars_4h, atr_len)

    signals: list[int] = [0] * n4
    stops: list[float | None] = [None] * n4

    for i, b in enumerate(bars_4h):
        c = b["close"]
        rv = rolling_vwap[i]
        slp = vwap_slope[i]
        a = atr14[i]
        m = macro_1d_ema[i]
        if rv is None or slp is None or a is None or m is None:
            continue
        upper = rv + buf_atr * a
        lower = rv - buf_atr * a
        if c > m and c > upper and slp > 0.0:
            signals[i] = 1
            stops[i] = c - sl_mult * a
        elif c < m or c < lower:
            signals[i] = -1

    sim = _simulate_4state_action(bars_4h, signals, stops)

    lc = bars_4h[-1]["close"]
    lrv = rolling_vwap[-1]
    lslp = vwap_slope[-1]
    latr = atr14[-1]
    lm = macro_1d_ema[-1]
    upper_now = (lrv + buf_atr * latr) if (lrv is not None and latr is not None) else None
    lower_now = (lrv - buf_atr * latr) if (lrv is not None and latr is not None) else None

    return {
        "status": "LIVE",
        "strategy_id": "tier1_5_vwap_shield",
        "name": "4H Rolling VWAP Shield",
        "weight_pct": p["weight_pct"],
        "timeframe": "4h",
        "last_bar_utc": _iso_from_ms(bars_4h[-1]["ts"]),
        "bars_evaluated": n4,
        "latest_signal": signals[-1],
        **sim,
        "indicators": {
            "close": round(lc, 2),
            "macro_120d_ema": round(lm, 2) if lm is not None else None,
            "dist_to_macro_ema_pct": round(((lc / lm) - 1.0) * 100.0, 2) if lm else None,
            "rolling_vwap_90": round(lrv, 2) if lrv is not None else None,
            "vwap_slope_12": round(lslp, 2) if lslp is not None else None,
            "atr_14": round(latr, 2) if latr is not None else None,
            "upper_band": round(upper_now, 2) if upper_now is not None else None,
            "lower_band": round(lower_now, 2) if lower_now is not None else None,
            "dist_to_upper_band_pct": round(((lc / upper_now) - 1.0) * 100.0, 2) if upper_now else None,
        },
        "conditions": {
            "above_120d_ema": bool(lm is not None and lc > lm),
            "above_upper_band": bool(upper_now is not None and lc > upper_now),
            "vwap_slope_rising": bool(lslp is not None and lslp > 0.0),
            "below_lower_band": bool(lower_now is not None and lc < lower_now),
        },
        "series": {
            "signals": signals,
            "stops": [round(x, 2) if x is not None else None for x in stops],
        },
    }


def evaluate_sleeve2_ttm_squeeze(
    bars_1d: list[dict[str, float]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute strictly causal Daily TTM Volatility Squeeze Breakout signals and live state."""
    p = {**SLEEVE2_PARAMS, **(params or {})}
    n1 = len(bars_1d)
    bb_len = int(p["bb_len"])
    bb_mult = float(p["bb_mult"])
    kc_len = int(p["kc_len"])
    kc_mult = float(p["kc_mult"])
    sq_bars = int(p["squeeze_bars"])
    mom_len = int(p["mom_len"])
    exit_sma_len = int(p["exit_sma_len"])
    atr_sl_len = int(p["atr_sl_len"])
    sl_mult = float(p["atr_sl_mult"])

    if n1 < max(bb_len, kc_len, mom_len, exit_sma_len, atr_sl_len) + sq_bars + 5:
        return {"status": "unavailable", "reason": "Insufficient daily bars for Sleeve #2"}

    closes = [float(b["close"]) for b in bars_1d]
    highs = [float(b["high"]) for b in bars_1d]
    lows = [float(b["low"]) for b in bars_1d]
    closes_opt: list[float | None] = [c for c in closes]

    bb_mid, bb_std = _rolling_sma_and_std_pop(closes, bb_len)
    kc_mid = _ema(closes_opt, kc_len)
    atr_kc = _atr_wilder(bars_1d, kc_len)
    sma_exit, _ = _rolling_sma_and_std_pop(closes, exit_sma_len)
    atr_sl = _atr_wilder(bars_1d, atr_sl_len)

    bb_up: list[float | None] = [None] * n1
    bb_lo: list[float | None] = [None] * n1
    kc_up: list[float | None] = [None] * n1
    kc_lo: list[float | None] = [None] * n1
    squeeze_on: list[bool | None] = [None] * n1

    for i in range(n1):
        if bb_mid[i] is not None and bb_std[i] is not None:
            bb_up[i] = bb_mid[i] + bb_mult * bb_std[i]
            bb_lo[i] = bb_mid[i] - bb_mult * bb_std[i]
        if kc_mid[i] is not None and atr_kc[i] is not None:
            kc_up[i] = kc_mid[i] + kc_mult * atr_kc[i]
            kc_lo[i] = kc_mid[i] - kc_mult * atr_kc[i]
        if bb_up[i] is not None and bb_lo[i] is not None and kc_up[i] is not None and kc_lo[i] is not None:
            squeeze_on[i] = (bb_up[i] < kc_up[i]) and (bb_lo[i] > kc_lo[i])

    delta: list[float | None] = [None] * n1
    for i in range(mom_len - 1, n1):
        if bb_mid[i] is None:
            continue
        hi_m = max(highs[i - mom_len + 1 : i + 1])
        lo_m = min(lows[i - mom_len + 1 : i + 1])
        don_mid = 0.5 * (hi_m + lo_m)
        delta[i] = closes[i] - 0.5 * (don_mid + bb_mid[i])

    mom = _rolling_linreg_endpoint(delta, window=mom_len)

    signals: list[int] = [0] * n1
    stops: list[float | None] = [None] * n1
    squeeze_releases: list[bool] = [False] * n1

    for i in range(sq_bars + 1, n1):
        if (
            squeeze_on[i] is None
            or kc_mid[i] is None
            or mom[i] is None
            or mom[i - 1] is None
            or sma_exit[i] is None
            or atr_sl[i] is None
        ):
            continue
        prev_sq = [squeeze_on[i - k] for k in range(1, sq_bars + 1)]
        had_sq = all(v is True for v in prev_sq)
        rel = (squeeze_on[i] is False) and had_sq
        squeeze_releases[i] = rel

        c = closes[i]
        exit_cond = (c < sma_exit[i]) or (mom[i] < 0.0)
        buy_cond = (not exit_cond) and rel and (mom[i] > 0.0) and (mom[i] > mom[i - 1]) and (c > kc_mid[i])
        if exit_cond:
            signals[i] = -1
        elif buy_cond:
            signals[i] = 1
            stops[i] = c - sl_mult * atr_sl[i]

    sim = _simulate_4state_action(bars_1d, signals, stops)

    streak = 0
    for j in range(n1 - 1, -1, -1):
        if squeeze_on[j] is True:
            streak += 1
        else:
            break

    lbb_w = (bb_up[-1] - bb_lo[-1]) if (bb_up[-1] is not None and bb_lo[-1] is not None) else None
    lkc_w = (kc_up[-1] - kc_lo[-1]) if (kc_up[-1] is not None and kc_lo[-1] is not None) else None
    ratio = round(lbb_w / lkc_w, 3) if (lbb_w is not None and lkc_w and lkc_w > 0) else None

    return {
        "status": "LIVE",
        "strategy_id": "tier14_ttm_squeeze_1d",
        "name": "1D TTM Squeeze Breakout",
        "weight_pct": p["weight_pct"],
        "timeframe": "1d",
        "last_bar_utc": _iso_from_ms(bars_1d[-1]["ts"]),
        "bars_evaluated": n1,
        "latest_signal": signals[-1],
        **sim,
        "indicators": {
            "close": round(closes[-1], 2),
            "squeeze_on": bool(squeeze_on[-1]) if squeeze_on[-1] is not None else False,
            "squeeze_streak_days": streak,
            "squeeze_released_today": bool(squeeze_releases[-1]),
            "bb_kc_width_ratio": ratio,
            "mom_ols": round(mom[-1], 2) if mom[-1] is not None else None,
            "prev_mom_ols": round(mom[-2], 2) if len(mom) >= 2 and mom[-2] is not None else None,
            "kc_mid_ema20": round(kc_mid[-1], 2) if kc_mid[-1] is not None else None,
            "sma_21_exit": round(sma_exit[-1], 2) if sma_exit[-1] is not None else None,
            "atr_14": round(atr_sl[-1], 2) if atr_sl[-1] is not None else None,
        },
        "conditions": {
            "squeeze_armed_3d": bool(squeeze_on[-1] and streak >= sq_bars) or bool(squeeze_releases[-1]),
            "squeeze_release": bool(squeeze_releases[-1]),
            "mom_positive": bool(mom[-1] is not None and mom[-1] > 0.0),
            "mom_rising": bool(mom[-1] is not None and mom[-2] is not None and mom[-1] > mom[-2]),
            "above_kc_mid": bool(kc_mid[-1] is not None and closes[-1] > kc_mid[-1]),
            "above_sma_21": bool(sma_exit[-1] is not None and closes[-1] >= sma_exit[-1]),
        },
        "series": {
            "signals": signals,
            "stops": [round(x, 2) if x is not None else None for x in stops],
        },
    }


def _next_quarter_rebalance(now_utc: dt.datetime) -> dict[str, Any]:
    year = now_utc.year
    for m in (1, 4, 7, 10):
        cand = dt.datetime(year, m, 1, 0, 0, tzinfo=dt.timezone.utc)
        if cand > now_utc:
            days = round((cand - now_utc).total_seconds() / 86400.0, 1)
            return {"next_rebalance_utc": cand.strftime("%Y-%m-%dT%H:%M:%SZ"), "days_remaining": days, "drift_band_pct": 3.0}
    cand = dt.datetime(year + 1, 1, 1, 0, 0, tzinfo=dt.timezone.utc)
    days = round((cand - now_utc).total_seconds() / 86400.0, 1)
    return {"next_rebalance_utc": cand.strftime("%Y-%m-%dT%H:%M:%SZ"), "days_remaining": days, "drift_band_pct": 3.0}


def compute_spot_shield(now_utc: dt.datetime | None = None) -> dict[str, Any]:
    """Fetch strictly closed Binance Spot 4H & 1D bars and compute Project F 80/20 Spot Shield."""
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    errors: list[str] = []

    bars_4h = fetch_binance_spot_closed_klines("4h", 1000, errors, now_ms=now_ms)
    bars_1d = fetch_binance_spot_closed_klines("1d", 400, errors, now_ms=now_ms)

    if not bars_4h or not bars_1d:
        return {
            "status": "unavailable",
            "updated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "errors": errors,
        }

    s1 = evaluate_sleeve1_vwap_shield(bars_4h, bars_1d)
    s2 = evaluate_sleeve2_ttm_squeeze(bars_1d)

    # Strip internal bar-level series before storing compact telemetry in state.json
    s1_compact = {k: v for k, v in s1.items() if k != "series"}
    s2_compact = {k: v for k, v in s2.items() if k != "series"}

    s1_in_btc = s1_compact.get("action") in ("BUY BTC", "HOLD BTC")
    s2_in_btc = s2_compact.get("action") in ("BUY BTC", "HOLD BTC")
    btc_alloc = (80 if s1_in_btc else 0) + (20 if s2_in_btc else 0)
    usdt_alloc = 100 - btc_alloc

    return {
        "status": "LIVE" if (s1_compact.get("status") == "LIVE" and s2_compact.get("status") == "LIVE") else "PARTIAL",
        "version": "1.0",
        "updated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Binance Spot BTCUSDT (data-api.binance.vision, closed bars only)",
        "portfolio": {
            "split_label": "80% 4H VWAP Shield / 20% 1D TTM Squeeze",
            "target_btc_pct": btc_alloc,
            "target_usdt_pct": usdt_alloc,
            "posture_label": (
                "100% BTC (FULL RISK-ON)"
                if btc_alloc == 100
                else ("80% BTC / 20% USDT (CORE TREND)" if btc_alloc == 80 else ("20% BTC / 80% USDT (SQUEEZE PROBE)" if btc_alloc == 20 else "100% USDT (BEAR SHIELD ACTIVE)"))
            ),
            "quarterly_rebalance": _next_quarter_rebalance(now),
        },
        "sleeve1": s1_compact,
        "sleeve2": s2_compact,
        "audit_warnings": {
            "capital_separation": "Slow mechanical BTCUSDT paper/spot compass — keep strictly separate from F3 Spot Magnet (DIBSE) core reserve.",
            "sleeve1_realistic_expectation": "27/27 parameter stability beats B&H, but live baseline (~0.90-0.95 Sharpe, -30% DD, 27% WR, up to 9-loss streak, ~65% time in USDT) is softer than #2 rank peak.",
            "sleeve2_sample_warning": "Experimental 1D volatility breakout built on 18 historical trades (8/27 passed blend gate); hard-capped at 15%-20% weight.",
            "fee_schedule_note": "Backtested at 0.30% RT (0.10% fee + 0.05% slip/side); BNB fee discount lowers exchange fee to 0.075%. 4H closes MYT: 00/04/08/12/16/20.",
        },
        "errors": errors,
    }
