"""Pure-Python technical indicators, market structure, and volume profile helpers."""
from __future__ import annotations

import math
from typing import Any


def ema_series(values: list[float], period: int) -> list[float]:
    """Compute an EMA series seeded by the initial SMA of length `period`."""
    if not values or period <= 0 or len(values) < period:
        return []
    k = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period
    out = [seed]
    prev = seed
    for v in values[period:]:
        prev = v * k + prev * (1.0 - k)
        out.append(prev)
    return out


def sma(values: list[float], period: int) -> float | None:
    """Return latest simple moving average over `period` items."""
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder RSI(14) on closed prices."""
    if len(closes) <= period:
        return None
    gains = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    losses = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
    if avg_l == 0.0:
        return 100.0
    rs = avg_g / avg_l
    return round(100.0 - 100.0 / (1.0 + rs), 2)


def atr(candles: list[dict[str, float]], period: int = 14) -> float | None:
    """Wilder ATR(14) from OHLCV candle dicts."""
    if len(candles) <= period:
        return None
    trs: list[float] = []
    for prev, cur in zip(candles, candles[1:]):
        tr = max(
            cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    val = sum(trs[:period]) / period
    for tr in trs[period:]:
        val = (val * (period - 1) + tr) / period
    return val


def atr_series(candles: list[dict[str, float]], period: int = 14) -> list[float]:
    """Return rolling ATR series."""
    if len(candles) <= period:
        return []
    trs = [
        max(
            cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]),
        )
        for prev, cur in zip(candles, candles[1:])
    ]
    if len(trs) < period:
        return []
    val = sum(trs[:period]) / period
    out = [val]
    for tr in trs[period:]:
        val = (val * (period - 1) + tr) / period
        out.append(val)
    return out


def roc(closes: list[float], period: int) -> float | None:
    """Percentage rate-of-change over `period` bars."""
    if len(closes) <= period or closes[-1 - period] <= 0:
        return None
    return (closes[-1] / closes[-1 - period] - 1.0) * 100.0


def realized_vol_annualized(closes: list[float], window: int, periods_per_year: float = 365.0) -> float | None:
    """Annualized log-return realized volatility (%) over `window` periods."""
    if len(closes) < window + 1 or window < 2:
        return None
    seg = closes[-(window + 1) :]
    rets = [math.log(b / a) for a, b in zip(seg, seg[1:]) if a > 0 and b > 0]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * periods_per_year) * 100.0


def rolling_rv_series(closes: list[float], window: int, periods_per_year: float = 365.0) -> list[float]:
    """Compute historical rolling realized volatility series for percentile ranking."""
    out: list[float] = []
    if len(closes) < window + 1:
        return out
    for idx in range(window + 1, len(closes) + 1):
        rv = realized_vol_annualized(closes[:idx], window, periods_per_year)
        if rv is not None:
            out.append(rv)
    return out


def percentile_rank(value: float, population: list[float]) -> float | None:
    """Return 0-100 percentile rank of `value` within `population`."""
    if not population:
        return None
    below = sum(1 for x in population if x <= value)
    return round((below / len(population)) * 100.0, 2)


def swing_pivots(
    candles: list[dict[str, float]], left: int = 3, right: int = 3
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Detect confirmed fractal swing highs and swing lows."""
    highs: list[dict[str, Any]] = []
    lows: list[dict[str, Any]] = []
    if len(candles) < left + right + 1:
        return highs, lows
    for i in range(left, len(candles) - right):
        hi = candles[i]["high"]
        lo = candles[i]["low"]
        win_hi = [candles[j]["high"] for j in range(i - left, i + right + 1) if j != i]
        win_lo = [candles[j]["low"] for j in range(i - left, i + right + 1) if j != i]
        if all(hi >= x for x in win_hi) and any(hi > x for x in win_hi):
            highs.append({"idx": i, "ts": candles[i]["ts"], "price": hi})
        if all(lo <= x for x in win_lo) and any(lo < x for x in win_lo):
            lows.append({"idx": i, "ts": candles[i]["ts"], "price": lo})
    return highs, lows


def analyze_structure(candles: list[dict[str, float]], left: int = 3, right: int = 3) -> dict[str, Any]:
    """Classify HH/HL vs LH/LL structure from confirmed pivots."""
    highs, lows = swing_pivots(candles, left=left, right=right)
    state = "MIXED"
    score = 50.0
    hh = hl = lh = ll = False
    if len(highs) >= 2 and len(lows) >= 2:
        h1, h2 = highs[-2]["price"], highs[-1]["price"]
        l1, l2 = lows[-2]["price"], lows[-1]["price"]
        hh = h2 > h1
        hl = l2 > l1
        lh = h2 < h1
        ll = l2 < l1
        if hh and hl:
            state = "BULLISH_HH_HL"
            score = 88.0
        elif lh and ll:
            state = "BEARISH_LH_LL"
            score = 12.0
        elif hh and not ll:
            state = "LEAN_BULL"
            score = 66.0
        elif ll and not hh:
            state = "LEAN_BEAR"
            score = 34.0
        else:
            state = "CHOPPY_RANGE"
            score = 50.0
    return {
        "state": state,
        "score": score,
        "last_swing_high": highs[-1]["price"] if highs else None,
        "prev_swing_high": highs[-2]["price"] if len(highs) >= 2 else None,
        "last_swing_low": lows[-1]["price"] if lows else None,
        "prev_swing_low": lows[-2]["price"] if len(lows) >= 2 else None,
        "swing_highs": highs[-5:],
        "swing_lows": lows[-5:],
    }


def volume_profile(candles: list[dict[str, float]], bin_width: float = 100.0) -> dict[str, float] | None:
    """Compute POC, VAH, VAL (70% value area) over closed candles."""
    if not candles:
        return None
    bins: dict[int, float] = {}
    for c in candles:
        lo_b = int(c["low"] // bin_width)
        hi_b = int(c["high"] // bin_width)
        span = max(1, hi_b - lo_b + 1)
        vol_share = c["volume"] / span
        for b in range(lo_b, hi_b + 1):
            bins[b] = bins.get(b, 0.0) + vol_share
    if not bins:
        return None
    total = sum(bins.values())
    if total <= 0:
        return None
    poc_bin = max(bins, key=lambda k: bins[k])
    lo = hi = poc_bin
    acc = bins[poc_bin]
    while acc < 0.70 * total:
        up = bins.get(hi + 1, 0.0)
        dn = bins.get(lo - 1, 0.0)
        if up == 0.0 and dn == 0.0:
            break
        if up >= dn:
            hi += 1
            acc += up
        else:
            lo -= 1
            acc += dn
    return {
        "poc": round(poc_bin * bin_width + bin_width / 2.0, 1),
        "vah": round((hi + 1) * bin_width, 1),
        "val": round(lo * bin_width, 1),
    }


def detect_execution_confirmation(
    candles_4h: list[dict[str, float]],
    direction: str,
    level_price: float | None,
    min_wick_ratio: float = 1.5,
    min_vol_ratio: float = 0.9,
) -> dict[str, Any]:
    """Check closed 4H bar for structure break or rejection candle with supporting volume."""
    if len(candles_4h) < 25:
        return {"confirmed": False, "type": None, "reason": "Insufficient 4H history"}

    last = candles_4h[-1]
    prev_20_vol = sma([c["volume"] for c in candles_4h[:-1]], 20) or 1.0
    vol_ratio = last["volume"] / prev_20_vol if prev_20_vol > 0 else 1.0

    # Short-term 4H structure break: last closed 4H close breaks recent 6-bar (24h) or swing pivot high/low
    recent_6 = candles_4h[-7:-1]
    recent_high = max(c["high"] for c in recent_6)
    recent_low = min(c["low"] for c in recent_6)

    body = abs(last["close"] - last["open"])
    rng = max(last["high"] - last["low"], 1e-6)
    lower_wick = min(last["open"], last["close"]) - last["low"]
    upper_wick = last["high"] - max(last["open"], last["close"])

    if direction == "LONG":
        bos = last["close"] > recent_high
        bull_close = last["close"] > last["open"]
        # Rejection candle: meaningful lower wick piercing/testing near level & closing in upper half
        close_pos = (last["close"] - last["low"]) / rng
        wick_ok = lower_wick >= max(body * min_wick_ratio, rng * 0.38) and close_pos >= 0.55
        touched_level = level_price is None or (last["low"] <= level_price * 1.006 and last["close"] >= level_price * 0.996)
        rejection = wick_ok and touched_level and vol_ratio >= min_vol_ratio
        if bos and bull_close:
            return {
                "confirmed": True,
                "type": "STRUCTURE_BREAK",
                "vol_ratio": round(vol_ratio, 2),
                "detail": f"4H close {last['close']:.1f} broke 24h high {recent_high:.1f} (vol {vol_ratio:.2f}x)",
            }
        if rejection:
            return {
                "confirmed": True,
                "type": "REJECTION_CANDLE",
                "vol_ratio": round(vol_ratio, 2),
                "detail": f"4H bullish wick rejection off {level_price:.1f} (vol {vol_ratio:.2f}x)",
            }
        return {
            "confirmed": False,
            "type": None,
            "vol_ratio": round(vol_ratio, 2),
            "reason": f"No 4H bullish BOS (> {recent_high:.1f}) or qualifying rejection candle (vol {vol_ratio:.2f}x)",
        }

    # SHORT
    bos = last["close"] < recent_low
    bear_close = last["close"] < last["open"]
    close_pos = (last["high"] - last["close"]) / rng
    wick_ok = upper_wick >= max(body * min_wick_ratio, rng * 0.38) and close_pos >= 0.55
    touched_level = level_price is None or (last["high"] >= level_price * 0.994 and last["close"] <= level_price * 1.004)
    rejection = wick_ok and touched_level and vol_ratio >= min_vol_ratio
    if bos and bear_close:
        return {
            "confirmed": True,
            "type": "STRUCTURE_BREAK",
            "vol_ratio": round(vol_ratio, 2),
            "detail": f"4H close {last['close']:.1f} broke 24h low {recent_low:.1f} (vol {vol_ratio:.2f}x)",
        }
    if rejection:
        return {
            "confirmed": True,
            "type": "REJECTION_CANDLE",
            "vol_ratio": round(vol_ratio, 2),
            "detail": f"4H bearish wick rejection off {level_price:.1f} (vol {vol_ratio:.2f}x)",
        }
    return {
        "confirmed": False,
        "type": None,
        "vol_ratio": round(vol_ratio, 2),
        "reason": f"No 4H bearish BOS (< {recent_low:.1f}) or qualifying rejection candle (vol {vol_ratio:.2f}x)",
    }
