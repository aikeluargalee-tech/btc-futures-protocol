#!/usr/bin/env python3
"""Salam Data Packet Protocol (SDPP) v1.7 — single file, standard library only.

Fetch -> compute -> write SALAM_DATA_HUB.md. No state, no database, no dependencies.

    python3 salam_protocol.py                 # writes ./SALAM_DATA_HUB.md
    python3 salam_protocol.py --out dir/      # writes elsewhere
    python3 salam_protocol.py --stdout        # print instead of write
    python3 salam_protocol.py --json          # also write SALAM_DATA_HUB.json
    python3 salam_protocol.py --check         # endpoint health only

Discipline:
  * closed bars only — a bar is used only when its close time is in the past
  * a failed endpoint prints UNAVAILABLE; it never falls back to stale data, zero or null
  * every estimated figure is labelled [MODELED] or [PROXY]
"""
from __future__ import annotations

import argparse
import bisect
import enum
import json
import math
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

SPOT = "https://data-api.binance.vision/api/v3"
FAPI = "https://fapi.binance.com"
OKX = "https://www.okx.com"
DUMP = "https://data.binance.vision/data/futures/um/daily/klines"   # official archive, not geo-blocked
FARSIDE = "https://farside.co.uk/bitcoin-etf-flow-all-data/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
BAND_WIDTH_ATR = 0.35      # tactical band width, in 1D ATR
MACRO_LOOKBACK = 500       # 1D bars for macro S/R
MACRO_PIVOT_K = 2          # fractal width for macro pivots
MACRO_CLUSTER_PCT = 0.01   # 1% clustering width
LIQ_WEIGHTS = ((10, 0.08), (25, 0.06), (50, 0.04), (100, 0.02))   # [MODELED] 20% of OI in total
LIQ_OVERLAY_PCT = 0.005     # a liq cluster "overlaps" a level when within 0.5% (matches v1.7)
MANUAL_MAX_AGE_H = 2
LIQ_OVERLAY_MIN_LEV = 25   # low-leverage tiers are not explosive enough to tag
RISK_PCT = 0.0075          # binding arithmetic handed to the execution prompt
MAX_POS_PCT_OF_USDT = 0.30


# ─────────────────────────────── transport ────────────────────────────────
def get_json(url: str, timeout: int = 12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def get_text(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def get_bytes(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def dump_bars(csv_lines: list[str]) -> list[dict]:
    """Parse a Binance kline CSV. The daily files ship a header row; older ones do not."""
    rows = [ln.split(",") for ln in csv_lines if ln.strip()]
    if rows and not rows[0][0].strip().lstrip("-").isdigit():
        rows = rows[1:]                       # drop the header
    if not rows or len(rows[0]) < 10:
        raise ValueError(f"unexpected column count {len(rows[0]) if rows else 0}")
    return [{"t": int(float(r[0])), "v": float(r[5]), "taker_buy": float(r[9])}
            for r in rows]


def okx_perp_cvd(fetch=None, now_ms: float | None = None):
    """Live perp CVD from OKX's Rubik taker-volume endpoint — measured, not modelled.

    OKX klines carry no taker split, but rubik/stat/taker-volume-contract does:
    data rows are [ts, sellVolume, buyVolume] in coin units, newest first.
    """
    fetch = fetch or get_json
    url = (f"{OKX}/api/v5/rubik/stat/taker-volume-contract"
           f"?instId=BTC-USDT-SWAP&period=1H&unit=0&limit=100")
    rows = (fetch(url) or {}).get("data") or []
    if len(rows) < 24:
        raise ValueError(f"only {len(rows)} taker-volume rows")
    now_ms = datetime.now(timezone.utc).timestamp() * 1000 if now_ms is None else now_ms
    bars = closed_bars(rows, now_ms)
    if len(bars) < 24:
        raise ValueError(f"only {len(bars)} closed taker-volume rows")
    tail = bars[-24:]
    if any(tail[i]["t"] - tail[i - 1]["t"] != 3_600_000 for i in range(1, 24)):
        raise ValueError("gap in 24h taker-volume rows")
    return {"cvd_1h": cvd(bars, 1), "cvd_4h": cvd(bars, 4), "cvd_24h": cvd(bars, 24),
            "bars": len(bars)}


def dump_day_problem(bars: list[dict], day) -> str | None:
    """None if these bars are exactly one closed UTC day; otherwise the reason they are not.

    A row count is not a day: twenty-four copies of one hour, or twenty-four hours pulled from
    two different dates, both pass a `>= 24` test and would be published as a complete day.
    """
    if len(bars) != 24:
        return f"{len(bars)} rows, expected 24"
    stamps = [b.get("t") for b in bars]
    if any(t is None for t in stamps):
        return "rows carry no timestamp"
    if len(set(stamps)) != 24:
        return f"{len(set(stamps))} unique hours, expected 24"
    days = {datetime.fromtimestamp(t / 1000, timezone.utc).date() for t in stamps}
    if days != {day}:
        return f"rows span {sorted(str(x) for x in days)}, expected {day}"
    hours = sorted(datetime.fromtimestamp(t / 1000, timezone.utc).hour for t in stamps)
    if hours != list(range(24)):
        return f"hours {hours} are not 00–23"
    return None


def perp_cvd_from_dump(days_back: int = 3, fetch=None):
    """Perp CVD from Binance's public daily archive (no API, no geo-block, T+1 lag).

    The 1h files carry 12 columns; column 9 is takerBuyBaseVolume — the field the live
    futures API refuses a US runner. Returns a complete closed day, never "now".
    """
    import io
    import zipfile
    from datetime import timedelta

    fetch = fetch or get_bytes
    today = datetime.now(timezone.utc).date()
    last_err = "no published daily dump in the last %d days" % days_back
    for back in range(1, days_back + 1):
        d = today - timedelta(days=back)
        url = f"{DUMP}/BTCUSDT/1h/BTCUSDT-1h-{d.isoformat()}.zip"
        try:
            blob = fetch(url)
            z = zipfile.ZipFile(io.BytesIO(blob))
            bars = dump_bars(z.read(z.namelist()[0]).decode().strip().splitlines())
            if len(bars) < 24:
                last_err = f"dump {d} only {len(bars)} bars"
                continue
            why = dump_day_problem(bars, d)
            if why:
                last_err = f"dump {d} unusable: {why}"
                continue
            bars.sort(key=lambda b: b["t"])
            return ({"date": d.isoformat(), "bars": len(bars),
                     "cvd_4h": cvd(bars, 4), "cvd_24h": cvd(bars, 24)}, None)
        except urllib.error.HTTPError as e:
            if e.code == 404:                      # not published yet -> try the day before
                last_err = f"dump {d} 404 (not published)"
                continue
            return None, f"dump {d} HTTP {e.code}"
        except Exception as e:                     # noqa: BLE001
            last_err = f"dump {d} {type(e).__name__}"
            continue
    return None, last_err


def safe(fn, label: str):
    """Run a fetch, return (value, None) or (None, reason). Never raises."""
    try:
        return fn(), None
    except urllib.error.HTTPError as e:
        return None, f"{label} HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, f"{label} unreachable ({e.reason})"
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return None, f"{label} parse error ({type(e).__name__})"
    except Exception as e:                                    # noqa: BLE001
        return None, f"{label} failed ({type(e).__name__})"


# ─────────────────────────────── indicators ───────────────────────────────
def closed(bars: list[dict], now_ms: float) -> list[dict]:
    return [b for b in bars if b["close_time"] < now_ms]


def to_bars(raw: list) -> list[dict]:
    out = []
    for r in raw:
        out.append({
            "open_time": int(r[0]), "o": float(r[1]), "h": float(r[2]), "l": float(r[3]),
            "c": float(r[4]), "v": float(r[5]), "close_time": int(r[6]),
            "taker_buy": float(r[9]),
        })
    return out


def atr_wilder(bars: list[dict], n: int = 14):
    if len(bars) < n + 2:
        return None
    trs = []
    for i in range(1, len(bars)):
        pc, b = bars[i - 1]["c"], bars[i]
        trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def sma(closes: list[float], n: int):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def pivots(bars: list[dict], k: int) -> tuple[list[float], list[float]]:
    """k=2 means a swing high is higher than the 2 bars either side."""
    highs, lows = [], []
    for i in range(k, len(bars) - k):
        window = bars[i - k:i + k + 1]
        if bars[i]["h"] >= max(b["h"] for b in window) and bars[i]["h"] > bars[i - 1]["h"]:
            highs.append(bars[i]["h"])
        if bars[i]["l"] <= min(b["l"] for b in window) and bars[i]["l"] < bars[i - 1]["l"]:
            lows.append(bars[i]["l"])
    return highs, lows


def cluster(levels: list[float], pct: float) -> list[dict]:
    """Greedy 1%-width clustering; returns [{low, high, center, touches}] sorted asc."""
    out: list[dict] = []
    for px in sorted(levels):
        if out and abs(px - out[-1]["center"]) / out[-1]["center"] <= pct:
            c = out[-1]
            c["center"] = (c["center"] * c["touches"] + px) / (c["touches"] + 1)
            c["touches"] += 1
            c["low"], c["high"] = min(c["low"], px), max(c["high"], px)
        else:
            out.append({"low": px, "high": px, "center": px, "touches": 1})
    return out


def volume_profile(bars: list[dict], bins: int = 60, value_area: float = 0.70) -> dict | None:
    if len(bars) < 5:
        return None
    lo = min(b["l"] for b in bars)
    hi = max(b["h"] for b in bars)
    if hi <= lo:
        return None
    step = (hi - lo) / bins
    hist = [0.0] * bins
    for b in bars:
        idx = min(bins - 1, max(0, int(((b["h"] + b["l"] + b["c"]) / 3 - lo) / step)))
        hist[idx] += b["v"]
    total = sum(hist)
    if total <= 0:
        return None
    poc_i = max(range(bins), key=lambda i: hist[i])
    covered, span = hist[poc_i], [poc_i, poc_i]
    while covered < total * value_area and (span[0] > 0 or span[1] < bins - 1):
        left = hist[span[0] - 1] if span[0] > 0 else -1
        right = hist[span[1] + 1] if span[1] < bins - 1 else -1
        if right >= left:
            span[1] += 1
            covered += right
        else:
            span[0] -= 1
            covered += left
    centers = [lo + (i + 0.5) * step for i in range(bins)]
    return {"poc": lo + (poc_i + 0.5) * step,
            "val": lo + span[0] * step,
            "vah": lo + (span[1] + 1) * step,
            "hist": hist, "centers": centers, "peak": max(hist), "bars": len(bars)}


def hvn_nearest(vp: dict | None, price: float, share: float = 0.60):
    """Nearest high-volume node: a bin holding >= share of the POC's volume."""
    if not vp or not vp.get("peak"):
        return None
    hits = [c for c, h in zip(vp["centers"], vp["hist"]) if h >= share * vp["peak"]]
    above = [c for c in hits if c > price]
    below = [c for c in hits if c < price]
    return {"above": min(above) if above else None,
            "below": max(below) if below else None}


def tactical_bands(h4: list[dict], atr1d: float, price: float) -> tuple[list[dict], dict | None]:
    highs, lows = pivots(h4, 2)
    width = BAND_WIDTH_ATR * atr1d
    raw = [{"low": p - width / 2, "high": p + width / 2, "touches": 1} for p in highs + lows]
    raw.sort(key=lambda b: b["low"])
    merged: list[dict] = []
    for b in raw:
        if merged:
            m = merged[-1]
            grown = max(m["high"], b["high"]) - min(m["low"], b["low"])
            if b["low"] <= m["high"] and grown <= 1.6 * width:
                m["high"] = max(m["high"], b["high"])
                m["low"] = min(m["low"], b["low"])
                m["touches"] += 1
                m["center"] = (m["low"] + m["high"]) / 2
                continue
        b["center"] = (b["low"] + b["high"]) / 2
        merged.append(b)
    inside = next((b for b in merged if b["low"] <= price <= b["high"]), None)
    return [b for b in merged if b is not inside], inside


def confluence(band: dict, vp: dict | None) -> tuple[int, list[str]]:
    """Max 10: +4 POC, +3 VAH or VAL, +3 round-1000 level. vp must be the 7D profile."""
    score, why = 0, []
    if vp:
        if band["low"] <= vp["poc"] <= band["high"]:
            score += 4
            why.append("POC")
        if band["low"] <= vp["vah"] <= band["high"] or band["low"] <= vp["val"] <= band["high"]:
            score += 3
            why.append("VAH/VAL")
    round_levels = [math.ceil(band["low"] / 1000) * 1000, math.floor(band["high"] / 1000) * 1000]
    if any(band["low"] <= r <= band["high"] for r in set(round_levels)):
        score += 3
        why.append("round-1k")
    return score, why


def cvd_complete(d) -> bool:
    """True only when all three windows carry a finite number.

    A failed series arrives as {'1h': None, '4h': None, '24h': None} — truthy as a dict, which is how
    a spot-feed failure slipped past a `bool()` test and still printed plans.
    """
    if not isinstance(d, dict) or not d:
        return False
    return all(isinstance(d.get(k), (int, float)) and math.isfinite(d[k])
               for k in ("1h", "4h", "24h"))


def closed_bars(rows: list[list], now_ms: float, max_age_ms: float = 7_200_000) -> list[dict]:
    """Taker-volume rows older than one hour, oldest first.

    OKX publishes the CURRENT, still-forming hour as its newest row. Summing it would make cvd_1h a
    partial hour and cvd_24h twenty-three closed hours plus a fragment, while the packet footer
    promises closed bars only. A bar counts as closed when its open time plus one hour has passed.
    """
    out = []
    for r in reversed(rows):                                  # OKX sends newest first
        t = int(r[0])
        if t + 3_600_000 <= now_ms:
            out.append({"t": t, "v": float(r[1]) + float(r[2]), "taker_buy": float(r[2])})
    if len({b["t"] for b in out}) != len(out):
        raise ValueError("duplicate taker-volume timestamps")
    if out and now_ms - (out[-1]["t"] + 3_600_000) > max_age_ms:
        # a 30-day-old archive is not a live reading: refuse rather than average history
        stale_min = int((now_ms - (out[-1]["t"] + 3_600_000)) / 60_000)
        raise ValueError(f"stale taker-volume archive (last closed bar {stale_min} min old)")
    return out


def cvd(bars: list[dict], n_bars: int) -> float | None:
    if len(bars) < n_bars:
        return None
    return sum(2 * b["taker_buy"] - b["v"] for b in bars[-n_bars:])


def sweep(h1: list[dict], support: dict | None, resistance: dict | None,
          macro_sup: list | None = None, macro_res: list | None = None) -> dict:
    """Last 6 closed 1H bars, newest first: macro levels are checked before tactical bands."""
    def stamp(b):
        return datetime.fromtimestamp(b["open_time"] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%MZ")

    recent = h1[-6:]
    for idx in range(len(recent) - 1, -1, -1):
        b = recent[idx]
        later = recent[idx + 1:]
        for c in (macro_sup or []):                       # macro support swept and reclaimed
            if c["touches"] < 2:
                continue
            lv = c["center"]
            if b["o"] >= lv and b["l"] < lv and b["c"] > lv and all(x["c"] > lv for x in later):
                return {"flag": "MACRO BULLISH SWEEP", "level": lv, "at": stamp(b),
                        "touches": c["touches"]}
        for c in (macro_res or []):
            if c["touches"] < 2:
                continue
            lv = c["center"]
            if b["o"] <= lv and b["h"] > lv and b["c"] < lv and all(x["c"] < lv for x in later):
                return {"flag": "MACRO BEARISH SWEEP", "level": lv, "at": stamp(b),
                        "touches": c["touches"]}
        if (support and b["o"] >= support["low"] and b["l"] < support["low"]
                and b["c"] > support["low"] and all(x["c"] > support["low"] for x in later)):
            return {"flag": "BULLISH SWEEP", "level": support["low"], "at": stamp(b)}
        if (resistance and b["o"] <= resistance["high"] and b["h"] > resistance["high"]
                and b["c"] < resistance["high"] and all(x["c"] < resistance["high"] for x in later)):
            return {"flag": "BEARISH SWEEP", "level": resistance["high"], "at": stamp(b)}
    return {"flag": "NONE", "level": None, "at": None}


def parse_manual(s: str | None) -> tuple[dict, bool]:
    """A manual reading unlocks execution ONLY if it carries a number and a UTC time.

    "perp_cvd_24h=+2663,at=04:05Z" unlocks. "perp_cvd=falling" does not — an adjective is not
    evidence, and a gate that any sentence can open is not a gate.
    """
    parts: dict[str, str] = {}
    for chunk in (s or "").split(","):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            parts[k.strip()] = v.strip()
    ok = False
    try:
        if not math.isfinite(float(parts.get("perp_cvd_24h", ""))):
            raise ValueError("non-finite manual reading")
        at_raw = (parts.get("at") or "").strip().upper()
        if at_raw.endswith("Z"):
            when = None
            time_only = False
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%H:%M"):
                try:
                    when = datetime.strptime(at_raw[:-1].strip(), fmt)
                    time_only = fmt == "%H:%M"      # the year is a strptime artefact, not evidence
                    break
                except ValueError:
                    continue
            if when is not None:
                now = datetime.now(timezone.utc)
                if time_only:                              # time-only: anchor to today
                    when = when.replace(year=now.year, month=now.month, day=now.day)
                when = when.replace(tzinfo=timezone.utc)
                if time_only and when > now + timedelta(minutes=5):
                    when -= timedelta(days=1)              # 23:50Z typed just after midnight
                elif time_only and when > now:
                    when = now                             # a few seconds of clock skew is not a future
                age = now - when
                # a future stamp is never evidence: the gate needs an age between 0 and the ceiling
                ok = timedelta(0) <= age <= timedelta(hours=MANUAL_MAX_AGE_H)
    except (TypeError, ValueError):
        ok = False
    return parts, ok


def percentile(values: list[float], x: float) -> float | None:
    if not values:
        return None
    return 100.0 * sum(1 for v in values if v <= x) / len(values)


# ───────────────────────────────── ETF ────────────────────────────────────
MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def _num(cell: str):
    """Farside numbers: 1,234.5 · (95.1) means -95.1 · '-' means not settled."""
    import re
    c = cell.replace("$", "").replace(",", "").replace("\u2212", "-").strip()
    neg = c.startswith("(") and c.endswith(")")
    c = c.strip("()").strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", c):
        return None
    v = float(c)
    return -v if neg else v


def etf_flows():
    """Farside table. A day counts only when its Total cell parses as a number.

    The newest row is often still filling even when its Total is present, so both the
    newest numeric day and the last completed day are reported.
    """
    import re
    html = get_text(FARSIDE)
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    cells_of = lambda tr: [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()
                           for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]

    total_idx = None
    for tr in trs:
        cs = cells_of(tr)
        if "Total" in cs:
            total_idx = cs.index("Total")
            break
    if total_idx is None:
        raise ValueError("Total column not found")

    rows: list[tuple[tuple[int, int, int], float]] = []
    for tr in trs:
        cs = cells_of(tr)
        if len(cs) <= total_idx:
            continue
        m = re.fullmatch(r"(\d{1,2}) (\w{3}) (\d{4})", cs[0])
        if not m or m.group(2) not in MONTHS:
            continue
        val = _num(cs[total_idx])
        if val is None:
            continue                                    # dash / blank = not settled yet
        rows.append(((int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))), val))
    if not rows:
        raise ValueError("no settled rows parsed")
    rows.sort()
    today = datetime.now(timezone.utc).date()
    y, mo, d = rows[-1][0]
    newest_is_today = (y, mo, d) == (today.year, today.month, today.day)
    prev = rows[-1] if not newest_is_today else (rows[-2] if len(rows) > 1 else rows[-1])
    last5 = rows[-5:]
    return {
        "latest_date": f"{d} {[k for k, v in MONTHS.items() if v == mo][0]} {y}",
        "one_day_m": rows[-1][1],
        "one_day_settling": newest_is_today,
        "prev_date": f"{prev[0][2]} {[k for k, v in MONTHS.items() if v == prev[0][1]][0]} {prev[0][0]}",
        "prev_day_m": prev[1],
        "five_day_m": sum(v for _, v in last5),
        "five_day_days": len(last5),
        "twenty_day_m": sum(v for _, v in rows[-20:]) if len(rows) >= 20 else None,
    }


# ───────────────────────── Project F dual sleeves ─────────────────────────
def _f_ewm(vals: list[float | None], alpha: float, min_periods: int) -> list[float | None]:
    """Causal exponential moving average matching pandas ewm(alpha=alpha, adjust=False)."""
    out: list[float | None] = []
    cur: float | None = None
    cnt = 0
    for v in vals:
        if v is None or not math.isfinite(v):
            out.append(None)
        else:
            cnt += 1
            cur = v if cur is None else (alpha * v + (1.0 - alpha) * cur)
            out.append(cur if cnt >= min_periods else None)
    return out


def _f_ema(vals: list[float | None], length: int) -> list[float | None]:
    return _f_ewm(vals, 2.0 / (length + 1.0), length)


def _f_rma(vals: list[float | None], length: int) -> list[float | None]:
    return _f_ewm(vals, 1.0 / float(length), length)


def _f_atr(bars: list[dict], length: int) -> list[float | None]:
    if not bars:
        return []
    trs: list[float | None] = [bars[0]["h"] - bars[0]["l"]]
    for i in range(1, len(bars)):
        pc, b = bars[i - 1]["c"], bars[i]
        trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
    return _f_rma(trs, length)


def _f_sma(vals: list[float | None], window: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(vals)):
        if i + 1 < window:
            out.append(None)
        else:
            w = vals[i - window + 1 : i + 1]
            out.append(None if any(x is None for x in w) else sum(w) / window)  # type: ignore[arg-type]
    return out


def _f_std_pop(vals: list[float | None], window: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(vals)):
        if i + 1 < window:
            out.append(None)
        else:
            w = vals[i - window + 1 : i + 1]
            if any(x is None for x in w):
                out.append(None)
            else:
                m = sum(w) / window  # type: ignore[arg-type]
                out.append(math.sqrt(sum((x - m) ** 2 for x in w) / window))  # type: ignore[operator]
    return out


def _f_linreg_end(vals: list[float | None], window: int = 20) -> list[float | None]:
    """Causal rolling OLS linear-regression endpoint matching ta.linreg(vals, window, 0)."""
    xm = (window - 1) / 2.0
    sxx = sum((i - xm) ** 2 for i in range(window))
    weights = [(1.0 / window) + ((i - xm) * ((window - 1) - xm) / sxx) for i in range(window)]
    out: list[float | None] = []
    for i in range(len(vals)):
        if i + 1 < window:
            out.append(None)
        else:
            w = vals[i - window + 1 : i + 1]
            out.append(None if any(x is None for x in w)
                       else sum(v * wt for v, wt in zip(w, weights)))  # type: ignore[operator]
    return out


def _f_bar_stamps(bar: dict, step_hours: int) -> dict:
    open_dt = datetime.fromtimestamp(bar["open_time"] / 1000.0, tz=timezone.utc)
    close_dt = open_dt + timedelta(hours=step_hours)
    return {
        "open_utc": open_dt.strftime("%Y-%m-%d %H:%MZ"),
        "close_utc": close_dt.strftime("%Y-%m-%d %H:%MZ"),
        "close_sgt": (close_dt + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M SGT"),
    }


def _f_simulate_spot(
    bars: list[dict],
    signals: list[int],
    sls: list[float | None],
    initial_capital_usdt: float = 10000.0,
    initial_btc_alloc: float = 0.5,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.0005,
    step_hours: int = 4,
) -> dict:
    """Deterministic 4-state spot simulator matching ctc_backtest_lab/engine.py."""
    open_0 = bars[0]["o"]
    btc_start_usdt = initial_capital_usdt * initial_btc_alloc
    cash_usdt = initial_capital_usdt - btc_start_usdt
    btc_qty = btc_start_usdt / open_0 if (btc_start_usdt > 0.0 and open_0 > 0.0) else 0.0
    active_sl: float | None = None
    prev_signal = 0
    prev_sl: float | None = None
    last_transition: dict | None = None
    exposed_weight = 0.0

    def _stamp_ms(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%MZ")

    for i, b in enumerate(bars):
        o_i, l_i = b["o"], b["l"]
        if i > 0:
            if prev_signal == 1 and cash_usdt > 0.0 and o_i > 0.0:
                fill_price = o_i * (1.0 + slippage_rate)
                net_spent = cash_usdt * (1.0 - fee_rate)
                btc_qty += net_spent / fill_price
                cash_usdt = 0.0
                active_sl = prev_sl
                last_transition = {
                    "type": "BUY",
                    "bar_idx": i,
                    "time_utc": _stamp_ms(b["open_time"]),
                    "event_ms": b["open_time"],
                    "price": round(o_i, 2),
                }
            elif prev_signal == -1 and btc_qty > 0.0:
                fill_price = o_i * (1.0 - slippage_rate)
                cash_usdt += (btc_qty * fill_price) * (1.0 - fee_rate)
                btc_qty = 0.0
                active_sl = None
                last_transition = {
                    "type": "SELL",
                    "bar_idx": i,
                    "time_utc": _stamp_ms(b["open_time"]),
                    "event_ms": b["open_time"],
                    "price": round(o_i, 2),
                }
            elif btc_qty > 0.0 and prev_signal == 0 and prev_sl is not None:
                active_sl = prev_sl

        if btc_qty > 0.0 and active_sl is not None and l_i <= active_sl:
            raw_exit = o_i if o_i <= active_sl else active_sl
            fill_price = raw_exit * (1.0 - slippage_rate)
            cash_usdt += (btc_qty * fill_price) * (1.0 - fee_rate)
            btc_qty = 0.0
            active_sl = None
            close_ev = b["open_time"] + step_hours * 3_600_000
            last_transition = {
                "type": "STOP_LOSS",
                "bar_idx": i,
                "time_utc": _stamp_ms(close_ev),
                "event_ms": close_ev,
                "price": round(raw_exit, 2),
            }

        if btc_qty > 0.0 and cash_usdt == 0.0:
            exposed_weight += 1.0
        elif btc_qty > 0.0 and cash_usdt > 0.0:
            exposed_weight += initial_btc_alloc

        prev_signal = signals[i]
        cand_sl = sls[i]
        prev_sl = (float(cand_sl)
                   if cand_sl is not None and math.isfinite(cand_sl) and cand_sl > 0.0
                   else None)

    holding_btc = btc_qty > 0.0
    holding_usdt = cash_usdt > 0.0
    last_signal = signals[-1]
    raw_entry_sl = prev_sl

    if last_signal == 1:
        if holding_usdt:
            action, active_stop_loss = "BUY BTC", raw_entry_sl
        else:
            action, active_stop_loss = "HOLD BTC", active_sl
    elif last_signal == -1:
        action = "SELL BTC" if holding_btc else "HOLD USDT"
        active_stop_loss = None
    else:
        action = "HOLD BTC" if holding_btc else "HOLD USDT"
        active_stop_loss = active_sl if holding_btc else None

    prior_pos = ("BTC" if holding_btc and not holding_usdt
                 else ("50/50" if holding_btc and holding_usdt else "USDT"))

    end_ms = bars[-1]["open_time"] + step_hours * 3_600_000
    if last_transition is not None:
        t_idx = last_transition["bar_idx"]
        trans_out = {
            "type": last_transition["type"],
            "time_utc": last_transition["time_utc"],
            "price": last_transition["price"],
            "bars_ago": (len(bars) - 1) - t_idx,
            "days_ago": round(max(0.0, (end_ms - last_transition["event_ms"]) / 86_400_000), 1),
        }
    else:
        trans_out = None
    stopped_on_last_bar = bool(
        last_transition is not None
        and last_transition["type"] == "STOP_LOSS"
        and last_transition["bar_idx"] == len(bars) - 1
    )
    flipped_on_last_bar = bool(action in ("BUY BTC", "SELL BTC") or stopped_on_last_bar)
    exposure_pct = round(exposed_weight / len(bars) * 100.0, 1) if bars else 0.0

    return {
        "raw_signal": last_signal,
        "prior_position": prior_pos,
        "action": action,
        "active_stop_loss": active_stop_loss,
        "flipped_on_last_bar": flipped_on_last_bar,
        "last_transition": trans_out,
        "exposure_pct": exposure_pct,
        "if_flat": "BUY BTC at next bar open" if last_signal == 1 else "HOLD USDT (wait for BUY +1)",
        "if_long": "SELL BTC at next bar open" if last_signal == -1 else "HOLD BTC (keep entry stop-loss active)",
    }


def _sleeve1_signals(
    h4: list[dict],
    d1: list[dict] | None = None,
    vwap_window: int = 90,
    slope_window: int = 12,
    macro_ema_days: int = 120,
    atr_len: int = 14,
    buffer_atr: float = 0.50,
    atr_sl_mult: float = 3.0,
) -> tuple[list[int], list[float | None], dict]:
    """Core signal vectors for Project F Sleeve #1 (tier1_5_vwap_shield)."""
    tp = [(b["h"] + b["l"] + b["c"]) / 3.0 for b in h4]
    pv = [t * b["v"] for t, b in zip(tp, h4)]
    vols = [b["v"] for b in h4]

    rvwap: list[float | None] = []
    for i in range(len(h4)):
        if i + 1 < vwap_window:
            rvwap.append(None)
        else:
            vs = sum(vols[i - vwap_window + 1 : i + 1])
            rvwap.append(sum(pv[i - vwap_window + 1 : i + 1]) / vs if vs > 0.0 else None)

    slope: list[float | None] = [
        None if (i < slope_window or rvwap[i] is None or rvwap[i - slope_window] is None)
        else (rvwap[i] - rvwap[i - slope_window])  # type: ignore[operator]
        for i in range(len(h4))
    ]
    atr4 = _f_atr(h4, atr_len)

    # Resample 4H closes by UTC day for causal 1-day-shifted 120D EMA (prepending d1 only when h4 < 121 days)
    day_closes: dict[int, float] = {}
    for b in h4:
        day_closes[b["open_time"] // 86_400_000] = b["c"]
    if len(day_closes) < macro_ema_days + 1 and d1:
        first_h4_day = min(day_closes.keys()) if day_closes else None
        for b in d1:
            dk = b["open_time"] // 86_400_000
            if first_h4_day is None or dk < first_h4_day:
                day_closes[dk] = b["c"]
    days_sorted = sorted(day_closes.keys())
    d_ema = _f_ema([day_closes[dk] for dk in days_sorted], macro_ema_days)
    day_to_shifted_ema: dict[int, float | None] = {}
    prev_e: float | None = None
    for dk, e_val in zip(days_sorted, d_ema):
        day_to_shifted_ema[dk] = prev_e
        prev_e = e_val

    macro_ema: list[float | None] = []
    for b in h4:
        dk = b["open_time"] // 86_400_000
        pos = bisect.bisect_right(days_sorted, dk) - 1
        macro_ema.append(day_to_shifted_ema.get(days_sorted[pos]) if pos >= 0 else None)

    sigs: list[int] = []
    sls: list[float | None] = []
    for i, b in enumerate(h4):
        c, rv, slp, at, me = b["c"], rvwap[i], slope[i], atr4[i], macro_ema[i]
        if None in (rv, slp, at, me):
            sigs.append(0)
            sls.append(None)
        else:
            ex = (c < me) or (c < rv - buffer_atr * at)        # type: ignore[operator]
            en = (c > me) and (c > rv + buffer_atr * at) and (slp > 0.0)  # type: ignore[operator]
            s = 1 if en else (-1 if ex else 0)
            sigs.append(s)
            sls.append(c - atr_sl_mult * at if s == 1 else None)  # type: ignore[operator]

    last = {
        "close": h4[-1]["c"] if h4 else None,
        "rolling_vwap": rvwap[-1] if rvwap else None,
        "vwap_slope": slope[-1] if slope else None,
        "atr_14": atr4[-1] if atr4 else None,
        "macro_120d_ema": macro_ema[-1] if macro_ema else None,
    }
    return sigs, sls, last


def sleeve1_vwap_shield(h4: list[dict], d1: list[dict] | None = None) -> dict:
    """Compute Project F Sleeve #1 (tier1_5_vwap_shield, 4H, 80% weight)."""
    if len(h4) < 102:
        return {"status": "UNAVAILABLE", "reason": f"insufficient closed 4H bars ({len(h4)} < 102)"}
    sigs, sls, last = _sleeve1_signals(h4, d1=d1)
    c, rv, slp, at, me = (last["close"], last["rolling_vwap"], last["vwap_slope"],
                          last["atr_14"], last["macro_120d_ema"])
    if None in (c, rv, slp, at, me):
        return {"status": "UNAVAILABLE", "reason": "insufficient warmup history for 120D EMA / VWAP(90)"}

    upper = rv + 0.50 * at       # type: ignore[operator]
    lower = rv - 0.50 * at       # type: ignore[operator]
    ref_sl = c - 3.0 * at        # type: ignore[operator]
    sim = _f_simulate_spot(h4, sigs, sls, step_hours=4)
    sim["reference_3x_atr_sl"] = ref_sl
    trig_px = max(me, upper)
    readiness = {
        "gates_passed": int(c > me) + int(c > upper) + int(slp > 0.0),  # type: ignore[operator]
        "gates_total": 3,
        "shield_dist_pct": round((c / me - 1.0) * 100.0, 2) if me > 0.0 else None,  # type: ignore[operator]
        "upper_buf_dist_pct": round((c / upper - 1.0) * 100.0, 2) if upper > 0.0 else None,  # type: ignore[operator]
        "lower_buf_dist_pct": round((c / lower - 1.0) * 100.0, 2) if lower > 0.0 else None,  # type: ignore[operator]
        "price_hurdle": round(trig_px, 2),
        "rally_to_hurdle_pct": round(max(0.0, (trig_px / c - 1.0) * 100.0), 2) if c > 0.0 else None,  # type: ignore[operator]
    }
    return {
        "status": "LIVE",
        "strategy": "tier1_5_vwap_shield",
        "timeframe": "4h",
        "weight_pct": 80,
        "bars_analyzed": len(h4),
        "last_closed_bar": _f_bar_stamps(h4[-1], 4),
        "indicators": {
            "close_price": c,
            "macro_120d_ema": me,
            "rolling_15d_vwap": rv,
            "vwap_slope_12bar": slp,
            "atr_14": at,
            "upper_buffer_price": upper,
            "lower_buffer_price": lower,
        },
        "conditions": {
            "above_macro_shield": bool(c > me),                  # type: ignore[operator]
            "above_upper_buffer": bool(c > upper),
            "below_lower_buffer": bool(c < lower),
            "vwap_slope_positive": bool(slp > 0.0),              # type: ignore[operator]
            "exit_triggered": bool((c < me) or (c < lower)),     # type: ignore[operator]
        },
        "readiness": readiness,
        "state": sim,
    }


def _sleeve2_signals(
    d1: list[dict],
    bb_len: int = 20,
    bb_mult: float = 2.0,
    kc_len: int = 20,
    kc_mult: float = 1.5,
    squeeze_bars: int = 3,
    mom_len: int = 20,
    exit_sma_len: int = 21,
    atr_sl_len: int = 14,
    atr_sl_mult: float = 2.0,
) -> tuple[list[int], list[float | None], dict]:
    """Core signal vectors for Project F Sleeve #2 (tier14_ttm_squeeze_1d)."""
    c1 = [b["c"] for b in d1]
    h1 = [b["h"] for b in d1]
    l1 = [b["l"] for b in d1]

    bb_mid = _f_sma(c1, bb_len)
    bb_std = _f_std_pop(c1, bb_len)
    bb_up = [None if (m is None or s is None) else m + bb_mult * s for m, s in zip(bb_mid, bb_std)]
    bb_lo = [None if (m is None or s is None) else m - bb_mult * s for m, s in zip(bb_mid, bb_std)]

    kc_mid = _f_ema(c1, kc_len)
    atr20 = _f_atr(d1, kc_len)
    kc_up = [None if (m is None or a is None) else m + kc_mult * a for m, a in zip(kc_mid, atr20)]
    kc_lo = [None if (m is None or a is None) else m - kc_mult * a for m, a in zip(kc_mid, atr20)]

    sq_on = [None if None in (bu, bl, ku, kl) else (1.0 if (bu < ku and bl > kl) else 0.0)
             for bu, bl, ku, kl in zip(bb_up, bb_lo, kc_up, kc_lo)]
    don_mid: list[float | None] = [
        None if i + 1 < mom_len else 0.5 * (max(h1[i - mom_len + 1 : i + 1]) + min(l1[i - mom_len + 1 : i + 1]))
        for i in range(len(d1))
    ]
    delta = [None if (dm is None or bm is None) else (c - 0.5 * (dm + bm))
             for c, dm, bm in zip(c1, don_mid, bb_mid)]
    mom = _f_linreg_end(delta, mom_len)
    sma21 = _f_sma(c1, exit_sma_len)
    atr14 = _f_atr(d1, atr_sl_len)

    sigs: list[int] = []
    sls: list[float | None] = []
    last_flags = {"squeeze_on": False, "prior_sq": 0, "had_sq3": False, "release": False, "exit": False}
    for i in range(len(d1)):
        prev_sq = [sq_on[i - j] for j in range(1, squeeze_bars + 1)] if i >= squeeze_bars else [None]
        prev_m = mom[i - 1] if i >= 1 else None
        if (sq_on[i] is None or any(x is None for x in prev_sq) or mom[i] is None
                or prev_m is None or sma21[i] is None or atr14[i] is None or kc_mid[i] is None):
            sigs.append(0)
            sls.append(None)
        else:
            prior_cnt = int(sum(prev_sq))                          # type: ignore[arg-type]
            had_sq = prior_cnt == squeeze_bars
            rel = (sq_on[i] == 0.0) and had_sq
            ex = (c1[i] < sma21[i]) or (mom[i] < 0.0)              # type: ignore[operator]
            bu = ((not ex) and rel and (mom[i] > 0.0)              # type: ignore[operator]
                  and (mom[i] > prev_m) and (c1[i] > kc_mid[i]))   # type: ignore[operator]
            s = 1 if bu else (-1 if ex else 0)
            sigs.append(s)
            sls.append(c1[i] - atr_sl_mult * atr14[i] if s == 1 else None)  # type: ignore[operator]
            if i == len(d1) - 1:
                last_flags = {
                    "squeeze_on": sq_on[i] == 1.0,
                    "prior_sq": prior_cnt,
                    "had_sq3": had_sq,
                    "release": rel,
                    "exit": ex,
                }

    sq_streak = 0
    for val in reversed(sq_on):
        if val == 1.0:
            sq_streak += 1
        else:
            break

    last = {
        "close": c1[-1] if c1 else None,
        "bb_upper": bb_up[-1] if bb_up else None,
        "bb_mid": bb_mid[-1] if bb_mid else None,
        "bb_lower": bb_lo[-1] if bb_lo else None,
        "kc_upper": kc_up[-1] if kc_up else None,
        "kc_mid": kc_mid[-1] if kc_mid else None,
        "kc_lower": kc_lo[-1] if kc_lo else None,
        "mom": mom[-1] if mom else None,
        "prev_mom": mom[-2] if len(mom) >= 2 else None,
        "sma_21": sma21[-1] if sma21 else None,
        "atr_14": atr14[-1] if atr14 else None,
        "squeeze_streak": sq_streak,
        **last_flags,
    }
    return sigs, sls, last


def sleeve2_ttm_squeeze(d1: list[dict]) -> dict:
    """Compute Project F Sleeve #2 (tier14_ttm_squeeze_1d, 1D, 20% weight, no 120D shield)."""
    if len(d1) < 40:
        return {"status": "UNAVAILABLE", "reason": f"insufficient closed 1D bars ({len(d1)} < 40)"}
    sigs, sls, last = _sleeve2_signals(d1)
    req = ("close", "bb_upper", "bb_mid", "bb_lower", "kc_upper", "kc_mid",
           "kc_lower", "mom", "prev_mom", "sma_21", "atr_14")
    if any(last[k] is None for k in req):
        return {"status": "UNAVAILABLE", "reason": "insufficient warmup history for TTM Squeeze indicators"}

    c = last["close"]
    at = last["atr_14"]
    ref_sl = c - 2.0 * at
    sim = _f_simulate_spot(d1, sigs, sls, step_hours=24)
    sim["reference_2x_atr_sl"] = ref_sl
    bb_w = last["bb_upper"] - last["bb_lower"]
    kc_w = last["kc_upper"] - last["kc_lower"]
    comp_ratio = round(bb_w / kc_w, 3) if kc_w > 0 else None
    conds_ok = (
        int(bool(last["release"]))
        + int(bool(last["mom"] > 0.0))
        + int(bool(last["mom"] > last["prev_mom"]))
        + int(bool(c > last["kc_mid"]))
        + int(not bool(last["exit"]))
    )
    readiness = {
        "gates_passed": conds_ok,
        "gates_total": 5,
        "compression_ratio": comp_ratio,
        "squeeze_streak_days": int(last["squeeze_streak"]),
        "kc_mid_dist_pct": round((c / last["kc_mid"] - 1.0) * 100.0, 2) if last["kc_mid"] > 0 else None,
        "sma21_dist_pct": round((c / last["sma_21"] - 1.0) * 100.0, 2) if last["sma_21"] > 0 else None,
    }
    return {
        "status": "LIVE",
        "strategy": "tier14_ttm_squeeze_1d",
        "timeframe": "1d",
        "weight_pct": 20,
        "bars_analyzed": len(d1),
        "last_closed_bar": _f_bar_stamps(d1[-1], 24),
        "indicators": {
            "close_price": c,
            "bb_upper": last["bb_upper"],
            "bb_mid": last["bb_mid"],
            "bb_lower": last["bb_lower"],
            "kc_upper": last["kc_upper"],
            "kc_mid": last["kc_mid"],
            "kc_lower": last["kc_lower"],
            "prior_3d_squeeze_bars": last["prior_sq"],
            "mom": last["mom"],
            "prev_mom": last["prev_mom"],
            "sma_21": last["sma_21"],
            "atr_14": at,
        },
        "conditions": {
            "squeeze_on_now": bool(last["squeeze_on"]),
            "had_squeeze_3d": bool(last["had_sq3"]),
            "squeeze_release": bool(last["release"]),
            "mom_positive": bool(last["mom"] > 0.0),
            "mom_rising": bool(last["mom"] > last["prev_mom"]),
            "above_kc_mid": bool(c > last["kc_mid"]),
            "exit_triggered": bool(last["exit"]),
        },
        "readiness": readiness,
        "state": sim,
    }


# ─────────────────────────────── collection ───────────────────────────────
def collect() -> tuple[dict, list[str]]:
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    jobs = {
        "d1": f"{SPOT}/klines?symbol=BTCUSDT&interval=1d&limit={MACRO_LOOKBACK}",
        "h4": f"{SPOT}/klines?symbol=BTCUSDT&interval=4h&limit=1000",
        "h1": f"{SPOT}/klines?symbol=BTCUSDT&interval=1h&limit=200",
        "fd1": f"{FAPI}/fapi/v1/klines?symbol=BTCUSDT&interval=1d&limit=200",
        "fh1": f"{FAPI}/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=200",
        "px": f"{SPOT}/ticker/price?symbol=BTCUSDT",
        "funding": f"{FAPI}/fapi/v1/premiumIndex?symbol=BTCUSDT",
        "funding_hist": f"{FAPI}/fapi/v1/fundingRate?symbol=BTCUSDT&limit=270",
        "oi": f"{FAPI}/fapi/v1/openInterest?symbol=BTCUSDT",
        "oi_hist": f"{FAPI}/futures/data/openInterestHist?symbol=BTCUSDT&period=4h&limit=7",
        "lsr": f"{FAPI}/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=4h&limit=1",
    }
    raw: dict = {}
    problems: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {k: pool.submit(safe, (lambda u=u: get_json(u)), k) for k, u in jobs.items()}
        futures["etf"] = pool.submit(safe, etf_flows, "etf")
        futures["okx_px"] = pool.submit(
            safe, (lambda u=f"{OKX}/api/v5/market/ticker?instId=BTC-USDT": get_json(u)), "okx_px"
        )
        for k, f in futures.items():
            val, err = f.result()
            raw[k] = val
            if err and k != "okx_px":
                problems.append(err)

    # Measured from a US GitHub runner: fapi.binance.com = HTTP 451, api.bybit.com = HTTP 403,
    # api.deribit.com = unreachable; www.okx.com / bitget / gate.io / kraken / coingecko = 200.
    # OKX is the one venue that serves both a CI runner and a home machine, so it is the fallback.
    fb: dict = {}
    deriv_src = "BINANCE"
    if any(raw.get(k) is None for k in ("funding", "oi", "oi_hist", "lsr")):
        jobs2 = {
            "fund": f"{OKX}/api/v5/public/funding-rate?instId=BTC-USDT-SWAP",
            "oi": f"{OKX}/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP",
            "oi_hist": f"{OKX}/api/v5/rubik/stat/contracts/open-interest-volume?ccy=BTC&period=1H",
            "lsr": f"{OKX}/api/v5/rubik/stat/contracts/long-short-account-ratio-contract?instId=BTC-USDT-SWAP&period=4H",
            "fund_hist": f"{OKX}/api/v5/public/funding-rate-history?instId=BTC-USDT-SWAP&limit=100",
        }
        with ThreadPoolExecutor(max_workers=5) as pool:
            futs = {k: pool.submit(safe, (lambda u=u: get_json(u)), f"okx:{k}") for k, u in jobs2.items()}
            for k, f in futs.items():
                val, err = f.result()
                fb[k] = val
                if err:
                    problems.append(err)
        if any(fb.get(k) for k in ("fund", "oi", "oi_hist", "lsr")):
            deriv_src = "OKX"

    def okx_data(key):
        return ((fb.get(key) or {}).get("data")) or []

    data = {"now": datetime.now(timezone.utc), "problems": problems, "deriv_src": deriv_src}
    for key in ("d1", "h4", "h1", "fd1", "fh1"):
        data[key] = closed(to_bars(raw[key]), now_ms) if raw.get(key) else []
    if raw.get("px"):
        data["price"] = float(raw["px"]["price"])
        data["price_src"] = "TICKER"
    elif data["d1"]:
        data["price"] = data["d1"][-1]["c"]
        data["price_src"] = "CLOSE-1D"          # last closed daily candle, not a live quote
    else:
        data["price"] = None
        data["price_src"] = None

    bin_px = float(raw["px"]["price"]) if raw.get("px") and raw["px"].get("price") not in (None, "") else None
    okx_px_row = ((raw.get("okx_px") or {}).get("data") or [{}])[0]
    try:
        okx_px = float(okx_px_row["last"]) if okx_px_row.get("last") not in (None, "") else None
    except (TypeError, ValueError):
        okx_px = None
    if (bin_px is not None and okx_px is not None and math.isfinite(bin_px) and math.isfinite(okx_px)
            and bin_px > 0 and okx_px > 0):
        spread_pct = abs(bin_px - okx_px) / bin_px * 100.0
        spot_ok = spread_pct <= 0.50
        data["spot_check"] = {
            "bin_price": bin_px,
            "okx_price": okx_px,
            "spread_pct": round(spread_pct, 4),
            "ok": spot_ok,
        }
        if not spot_ok:
            problems.append(
                f"spot price divergence BIN (${bin_px:,.2f}) vs OKX (${okx_px:,.2f}) "
                f"= {spread_pct:.3f}% (> 0.50%)"
            )
    else:
        data["spot_check"] = {
            "bin_price": bin_px,
            "okx_price": okx_px,
            "spread_pct": None,
            "ok": None,
        }
    okx_fund = (okx_data("fund") or [{}])[0]
    if raw.get("funding"):
        data["funding"] = float(raw["funding"]["lastFundingRate"]) * 100
        data["mark"] = float(raw["funding"]["markPrice"])
        data["fund_src"] = "BINANCE"
    elif okx_fund.get("fundingRate") not in (None, ""):
        data["funding"] = float(okx_fund["fundingRate"]) * 100
        data["mark"] = None
        data["fund_src"] = "OKX"
    else:
        data["funding"] = data["mark"] = None
        data["fund_src"] = None

    okx_oi = (okx_data("oi") or [{}])[0]
    if raw.get("oi"):
        data["oi_btc"] = float(raw["oi"]["openInterest"])
        data["oi_src"] = "BINANCE"
    elif okx_oi.get("oiCcy") not in (None, ""):
        data["oi_btc"] = float(okx_oi["oiCcy"])
        data["oi_src"] = "OKX"
    else:
        data["oi_btc"] = None
        data["oi_src"] = None

    oi_series: list[float] = []
    oi_stamps: list[int] = []
    if raw.get("oi_hist"):
        oi_series = [float(r["sumOpenInterest"]) for r in raw["oi_hist"]]
        oi_stamps = [int(r["timestamp"]) for r in raw["oi_hist"]]
        data["oi_hist_src"] = "BINANCE"
    elif okx_data("oi_hist"):
        rows = list(reversed(okx_data("oi_hist")[:25]))   # hourly, newest first -> oldest first
        oi_series = [float(r[1]) for r in rows]
        oi_stamps = [int(r[0]) for r in rows]
        data["oi_hist_src"] = "OKX"
    else:
        data["oi_hist_src"] = None

    data["oi_4h_chg"] = oi_change(oi_series, oi_stamps, 4)
    data["oi_24h_chg"] = oi_change(oi_series, oi_stamps, 24)
    if raw.get("funding_hist"):
        fh = [float(r["fundingRate"]) * 100 for r in raw["funding_hist"]]
        data["fund_hist_src"] = "BINANCE"
    else:
        fh = [float(r["fundingRate"]) * 100 for r in okx_data("fund_hist")
              if r.get("fundingRate") not in (None, "")]
        data["fund_hist_src"] = "OKX" if fh else None
    data["funding_pct90"] = (percentile(fh, data["funding"])
                             if (fh and data["funding"] is not None
                                 and data["fund_src"] == data["fund_hist_src"])
                             else None)
    lsr = raw.get("lsr") or []
    if lsr:
        data["ls_ratio"] = float(lsr[0]["longShortRatio"])
        data["lsr_src"] = "BINANCE"
    else:
        blsr = okx_data("lsr")
        data["ls_ratio"] = float(blsr[0][1]) if blsr else None
        data["lsr_src"] = "OKX" if blsr else None
    data["etf"] = raw.get("etf")
    data["perp_dump"] = None
    data["perp_src"] = "BINANCE" if data["fh1"] else None
    if not data["fh1"]:
        try:
            data["okx_perp"] = okx_perp_cvd(now_ms=now_ms)
            data["perp_src"] = "OKX-RUBIK"
            problems.append("perp CVD is OKX's measured taker volume (BTC-USDT swap), "
                            "not Binance — Binance Futures refused this host")
        except Exception as e:                          # noqa: BLE001
            data["okx_perp"] = None
            problems.append(f"okx taker-volume unavailable ({type(e).__name__})")
    if not data["fh1"] and not data.get("okx_perp"):
        dump, derr = perp_cvd_from_dump()
        data["perp_dump"] = dump
        if dump:
            data["perp_src"] = "ARCHIVE"
        if dump:
            problems.append(f"perp CVD is from Binance's daily archive for {dump['date']} "
                            f"(T+1, {dump['bars']} bars) — not live")
        else:
            problems.append(f"perp klines unavailable ({derr}); no taker split from OKX/Bybit")
    return data, problems


# ──────────────────────────────── compute ─────────────────────────────────
def oi_change(series: list[float], stamps: list[int], hours: int) -> float | None:
    """Percent change over `hours`, matched by timestamp rather than by position.

    A positional offset assumes the samples are contiguous: one missing hour silently shifts
    the window and reports a different interval as "4H". If no sample sits within 30 minutes of
    the requested horizon, the change is unavailable rather than approximate.
    """
    if not series or not stamps or len(series) != len(stamps) or len(stamps) < 2:
        return None
    target = stamps[-1] - hours * 3600_000
    idx = min(range(len(stamps) - 1), key=lambda i: abs(stamps[i] - target))
    if abs(stamps[idx] - target) > 1800_000:
        return None
    a, b = series[idx], series[-1]
    return (b / a - 1) * 100 if a else None


def compute_salam_diagnostics(out: dict) -> tuple[dict, dict | None]:
    """Compute Macro Weather regime summary and Rail B sizing diagnostic (no rule changes)."""
    price = out.get("price")
    sma200 = out.get("sma200")
    etf = out.get("etf") or {}
    fp = out.get("funding_pct90")

    above_sma200 = (bool(price > sma200)
                    if (price is not None and sma200 is not None
                        and math.isfinite(price) and math.isfinite(sma200) and sma200 > 0)
                    else None)
    sma200_dist_pct = (round((price / sma200 - 1.0) * 100.0, 2)
                       if above_sma200 is not None else None)
    etf_5d = etf.get("five_day_m")
    etf_1d = etf.get("one_day_m")
    crowded_long = bool(fp is not None and math.isfinite(fp) and fp >= 90.0)

    if above_sma200 is None and etf_5d is None:
        regime = "UNAVAILABLE"
    elif above_sma200 is False and (etf_5d is None or etf_5d <= 0.0):
        regime = "HEADWIND"
    elif above_sma200 is True and (etf_5d is not None and etf_5d > 0.0) and not crowded_long:
        regime = "TAILWIND"
    else:
        regime = "MIXED"

    notes = [
        f"Price {sma200_dist_pct:+.1f}% vs 200D SMA" if sma200_dist_pct is not None else "200D SMA UNAVAILABLE",
        f"5D ETF {etf_5d:+,.1f}M" if etf_5d is not None else "ETF flow UNAVAILABLE",
        (f"Funding pctile {fp:.0f}" + (" (crowded)" if crowded_long else ""))
        if (fp is not None and math.isfinite(fp)) else "Funding pct UNAVAILABLE",
    ]
    macro_weather = {
        "regime": regime,
        "above_sma200": above_sma200,
        "sma200_dist_pct": sma200_dist_pct,
        "etf_5d_m": etf_5d,
        "etf_1d_m": etf_1d,
        "funding_pct90": fp,
        "crowded_long": crowded_long,
        "summary": " · ".join(notes),
    }

    sup_b = out.get("sup_band")
    m_sup = out.get("macro_sup") or []
    if sup_b and sup_b.get("high"):
        ref_px = float(sup_b["high"])
        ref_src = "Tactical Floor High"
    elif m_sup and m_sup[0].get("center"):
        ref_px = float(m_sup[0]["center"])
        ref_src = "Nearest Macro Support"
    elif price is not None and math.isfinite(price) and price > 0:
        ref_px = float(price)
        ref_src = "Current Spot"
    else:
        ref_px = None
        ref_src = "UNAVAILABLE"

    atr1h = out.get("atr1h")
    if (atr1h is not None and math.isfinite(atr1h) and atr1h > 0
            and ref_px is not None and math.isfinite(ref_px) and ref_px > 0):
        stop_dist = 1.5 * float(atr1h)
        stop_px = ref_px - stop_dist
        stop_pct = (stop_dist / ref_px) * 100.0
        implied_port_pct = (RISK_PCT / (stop_dist / ref_px)) * 100.0
        cap_50_50 = MAX_POS_PCT_OF_USDT * 50.0
        cap_100_usdt = MAX_POS_PCT_OF_USDT * 100.0
        rail_b_sizing = {
            "ref_entry": round(ref_px, 2),
            "ref_source": ref_src,
            "atr1h": round(float(atr1h), 2),
            "stop_dist": round(stop_dist, 2),
            "stop_price": round(stop_px, 2),
            "stop_pct": round(stop_pct, 3),
            "implied_port_pct": round(implied_port_pct, 2),
            "cap_port_pct_50_50": cap_50_50,
            "cap_port_pct_100_usdt": cap_100_usdt,
            "required_usdt_share_pct": round(implied_port_pct / MAX_POS_PCT_OF_USDT, 1),
            "vetoed_at_50_50": bool(implied_port_pct > cap_50_50),
            "vetoed_at_100_usdt": bool(implied_port_pct > cap_100_usdt),
        }
    else:
        rail_b_sizing = None

    return macro_weather, rail_b_sizing


def analyse(d: dict) -> dict:
    out: dict = {"problems": d["problems"], "deriv_src": d.get("deriv_src", "BINANCE"),
                 "price_src": d.get("price_src"), "spot_check": d.get("spot_check")}
    for _sk in ("oi_src", "oi_hist_src", "fund_src", "fund_hist_src", "lsr_src"):
        if _sk in d:
            out[_sk] = d[_sk]
    price = d["price"]
    out["price"] = price
    if not d["d1"] or price is None:
        out["fatal"] = "no closed 1D bars or no price"
        return out

    closes = [b["c"] for b in d["d1"]]
    atr1d = atr_wilder(d["d1"], 14)
    out["atr1d"] = atr1d
    out["sma200"] = sma(closes, 200)
    out["vp30"] = volume_profile(d["d1"][-30:])
    out["vp7"] = volume_profile(d["d1"][-7:])
    out["vp4h"] = volume_profile(d["h4"][-30:]) if len(d["h4"]) >= 30 else None
    out["hvn7"] = hvn_nearest(out["vp7"], price)
    out["atr1h"] = atr_wilder(d["h1"], 14) if len(d["h1"]) > 16 else None
    h1_closes = [b["c"] for b in d["h1"]]
    h1_stamps = [b["close_time"] for b in d["h1"]]
    out["px_chg"] = {
        "1h": oi_change(h1_closes, h1_stamps, 1),
        "4h": oi_change(h1_closes, h1_stamps, 4),
        "24h": oi_change(h1_closes, h1_stamps, 24),
    }

    highs, lows = pivots(d["d1"], MACRO_PIVOT_K)
    clusters = cluster(highs + lows, MACRO_CLUSTER_PCT)
    # nearest 3 by distance — touch count is kept as context but no longer ranks the list
    noise = price * 0.0025          # a cluster this close is "at price", not a level to trade
    out["macro_res"] = sorted([c for c in clusters if c["center"] > price + noise],
                              key=lambda c: c["center"])[:3]
    out["macro_sup"] = sorted([c for c in clusters if c["center"] < price - noise],
                              key=lambda c: -c["center"])[:3]

    bands, inside = tactical_bands(d["h4"], atr1d, price) if (d["h4"] and atr1d) else ([], None)
    if inside:                      # never offer a "next" band that overlaps the one we are in
        below = [b for b in bands if b["high"] < inside["low"]]
        above = [b for b in bands if b["low"] > inside["high"]]
    else:
        below = [b for b in bands if b["high"] < price]
        above = [b for b in bands if b["low"] > price]
    sup_band = max(below, key=lambda b: b["high"]) if below else None
    res_band = min(above, key=lambda b: b["low"]) if above else None
    for b in (sup_band, res_band):
        if b:
            b["score"], b["why"] = confluence(b, out["vp7"])
    out["sup_band"], out["res_band"], out["inside_band"] = sup_band, res_band, inside
    out["bands"] = bands

    all_sup = [c for c in clusters if c["center"] <= price]
    all_res = [c for c in clusters if c["center"] >= price]
    out["sweep"] = sweep(d["h1"], sup_band, res_band, all_sup, all_res) \
        if d["h1"] else {"flag": "UNAVAILABLE"}

    out["cvd_spot"] = {"1h": cvd(d["h1"], 1), "4h": cvd(d["h1"], 4), "24h": cvd(d["h1"], 24)}
    out["cvd_perp"] = {"1h": cvd(d["fh1"], 1), "4h": cvd(d["fh1"], 4), "24h": cvd(d["fh1"], 24)}
    if d.get("okx_perp"):
        op = d["okx_perp"]
        out["cvd_perp"] = {"1h": op["cvd_1h"], "4h": op["cvd_4h"], "24h": op["cvd_24h"]}
    out["perp_src"] = d.get("perp_src")
    out["spot_cvd_ok"] = cvd_complete(out["cvd_spot"])
    out["perp_cvd_ok"] = cvd_complete(out["cvd_perp"])
    out["perp_dump"] = d.get("perp_dump")
    out["oi_btc"], out["oi_4h_chg"], out["oi_24h_chg"] = d["oi_btc"], d["oi_4h_chg"], d["oi_24h_chg"]
    out["funding"], out["funding_pct90"], out["ls_ratio"] = d["funding"], d["funding_pct90"], d["ls_ratio"]
    out["etf"] = d["etf"]

    if d.get("liq_upper") is not None:
        pass

    if d["oi_btc"] and price:
        oi_usd_m = d["oi_btc"] * price / 1e6
        out["oi_usd_m"] = oi_usd_m
        out["liq_upper"] = [{"lev": lev, "price": price * (1 + 1 / lev), "usd_m": oi_usd_m * w}
                            for lev, w in LIQ_WEIGHTS]
        out["liq_lower"] = [{"lev": lev, "price": price * (1 - 1 / lev), "usd_m": oi_usd_m * w}
                            for lev, w in LIQ_WEIGHTS]
    # ── layer 4: liquidation overlay on every level we publish ──
    def overlay_span(lo_px: float, hi_px: float):
        """One tag at most: the single nearest cluster >= 25x within LIQ_OVERLAY_PCT of [lo_px, hi_px]."""
        if not lo_px or not hi_px:
            return None
        cands = [("Shorts", c) for c in out.get("liq_upper") or []] + \
                [("Longs", c) for c in out.get("liq_lower") or []]
        hits = []
        for s, c in cands:
            if c["lev"] < LIQ_OVERLAY_MIN_LEV:
                continue
            px = c["price"]
            dist = 0.0 if lo_px <= px <= hi_px else (
                (lo_px - px) / lo_px if px < lo_px else (px - hi_px) / hi_px)
            if dist <= LIQ_OVERLAY_PCT:
                hits.append((s, c))
        if not hits:
            return None
        mid = (lo_px + hi_px) / 2
        side, c = min(hits, key=lambda sc: abs(sc[1]["price"] - mid))
        return (side, c["usd_m"], c["lev"])

    for b in (out.get("sup_band"), out.get("res_band"), out.get("inside_band")):
        if b:
            b["liq"] = overlay_span(b["low"], b["high"])
    for c in out.get("macro_res", []) + out.get("macro_sup", []):
        c["liq"] = overlay_span(c["center"], c["center"]) if c["touches"] >= 2 else None
    out["sleeve1"] = sleeve1_vwap_shield(d.get("h4") or [], d.get("d1") or [])
    out["sleeve2"] = sleeve2_ttm_squeeze(d.get("d1") or [])
    out["macro_weather"], out["rail_b_sizing"] = compute_salam_diagnostics(out)
    return out


# ───────────────────────────────── render ─────────────────────────────────
def f(x, dp=2, dash="UNAVAILABLE"):
    return dash if x is None else f"{x:,.{dp}f}"


def band_txt(b: dict | None) -> str:
    if not b:
        return "UNAVAILABLE"
    return f"{b['low']:,.0f}-{b['high']:,.0f}"


def fmt_dual(ts: str | None) -> str:
    """Render a 'YYYY-MM-DD HH:MMZ' stamp as UTC and SGT (UTC+8)."""
    if not ts:
        return ""
    try:
        d = datetime.strptime(str(ts), "%Y-%m-%d %H:%MZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return str(ts)
    return f"{ts} / {(d + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')} SGT"


def tag(a: dict) -> str:
    return "[OKX]" if a.get("deriv_src") == "OKX" else "[BIN]"


def liq_txt(x) -> str:
    if not x:
        return ""
    side, usd, lev = x
    return f" [+${usd:,.0f}M {lev}x {side}]"


def vp_txt(vp: dict | None, style: str) -> str:
    if not vp:
        return "UNAVAILABLE"
    if style == "full":
        return f"VAH {vp['vah']:,.0f} · POC {vp['poc']:,.0f} · VAL {vp['val']:,.0f}"
    return f"VAH: {vp['vah']:,.0f} | POC: {vp['poc']:,.0f} | VAL: {vp['val']:,.0f}"


def render(a: dict) -> str:
    stamp = a.get("generated_at_utc")
    if stamp:
        _n = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    else:
        _n = datetime.now(timezone.utc)
    now = (_n.strftime("%Y-%m-%d %H:%M:%S UTC")
           + " / " + (_n + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S SGT (UTC+8)"))
    if a.get("fatal"):
        return f"# SALAM PRO MAX DATA HUB v1.7\n**Timestamp:** {now} | **FATAL:** {a['fatal']}\n"
    p = a["price"]
    sb, rb = a.get("sup_band"), a.get("res_band")
    inside = a.get("inside_band")
    sw = a.get("sweep") or {}
    etf = a.get("etf") or {}
    up, lo = a.get("liq_upper") or [], a.get("liq_lower") or []
    hvn = a.get("hvn7") or {}
    V = tag(a)
    def src_tag(key: str) -> str:
        s = a.get(key)
        return "[OKX]" if s == "OKX" else ("[BIN]" if s == "BINANCE" else V)
    PV = {"OKX-RUBIK": "[OKX-RUBIK]", "BINANCE": "[BIN]",
          "ARCHIVE": "[BIN-DUMP]"}.get(a.get("perp_src"), "[UNAVAILABLE]")

    L: list[str] = []
    L.append("# SALAM PRO MAX DATA HUB v1.7")
    PT = "[BIN-CLOSE 1D]" if a.get("price_src") == "CLOSE-1D" else "[BIN]"
    sc = a.get("spot_check") or {}
    sc_txt = ""
    if sc.get("ok") is not None and sc.get("okx_price") is not None and sc.get("spread_pct") is not None:
        sc_tag = "OK" if sc["ok"] else "WARN >0.50%"
        sc_txt = f" | **OKX Spot:** ${sc['okx_price']:,.2f} (spread {sc['spread_pct']:.3f}% [{sc_tag}])"
    L.append(f"**Timestamp:** {now} | **Spot Price:** ${p:,.2f} {PT}{sc_txt}")
    dump = a.get("perp_dump")
    # A whitelist, not a default: a missing or unrecognised state is NONE. The old default was
    # "FULL", so a packet with no state at all printed plans under a healthy banner.
    raw_state = a.get("exec_state")
    state = raw_state if (type(raw_state) is str and raw_state in ("FULL", "MANUAL", "PARTIAL", "NONE")) else "NONE"
    # FULL needs BOTH halves complete. MANUAL needs a complete spot series plus the typed reading —
    # requiring cvd_perp there broke hand-entered packets, where perp klines have failed by definition.
    if state == "FULL" and not (cvd_complete(a.get("cvd_spot")) and cvd_complete(a.get("cvd_perp"))):
        state = "NONE"
    elif state == "MANUAL":
        man_val = (a.get("manual") or {}).get("perp_cvd_24h")
        try:
            typed_ok = man_val is not None and math.isfinite(float(man_val))
        except (TypeError, ValueError):
            typed_ok = False
        if not (cvd_complete(a.get("cvd_spot")) and typed_ok):
            state = "NONE"
    state_tag = f" (state: {state}"
    if raw_state not in (None, "FULL", "MANUAL", "PARTIAL", "NONE"):
        state_tag += f", packet said {raw_state!r}"
    state_tag += ")"
    if state == "FULL" and a.get("perp_src") == "OKX-RUBIK":
        L.append(f"> ✅ **LIVE DATA — plans allowed**{state_tag}. Spot comes from Binance; "
                 "futures flow is "
                 "OKX's measured taker volume, not Binance's (this host is blocked). "
                 "Live, not modelled: Binance Futures refuses this host, but OKX's rubik endpoint "
                 "publishes real taker buy/sell per hour.")
    elif state == "FULL":
        L.append(f"> ✅ **LIVE DATA — plans allowed**{state_tag}. Spot and futures flow are both "
                 f"measured now, not estimated.")
    elif state == "MANUAL":
        L.append(f"> ✅ **HAND-ENTERED DATA — plans allowed**{state_tag}. Futures flow was typed in at "
                 f"{a.get('manual_at')}. "
                 f"Human-supplied from a screenshot, not machine-verified. "
                 f"Perp CVD 24H = {a['manual'].get('perp_cvd_24h')} BTC.")
    elif state == "PARTIAL" and dump:
        L.append(f"> ⚠️ **PARTIAL ORDER FLOW**{state_tag} — perp CVD is Binance's archive for {dump['date']} "
                 f"(T+1), not live. Live perp klines are blocked on this host. Intraday perp "
                 f"reads are one day old; spot and levels are live.")
    else:
        why = ("CI host: Binance Futures refused this runner (HTTP 451)"
               if a.get("deriv_src") == "OKX" else
               "this run produced no usable perp klines")
        L.append(f"> ⚠️ **PERP CVD UNAVAILABLE**{state_tag} — {why}. This packet is a levels map, "
                 f"not an execution packet. Run locally before acting.")
    L.append("")

    # ── 1. Deep S/R matrix ──
    L.append("## 1. THE ANCHOR (Deep S/R Matrix)")
    px_tag = f" {PT}" if a.get("price_src") == "CLOSE-1D" else ""
    L.append(f"*   **Current Price:** ${p:,.0f}{px_tag} (1D SMA200 {f(a.get('sma200'), 0)})")
    L.append("*   **Tactical Bands:**")
    if rb:
        why_r = f", {'+'.join(rb['why']) or 'pivot-only'}" if "why" in rb else ""
        L.append(f"    *   Upper: ${rb['low']:,.0f} - ${rb['high']:,.0f} "
                 f"(Conf: {rb.get('score', 0)}/10{why_r}){liq_txt(rb.get('liq'))}")
    else:
        L.append("    *   Upper: UNAVAILABLE")
    if sb:
        why_s = f", {'+'.join(sb['why']) or 'pivot-only'}" if "why" in sb else ""
        L.append(f"    *   Lower: ${sb['low']:,.0f} - ${sb['high']:,.0f} "
                 f"(Conf: {sb.get('score', 0)}/10{why_s}){liq_txt(sb.get('liq'))}")
    else:
        L.append("    *   Lower: UNAVAILABLE")
    if inside:
        L.append(f"    *   Price is inside ${inside['low']:,.0f} - ${inside['high']:,.0f}"
                 f"{liq_txt(inside.get('liq'))}")

    L.append("*   **Macro S/R (Nearest 3):**")
    mr, ms = a.get("macro_res") or [], a.get("macro_sup") or []
    L.append("    *   Resistance: " + (", ".join(
        f"${c['center']:,.0f} ({c['touches']}x){liq_txt(c.get('liq'))}" for c in mr) or "UNAVAILABLE"))
    L.append("    *   Support: " + (", ".join(
        f"${c['center']:,.0f} ({c['touches']}x){liq_txt(c.get('liq'))}" for c in ms) or "UNAVAILABLE"))

    hvn_bit = "UNAVAILABLE"
    if hvn.get("above") or hvn.get("below"):
        parts = []
        if hvn.get("below"):
            parts.append(f"${hvn['below']:,.0f} below")
        if hvn.get("above"):
            parts.append(f"${hvn['above']:,.0f} above")
        hvn_bit = " · ".join(parts)
    L.append(f"*   **Volume Nodes (7D):** {vp_txt(a.get('vp7'), 'inline')} | Nearest HVN: {hvn_bit}")
    L.append(f"*   **Volume Profile (MTF):** 30D {vp_txt(a.get('vp30'), 'full')}")
    L.append(f"    *   4H (last 30 bars): {vp_txt(a.get('vp4h'), 'full')}")
    L.append("")

    # ── 2. Liq magnets, weighted tiers ──
    L.append("## 2. THE FUEL (Liquidation Magnets) [ESTIMATED]")
    if up and lo:
        wdesc = " / ".join(f"{lev}x {w:.0%}" for lev, w in LIQ_WEIGHTS)
        total_w = sum(w for _, w in LIQ_WEIGHTS)
        L.append(f"*   **OI weighting (assumed):** {wdesc} of open interest "
                 f"(= {total_w:.0%} in total; the rest assumed cross-margin or lower leverage)")
        L.append("*   **Upper Shorts:** " + " / ".join(
            f"{c['lev']}x ${c['price']:,.0f} (${c['usd_m']:,.1f}M)" for c in up))
        L.append("*   **Lower Longs:** " + " / ".join(
            f"{c['lev']}x ${c['price']:,.0f} (${c['usd_m']:,.1f}M)" for c in lo))
        L.append(f"    *Levels are exact leverage arithmetic. The $ per tier is OI "
                 f"${a['oi_usd_m']:,.1f}M x the weights above, i.e. an assumed "
                 f"{sum(w for _, w in LIQ_WEIGHTS):.0%} of open interest across these four tiers "
                 f"(the rest assumed cross-margin or lower leverage) — not observed liquidation data. A tier is tagged as overlapping a level when it sits within "
             f"{LIQ_OVERLAY_PCT:.1%} of it.*")
    else:
        L.append("*   **Upper Shorts:** UNAVAILABLE (no open interest)")
        L.append("*   **Lower Longs:** UNAVAILABLE (no open interest)")
    if a.get("ls_ratio") is not None:
        L.append(f"*   **Long/Short account ratio (4H):** {a['ls_ratio']:.2f} {src_tag('lsr_src')}")
    else:
        L.append("*   **Long/Short account ratio (4H):** UNAVAILABLE")
    L.append("")

    # ── 3. Order flow ──
    L.append("## 3. THE TRUTH (Order Flow)")
    pxc = a.get("px_chg") or {}
    pct_f = lambda v: "UNAVAILABLE" if v is None else f"{v:+.2f}%"
    L.append(f"*   **Price Change (closed 1H [BIN]):** "
             f"1H: {pct_f(pxc.get('1h'))} | 4H: {pct_f(pxc.get('4h'))} | 24H: {pct_f(pxc.get('24h'))}")
    cs, cp = a.get("cvd_spot") or {}, a.get("cvd_perp") or {}
    L.append(f"*   **CVD (Spot [BIN] / Perp {PV}):** "
             f"1H: {f(cs.get('1h'), 1)} / {f(cp.get('1h'), 1)}"
             f" | 4H: {f(cs.get('4h'), 1)} / {f(cp.get('4h'), 1)}"
             f" | 24H: {f(cs.get('24h'), 1)} / {f(cp.get('24h'), 1)}")
    L.append(f"*   **Open Interest:** {f(a.get('oi_btc'), 0)} BTC {src_tag('oi_src')}"
             f" | 4H Change: {f(a.get('oi_4h_chg'), 2)}% | 24H Change: {f(a.get('oi_24h_chg'), 2)}%")
    if a.get("deriv_src") == "OKX":
        L.append("*   **Derivatives source:** [OKX fallback] Binance Futures answers HTTP 451 and "
                 "Bybit HTTP 403 from this host. OI, funding and L/S are OKX's BTC-USDT swap; the "
                 "funding percentile uses its last 100 readings (~33 days), not 90.")
    fh_src = a.get("fund_hist_src") or a.get("deriv_src")
    L.append(f"*   **Funding:** {f(a.get('funding'), 4)}% per 8H {src_tag('fund_src')}"
             + (f" | percentile (100 pts): {f(a.get('funding_pct90'), 0)}"
                if fh_src == "OKX"
                else f" | 90-day percentile: {f(a.get('funding_pct90'), 0)}"))
    if dump and not a.get("perp_cvd_ok"):
        L.append(f"*   **Perp CVD [BIN-DUMP {dump['date']}]:** 4H {f(dump.get('cvd_4h'), 1)}"
                 f" | 24H {f(dump.get('cvd_24h'), 1)} (complete closed day, {dump['bars']} bars"
                 f" — one day old, not live)")
    if a.get("manual"):
        man = a["manual"]
        L.append(f"*   **Manual override [MANUAL {man.get('at', '?')}]:** "
                 + ", ".join(f"{k}={v}" for k, v in man.items() if k != "at")
                 + ("" if a.get("manual_ok") else
                    "  (no numeric perp CVD + timestamp — does NOT unlock execution)"))
    _atr = a.get("atr1h")
    _stop = f"1.5 x this = {f(_atr * 1.5, 0)})" if _atr is not None else "UNAVAILABLE)"
    L.append(f"*   **ATR 1H:** {f(_atr, 0)} (Rail B stop distance = {_stop}")
    L.append("")

    # ── 4. Trigger ──
    L.append("## 4. THE TRIGGER")
    if sw.get("flag") == "NONE":
        L.append("*   **Sweep Status:** NONE (no closed 1H bar beyond a level that closed back inside)")
    elif (sw.get("flag") in ("BULLISH SWEEP", "BEARISH SWEEP",
                             "MACRO BULLISH SWEEP", "MACRO BEARISH SWEEP")
          and isinstance(sw.get("level"), (int, float))
          and math.isfinite(sw["level"]) and sw["level"] > 0):
        extra = f" ({sw['touches']}x level)" if sw.get("touches") else ""
        L.append(f"*   **Sweep Status:** {sw['flag']} at "
                 f"${sw['level']:,.0f}{extra} · {fmt_dual(sw.get('at'))}")
    else:
        L.append("*   **Sweep Status:** UNAVAILABLE (no 1H bars)")
    L.append("")

    # ── 5. Macro veto ──
    L.append("## 5. MACRO VETO INPUTS")
    if etf:
        _settled = "settling" if etf.get("one_day_settling") else "settled"
        L.append(f"*   **ETF Net Flow:** 1D: ${etf['one_day_m']:,.1f}M "
                 f"({etf['latest_date']}, {_settled})"
                 f" | 5D: ${etf['five_day_m']:,.1f}M")
    else:
        L.append("*   **ETF Net Flow:** UNAVAILABLE (Farside unreachable or no settled row)")
    okx_src = fh_src == "OKX"
    L.append(f"*   **Funding percentile:** {f(a.get('funding_pct90'), 0)}"
             + (" of the last 100 readings (~33 days, OKX)" if okx_src else " of 90 days")
             + ("  <- tail" if ((a.get("funding_pct90") or 0) >= 95 and not okx_src) else ""))
    mw = a.get("macro_weather")
    if mw:
        L.append(f"*   **Macro Weather (Veto Summary, never a trigger):** {mw['regime']} ({mw['summary']})")
    L.append("")

    sig_fmt = lambda s: f"{s:+d}" if s else "0"
    _pct_s = lambda v: "UNAVAILABLE" if v is None else f"{v:+.2f}%"
    def _trans_txt(st: dict) -> str:
        lt = st.get("last_transition")
        if not lt:
            return "None in window"
        return (f"{lt['type']} @ ${lt['price']:,.2f} on {lt['time_utc']} "
                f"({lt['days_ago']:.1f}d / {lt['bars_ago']} bars ago)")

    s1 = a.get("sleeve1") or {}
    L.append("## 6. PROJECT F — SLEEVE #1 (4H Rolling VWAP Shield · 80% Weight)")
    if s1.get("status") == "LIVE":
        ind1, cond1, st1 = s1["indicators"], s1["conditions"], s1["state"]
        bar1 = s1["last_closed_bar"]
        sl1_line = (f" | Active Entry Stop: ${st1['active_stop_loss']:,.2f}"
                    if st1.get("active_stop_loss") is not None else "")
        L.append("*   **Strategy:** `tier1_5_vwap_shield` (Spot BTC/USDT, zero leverage, 4H closed bars)")
        L.append(f"*   **Last Closed 4H Bar:** {bar1['open_utc']} -> {bar1['close_utc']} / "
                 f"{bar1['close_sgt']} ({s1['bars_analyzed']} closed 4H bars)")
        L.append(f"*   **Indicators:** Close ${ind1['close_price']:,.2f} | "
                 f"120D EMA Shield ${ind1['macro_120d_ema']:,.2f} | "
                 f"15D Rolling VWAP (90b) ${ind1['rolling_15d_vwap']:,.2f} "
                 f"(12b Slope {ind1['vwap_slope_12bar']:+,.2f}) | "
                 f"Band +/-0.50 ATR: ${ind1['lower_buffer_price']:,.2f} to "
                 f"${ind1['upper_buffer_price']:,.2f} | 4H ATR(14) ${ind1['atr_14']:,.2f}")
        L.append(f"*   **Checks:** [{'PASS' if cond1['above_macro_shield'] else 'FAIL'}] Close > 120D EMA | "
                 f"[{'PASS' if cond1['above_upper_buffer'] else 'FAIL'}] Close > Upper Buffer | "
                 f"[{'PASS' if cond1['vwap_slope_positive'] else 'FAIL'}] 12b VWAP Slope > 0 | "
                 f"[{'TRIGGERED' if cond1['exit_triggered'] else 'CLEAR'}] Exit Rule")
        r1 = s1.get("readiness")
        if r1:
            hurdle_txt = (f" | Clear-Both Hurdle: ${r1['price_hurdle']:,.2f} (+{r1['rally_to_hurdle_pct']:.2f}% needed)"
                          if r1.get("price_hurdle") is not None and r1.get("rally_to_hurdle_pct") is not None else "")
            L.append(f"*   **Readiness Radar:** {r1['gates_passed']}/{r1['gates_total']} Buy Gates Passed | "
                     f"vs 120D EMA: {_pct_s(r1.get('shield_dist_pct'))} | "
                     f"vs Upper Buffer: {_pct_s(r1.get('upper_buf_dist_pct'))}{hurdle_txt}")
        L.append(f"*   **Signal & Simulated State:** raw_signal = {sig_fmt(st1['raw_signal'])} | "
                 f"Sim Prior Pos = {st1['prior_position']} -> Action: {st1['action']} | "
                 f"Reference 3.0x ATR Stop: ${st1['reference_3x_atr_sl']:,.2f}{sl1_line}")
        if "flipped_on_last_bar" in st1 or "last_transition" in st1:
            flip1 = " **[NEW SIGNAL ON LATEST BAR]**" if st1.get("flipped_on_last_bar") else ""
            exp1 = f"{st1['exposure_pct']:.1f}%" if st1.get("exposure_pct") is not None else "UNAVAILABLE"
            L.append(f"*   **Transition Memory:** Last Flip: {_trans_txt(st1)} | Window BTC Exposure: {exp1}{flip1}")
        L.append(f"*   **Action by Actual Account State:** If currently FLAT (USDT): {st1['if_flat']} | "
                 f"If currently LONG (BTC): {st1['if_long']}")
    else:
        L.append(f"*   **Status:** UNAVAILABLE ({s1.get('reason', 'missing 4H/1D Spot bars')})")
    L.append("")

    s2 = a.get("sleeve2") or {}
    L.append("## 7. PROJECT F — SLEEVE #2 (1D TTM Volatility Squeeze · 20% Weight)")
    if s2.get("status") == "LIVE":
        ind2, cond2, st2 = s2["indicators"], s2["conditions"], s2["state"]
        bar2 = s2["last_closed_bar"]
        sl2_line = (f" | Active Entry Stop: ${st2['active_stop_loss']:,.2f}"
                    if st2.get("active_stop_loss") is not None else "")
        sq_txt = "ON" if cond2["squeeze_on_now"] else "OFF"
        rel_txt = "YES" if cond2["squeeze_release"] else "NO"
        L.append("*   **Strategy:** `tier14_ttm_squeeze_1d` (Spot BTC/USDT, zero leverage, "
                 "NO 120D EMA shield, 1D closed bars)")
        L.append(f"*   **Last Closed 1D Bar:** {bar2['open_utc']} -> {bar2['close_utc']} / "
                 f"{bar2['close_sgt']} ({s2['bars_analyzed']} closed 1D bars)")
        L.append(f"*   **Indicators:** Close ${ind2['close_price']:,.2f} | "
                 f"BB(20,2.0) ${ind2['bb_lower']:,.2f} to ${ind2['bb_upper']:,.2f} | "
                 f"KC(20,1.5) ${ind2['kc_lower']:,.2f} to ${ind2['kc_upper']:,.2f} "
                 f"(Mid ${ind2['kc_mid']:,.2f}) | Squeeze Now: {sq_txt} "
                 f"(Prior 3D: {ind2['prior_3d_squeeze_bars']}/3, Release: {rel_txt}) | "
                 f"OLS Mom(20): {ind2['mom']:+,.2f} (Prev {ind2['prev_mom']:+,.2f}) | "
                 f"Exit SMA(21): ${ind2['sma_21']:,.2f} | 1D ATR(14): ${ind2['atr_14']:,.2f}")
        L.append(f"*   **Checks:** [{'PASS' if cond2['squeeze_release'] else 'FAIL'}] Squeeze Release (after >=3d) | "
                 f"[{'PASS' if cond2['mom_positive'] else 'FAIL'}] Mom > 0 | "
                 f"[{'PASS' if cond2['mom_rising'] else 'FAIL'}] Mom Rising | "
                 f"[{'PASS' if cond2['above_kc_mid'] else 'FAIL'}] Close > KC Mid | "
                 f"[{'TRIGGERED' if cond2['exit_triggered'] else 'CLEAR'}] Exit (Close < SMA21 or Mom < 0)")
        r2 = s2.get("readiness")
        if r2:
            cr = r2.get("compression_ratio")
            cr_txt = (f"{cr:.2f}x ({'COILED <1.00' if cr < 1.0 else 'WIDE >=1.00'})"
                      if cr is not None else "UNAVAILABLE")
            L.append(f"*   **Readiness Radar:** {r2['gates_passed']}/{r2['gates_total']} Buy Gates Passed | "
                     f"BB/KC Compression: {cr_txt} | Active Squeeze Streak: {r2.get('squeeze_streak_days', 0)}d | "
                     f"vs KC Mid: {_pct_s(r2.get('kc_mid_dist_pct'))} | vs SMA21: {_pct_s(r2.get('sma21_dist_pct'))}")
        L.append(f"*   **Signal & Simulated State:** raw_signal = {sig_fmt(st2['raw_signal'])} | "
                 f"Sim Prior Pos = {st2['prior_position']} -> Action: {st2['action']} | "
                 f"Reference 2.0x ATR Stop: ${st2['reference_2x_atr_sl']:,.2f}{sl2_line}")
        if "flipped_on_last_bar" in st2 or "last_transition" in st2:
            flip2 = " **[NEW SIGNAL ON LATEST BAR]**" if st2.get("flipped_on_last_bar") else ""
            exp2 = f"{st2['exposure_pct']:.1f}%" if st2.get("exposure_pct") is not None else "UNAVAILABLE"
            L.append(f"*   **Transition Memory:** Last Flip: {_trans_txt(st2)} | Window BTC Exposure: {exp2}{flip2}")
        L.append(f"*   **Action by Actual Account State:** If currently FLAT (USDT): {st2['if_flat']} | "
                 f"If currently LONG (BTC): {st2['if_long']}")
        L.append("*   **Portfolio Rule:** Segregated virtual ledgers (80% Sleeve #1 / 20% Sleeve #2, "
                 "hard cap 15%-20% on #2); quarterly rebalance on Jan 1 / Apr 1 / Jul 1 / Oct 1 at "
                 "00:00 UTC if drift exceeds +/-3% ([77%, 83%]). Models 0.30% RT friction.")
    else:
        L.append(f"*   **Status:** UNAVAILABLE ({s2.get('reason', 'missing 1D Spot bars')})")
    L.append("")

    if a["problems"]:
        L.append("## DATA NOTES")
        for pr in a["problems"]:
            L.append(f"*   {pr}")
        L.append("")

    L.append("### AI EXECUTION PROTOCOL: SALAM PRO MAX v1.7 (3-VERDICT EDITION)")
    L.append("**Role:** quantitative analyst for a spot-only BTC/USDT operator running three "
             "independent systems inside one packet: (1) SALAM Protocol tactical structure/flow "
             "(Sections 1-5), (2) Project F Sleeve #1 — 4H Rolling VWAP Shield, 80% weight "
             "(Section 6), and (3) Project F Sleeve #2 — 1D TTM Volatility Squeeze, 20% weight "
             "(Section 7).")
    L.append("**Primary Directive:** use only numbers present in this packet. No external data, no "
             "recall, no forecasting, no recomputing indicators from memory. A missing number is "
             "UNAVAILABLE (never zero) — state what its absence costs the verdict.")
    L.append("")
    L.append("**THREE-VERDICT MANDATE & STRICT FIREWALL (NON-NEGOTIABLE):**")
    L.append("Start every response with a **3-VERDICT SUMMARY TABLE** covering all three systems, "
             "then present the detail sections. Each verdict is strictly walled off from the other two:")
    L.append("1. **Verdict 1 — SALAM Tactical (Sections 1-5):** Governed ONLY by the SALAM gate banner, "
             "Four Pillars, and SALAM rules below. Quote the Macro Weather summary (and live "
             "Sizing Check when active). Never use Project F to trigger or cancel SALAM. If SALAM's gate "
             "is PARTIAL or NONE, Verdict 1 MUST remain SUSPENDED / WAIT even if Sleeves #1 or #2 fire.")
    L.append("2. **Verdict 2 — Project F Sleeve #1 (Section 6 · 4H VWAP Shield · 80%):** Purely mechanical "
             "Spot OHLCV system (`tier1_5_vwap_shield`). Output BOTH the If-FLAT action and If-LONG action "
             "verbatim from Section 6, quote its key numbers (Close vs 120D EMA Shield, 15D Rolling VWAP, "
             "Upper/Lower Buffers, 3.0x ATR Stop, Readiness Radar, Last Transition, and flag any "
             "`[NEW SIGNAL ON LATEST BAR]`), and state the last closed 4H bar timestamp. **FIREWALL:** "
             "You are FORBIDDEN from overriding, delaying, or altering Verdict 2 using ETF flows, CVD, open "
             "interest, funding, L/S ratios, liquidation tiers, or SALAM's PARTIAL/NONE order-flow gate "
             "(Sleeve #1 uses only Spot klines and stays live 24/7).")
    L.append("3. **Verdict 3 — Project F Sleeve #2 (Section 7 · 1D TTM Squeeze · 20%):** Purely mechanical "
             "Spot OHLCV breakout system (`tier14_ttm_squeeze_1d`). Output BOTH the If-FLAT action and If-LONG "
             "action verbatim from Section 7, quote Squeeze state/release, BB/KC Compression Ratio, Readiness Radar, "
             "Last Transition (and flag any `[NEW SIGNAL ON LATEST BAR]`), OLS Momentum vs prior bar, Close vs "
             "KC Mid & SMA(21), and 2.0x ATR Stop, and state the last closed 1D bar timestamp. **FIREWALL:** "
             "Sleeve #2 intentionally has NO 120D EMA shield — you are FORBIDDEN from vetoing or altering "
             "Verdict 3 using the 120D EMA, 200D SMA, ETF flows, CVD, funding, or SALAM bands.")
    L.append("*End with a 2-line **Portfolio Alignment & Quarterly Rebalance Note** (informational only — "
             "never changes any verdict): state how many verdicts are active vs waiting, and remind the user of "
             "the 80/20 segregated ledger & quarterly rebalance schedule (Jan 1 / Apr 1 / Jul 1 / Oct 1 at 00:00 UTC, "
             "+/-3% drift band `[77%, 83%]`).*")
    L.append("")
    L.append("**THE FOUR PILLARS — the only drivers. Nothing else may start a trade.**")
    L.append("1. **Structure A — S/R:** tactical bands with confluence scores, macro S/R with touches.")
    L.append("2. **Structure B — Volume Profile:** 7D, 30D AND 4H value areas (VAH/POC/VAL) + nearest HVN.")
    L.append("3. **Fuel — Liquidation tiers:** leverage-derived clusters, reported only where they "
             "overlap measured structure.")
    L.append("4. **Trigger — Order Flow:** spot vs perp CVD across 1H/4H/24H, plus open-interest change.")
    L.append("")
    L.append("*Veto inputs (can block a trade, never start one): 200D average, ETF flows with trade "
             "date, funding percentile, long/short ratio.*")
    L.append("")
    L.append("**Structure tests (highest weight)**")
    L.append("*   *Value-area test:* evaluate 7D (inside = balance; above 7D VAH = breakout/premium; "
             "below 7D VAL = breakdown/discount) and 30D (below 30D VAL = HTF discount and the "
             "return-to-value line) separately.")
    L.append("*   *POC test:* price within 0.25% of any POC means the market is balanced on the "
             "defended price. That explains quiet tape; it is not a signal.")
    L.append("*   *Band quality:* an edge sitting beyond the nearest measured volume node is weaker "
             "than its score. On a low score, name what carried it and what is missing.")
    L.append("*   *Chop rule:* inside the mid band and more than 1% from BOTH band edges = NO TRADE "
             "regardless of CVD. Quote the two distances.")
    L.append("*   *Density test:* compare measured levels above with measured levels below. Thin path "
             "= fast travel; dense path = grind.")
    L.append("")
    L.append("**Fuel tests**")
    L.append("*   Tiers are leverage arithmetic (100x dies 1% from entry, 50x 2%, 25x 4%, 10x 10%) and "
             "they RE-CENTRE with price. Never quote a tier as a fixed target.")
    L.append("*   Report a tier only when it overlaps a measured structure (volume node, >=2 touches, "
             "band edge, macro S/R) within 0.5%. List the overlaps; ignore the rest.")
    L.append("*   Convert to coins: notional / price = BTC of forced orders, and as % of open interest.")
    L.append("*   Fuel is symmetric by assumption: say so, and never infer direction from it. Only "
             "the terrain around it is asymmetric. Name the exhaust point.")
    L.append("*   In your output, tag every DERIVED figure `estimated` and every venue-specific "
             "figure with its venue (`[BIN]` / `[OKX]`). This is a labelling rule for what you "
             "write, not a reason to discard a packet figure.")
    L.append("")
    L.append("**Trigger tests (confirmation only, only at an anchor)**")
    L.append("*   Read spot vs perp CVD in 1H, 4H and 24H. Compute perp:spot 24H ratio; above 3x means "
             "futures-led, i.e. positioning rather than accumulation.")
    L.append("*   OI rising while price is flat and spot CVD is negative = distribution. Say it.")
    L.append("*   No sweep flag = that rail is NOT armed, whatever the band score. When a sweep is "
             "present, state its level, direction and time.")
    L.append("*   If ## DATA NOTES lists HTTP 451s, state that perp data is OKX, not Binance — "
             "measured, different venue.")
    L.append("*   If the gate is PARTIAL or NONE, plans are withheld — do not invent levels. An "
             "unknown state reads as NONE.")
    L.append("")
    if state in ("PARTIAL", "NONE"):
        L.append("## ❌ EXECUTION SUSPENDED")
        L.append(f"*   **State: {state}.** Perp CVD is "
                 + ("the archive figure for " + dump["date"] + " (T+1)" if dump else "unavailable")
                 + ". Rail A and Rail B plans are withheld by design — a lagged or missing flow "
                   "figure is not a basis for an order, and a model reading one beside a plan will "
                   "use it as if it were live.")
        L.append("*   **To lift the gate, either:** run this script on a Binance-reachable host "
                 "(full live perp), or record a screenshot reading with a number and a UTC time:")
        L.append('    *   `python3 salam_protocol.py --manual "perp_cvd_24h=+2663,at=04:05Z"`')
        L.append("*   An adjective does not unlock it. `perp_cvd=falling` will print under [MANUAL] "
                 "and leave execution suspended.")
        L.append("")
        L.append("*Never forecast. State what the rules permit, name the trigger that would change the "
                 "answer, and stop.*")
    else:
        L.append("**Binding Arithmetic (not optional, never adjusted)**")
        L.append(f"*   **Rail B stop loss = Entry - (1.5 x ATR 1H).** ATR 1H is printed in section 3; "
                 f"print the ATR and the dollar stop, do not invent one.")
        L.append(f"*   **Risk per trade = {RISK_PCT:.2%} of total portfolio value.** Position size = "
                 f"(portfolio x {RISK_PCT:.2%}) / (entry - stop).")
        L.append(f"*   **If that size exceeds {MAX_POS_PCT_OF_USDT:.0%} of the USDT inventory, SKIP** — "
                 f"and report the conflict: \"risk budget asks X BTC, the cap allows Y BTC, so this "
                 f"rail is vetoed.\" Do not silently resize; do not drop the rule.")
        L.append("*   **Rail A invalidation = a DAILY close above (band high + 1 x ATR 1H).** Print the "
                 "number. A 1H close is noise, not invalidation.")
        rbs = a.get("rail_b_sizing")
        if rbs:
            v50 = "VETOED — EXCEEDS 30% USDT CAP" if rbs["vetoed_at_50_50"] else "FITS CAP"
            v100 = "VETOED — EXCEEDS 30% USDT CAP" if rbs["vetoed_at_100_usdt"] else "FITS CAP"
            L.append(f"*   **Pre-Computed Sizing Check (at {rbs['ref_source']} ${rbs['ref_entry']:,.0f}):** "
                     f"1.5x ATR stop = ${rbs['stop_dist']:,.0f} ({rbs['stop_pct']:.2f}%, stop ${rbs['stop_price']:,.0f}) "
                     f"-> {RISK_PCT:.2%} risk requires **{rbs['implied_port_pct']:.1f}%** of total portfolio. "
                     f"At 50/50 BTC/USDT (cap {rbs['cap_port_pct_50_50']:.1f}% of portfolio): **{v50}**; "
                     f"at 100% USDT (cap {rbs['cap_port_pct_100_usdt']:.1f}%): **{v100}**.")
        L.append("")
        L.append("**Execution Rules:**")
        L.append("*   **Rail B (USDT -> BTC):** a BULLISH or MACRO BULLISH sweep into a Major Support "
                 "that overlaps a Lower Long tier, confirmed by positive Spot CVD -> enter on the "
                 "reclaim. Stop from the arithmetic. Target = the next MEASURED level above, named; "
                 "if none exists in this packet, write \"no target\".")
        L.append("*   **Rail A (BTC -> USDT):** a BEARISH or MACRO BEARISH sweep into a Major Resistance "
                 "that overlaps an Upper Short tier, confirmed by flat/negative Spot CVD -> trim. "
                 "Invalidation per the arithmetic. Target = the next MEASURED level below, named; "
                 "if none exists in this packet, write \"no target\".")
        L.append("")
        L.append("**Required Output Format (present the 3-VERDICT SUMMARY TABLE first, "
                 "followed by Verdict 1 details 0-7 and Verdict 2/3 summaries):**")
        L.append("0. **BOTTOM LINE** — one plain sentence a non-trader can act on "
                 "(\"NO ACTION at $X\" or \"TRIM 0.25 BTC at $Y\") plus the bias in one clause.")
        L.append("1. **Market State** — regime, where price sits against structure, sweep status, gate.")
        L.append("2. **The Four Pillars** — one block each, every number labelled MEASURED or DERIVED.")
        L.append("3. **The Levels Map** — every level with distance in % and its type.")
        L.append("4. **Rail B (Buy) Plan** — trigger, what is missing, stop, the sizing result "
                 "including the conflict if any, target.")
        L.append("5. **Rail A (Sell/Trim) Plan** — tranches with price windows, invalidation number, "
                 "target.")
        L.append("6. **If / Then block** — the price alerts as a list; the only part that gets re-read.")
        L.append("7. **Not verified** — OKX-not-Binance, modelled dollars, assumed weights, "
                 "any UNAVAILABLE.")
        L.append("")
        L.append("*Never forecast. State what the rules permit, name the trigger that would change the "
                 "answer, and stop. Jargon is allowed in 1-7 and never in 0.*")
    L.append("")
    # ── order: rules before data ──────────────────────────────────────────────
    # A packet is pasted into a model, so the instructions must be read before the numbers:
    # instructions that arrive after 60 lines of figures get treated as commentary. The title,
    # timestamp and gate banner stay first because a human scanning the file needs those in the
    # top three lines. Everything else is unchanged — this only moves the v1.7 block.
    def _first(prefix):
        for idx, line in enumerate(L):
            if line.startswith(prefix):
                return idx
        raise RuntimeError(f"markdown assembly lost its {prefix!r} anchor")

    i_data  = _first("## 1. THE ANCHOR")
    i_proto = _first("### AI EXECUTION PROTOCOL")
    # the protocol block runs to the end of L at this point (footer is appended below)
    L = L[:i_data] + L[i_proto:] + L[i_data:i_proto]

    L.append("---")
    L.append("*Generated by salam_protocol.py — standard library only, closed bars only, no state. "
             "UNAVAILABLE is a valid answer; every estimated figure carries its label.*")
    return "\n".join(L) + "\n"


# ────────────────────────────────── main ──────────────────────────────────
def selftest() -> int:
    """Offline maths assertions + one live cross-venue consistency check."""
    fails: list[str] = []

    def check(name: str, cond: bool, detail: str = ""):
        print(("  PASS  " if cond else "  FAIL  ") + name + (f"  ({detail})" if detail else ""))
        if not cond:
            fails.append(name)

    now = datetime.now(timezone.utc).timestamp() * 1000
    bars = []
    for i in range(60):                       # zig-zag so pivots exist, base near a round 1000
        c = 1000.0 + i + (14.0 if i % 4 == 2 else -9.0 if i % 4 == 0 else 0.0)
        bars.append({"open_time": int(now) - (40 - i) * 3_600_000, "o": c - 0.5, "h": c + 1.0,
                     "l": c - 1.0, "c": c, "v": 10.0, "close_time": int(now) - (39 - i) * 3_600_000,
                     "taker_buy": 6.0})
    print("offline")
    check("ATR is positive", (atr_wilder(bars, 14) or 0) > 0)
    check("CVD = sum(2*taker_buy - volume)",
          abs((cvd(bars, 4) or 0) - 4 * (2 * 6.0 - 10.0)) < 1e-9, f"{cvd(bars, 4)}")
    vp = volume_profile(bars)
    check("volume profile has POC/VAH/VAL", bool(vp) and vp["val"] <= vp["poc"] <= vp["vah"])
    check("HVN returns a level", hvn_nearest(vp, vp["poc"]) is not None)
    band = {"low": min(b["l"] for b in bars) - 5, "high": max(b["h"] for b in bars) + 5,
            "center": vp["poc"]}
    check("confluence maxes at 10 with POC+VA+round", confluence(band, vp)[0] == 10,
          f"{confluence(band, vp)}")
    cl = cluster([100.0, 100.5, 130.0], 0.01)
    check("clustering merges within 1%", len(cl) == 2, f"{len(cl)} clusters")
    hi, lo_ = pivots(bars, 2)
    check("pivots found", len(hi) >= 1 and len(lo_) >= 1, f"{len(hi)} highs / {len(lo_)} lows")

    _flow = {"1h": 1.0, "4h": 2.0, "24h": 3.0}
    base = {"price": 1000.0, "problems": [], "cvd_spot": dict(_flow), "cvd_perp": dict(_flow),
            "sweep": {"flag": "NONE"}, "deriv_src": "BINANCE"}
    _now = datetime.now(timezone.utc)
    fresh = (_now - timedelta(minutes=4)).strftime("%H:%M") + "Z"
    stale = (_now - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M") + "Z"
    full = dict(base, perp_cvd_ok=True, exec_state="FULL")
    check("FULL state prints execution rules", "Execution Rules" in render(full))
    part = dict(base, perp_cvd_ok=False, exec_state="PARTIAL",
                perp_dump={"date": "2026-11-24", "bars": 24, "cvd_4h": 1.0, "cvd_24h": 2.0})
    part_md = render(part)
    check("PARTIAL state suspends execution", "EXECUTION SUSPENDED" in part_md)
    check("PARTIAL state withholds the rails",
          "Rail B (USDT -> BTC)" not in part_md and "Rail A (BTC -> USDT)" not in part_md)
    check("PARTIAL state still names the archive day", "PARTIAL ORDER FLOW" in part_md)
    none_md = render(dict(base, perp_cvd_ok=False, exec_state="NONE"))
    check("NONE state warns plainly", "PERP CVD UNAVAILABLE" in none_md)
    man_md = render(dict(base, perp_cvd_ok=False, exec_state="MANUAL", manual_at=fresh,
                         manual={"perp_cvd_24h": "+2663", "at": fresh}))
    check("MANUAL state unlocks the rails", "Execution Rules" in man_md and "MANUAL" in man_md)

    # ── v1.8 gate regressions (each failed on the pre-fix code) ──
    flows = {"cvd_spot": {"1h": 1.0, "4h": 2.0, "24h": 3.0},
             "cvd_perp": {"1h": 1.0, "4h": 2.0, "24h": 3.0}}

    missing_state = render(dict(base, perp_cvd_ok=True, **flows))
    check("a packet with no exec_state never prints plans",
          "Execution Rules" not in missing_state and "state: NONE" in missing_state)

    garbage = render(dict(base, perp_cvd_ok=True, exec_state="GARBAGE", **flows))
    check("an unknown exec_state reads as NONE, not as healthy",
          "Execution Rules" not in garbage and "state: NONE" in garbage)
    check("an unknown exec_state says what the packet claimed", "GARBAGE" in garbage)

    for bad in ("perp_cvd_24h=+1,at=2030-01-01T00:00Z", "perp_cvd_24h=+1,at=2099-06-01 12:00Z"):
        check(f"future stamp is rejected ({bad.split('at=')[1]})", parse_manual(bad)[1] is False)

    _recent = (_now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%MZ")
    for val in ("nan", "inf", "-inf"):
        check(f"non-finite manual value is rejected ({val})",
              parse_manual(f"perp_cvd_24h={val},at={_recent}")[1] is False)
    check("a finite manual value still unlocks",
          parse_manual(f"perp_cvd_24h=+2663,at={_recent}")[1] is True)

    # the shape analyse() emits when the spot feed fails: a TRUTHY dict of Nones, which is why a
    # bool() test let this through. These assertions use production shapes, not {}.
    dead_spot = {"1h": None, "4h": None, "24h": None}
    no_spot = render(dict(base, perp_cvd_ok=True, exec_state="FULL",
                          cvd_perp=flows["cvd_perp"], cvd_spot=dead_spot))
    check("FULL with a dead spot series is demoted to NONE",
          "Execution Rules" not in no_spot and "state: NONE" in no_spot)
    check("the banner stops claiming both halves are measured", "both measured" not in no_spot)
    half_spot = render(dict(base, exec_state="FULL", cvd_perp=flows["cvd_perp"],
                            cvd_spot={"1h": 0.0}))
    check("a spot series with only 1h is not enough for FULL", "Execution Rules" not in half_spot)
    zero_spot = render(dict(base, exec_state="FULL", cvd_perp=flows["cvd_perp"],
                            cvd_spot={"1h": 0.0, "4h": 0.0, "24h": 0.0}))
    check("a genuinely balanced spot series still unlocks", "Execution Rules" in zero_spot)
    man_hand = render(dict(base, exec_state="MANUAL", cvd_perp={}, manual_at=fresh,
                           manual={"perp_cvd_24h": "+2663", "at": fresh}))
    check("MANUAL survives an empty cvd_perp (hand entry is the whole point)",
          "Execution Rules" in man_hand and "state: MANUAL" in man_hand)
    _hm = datetime.now(timezone.utc).strftime("%H:%M")
    check("an explicit 1900 date is not mistaken for the time-only form",
          parse_manual(f"perp_cvd_24h=+500,at=1900-06-15T{_hm}Z")[1] is False)
    _skew = (datetime.now(timezone.utc) + timedelta(minutes=3)).strftime("%H:%M")
    check("three minutes of clock skew still unlocks",
          parse_manual(f"perp_cvd_24h=+500,at={_skew}Z")[1] is True)
    dump_state = render(dict(base, exec_state="GARBAGE", cvd_spot={}, cvd_perp={},
                             perp_dump={"date": "2026-11-26", "bars": 24, "cvd_4h": 10.0,
                                        "cvd_24h": 50.0}))
    check("a demoted packet does not wear the PARTIAL banner",
          "spot and levels are live" not in dump_state)

    class _StrState(str, enum.Enum):
        FULL = "FULL"
    _enum_md = render(dict(base, exec_state=_StrState.FULL))
    check("a str-enum state cannot smuggle a token into the banner",
          "Execution Rules" not in _enum_md and "S.FULL)" not in _enum_md)

    _old_rows = [[str(1_700_000_000_000 + h * 3600_000), "1", "2"] for h in range(23, -1, -1)]
    try:
        closed_bars(_old_rows, 1_700_000_000_000 + 30 * 86400_000)
        _stale_blocked = False
    except ValueError:
        _stale_blocked = True
    check("a month-old archive is refused, not averaged", _stale_blocked)

    _open_rows_24 = [[str(1_700_000_000_000 + h * 3600_000), "1", "2"] for h in range(23, -1, -1)]
    try:
        okx_perp_cvd(fetch=lambda url: {"data": _open_rows_24},
                     now_ms=1_700_000_000_000 + 23 * 3600_000 + 600_000)
        _perp_blocked = False
    except ValueError:
        _perp_blocked = True
    check("okx_perp_cvd refuses a window with only 23 closed rows", _perp_blocked)
    _good_rows = [[str(1_700_000_000_000 + h * 3600_000), "1", "2"] for h in range(24, -1, -1)]
    _good = okx_perp_cvd(fetch=lambda url: {"data": _good_rows},
                         now_ms=1_700_000_000_000 + 24 * 3600_000 + 600_000)
    check("okx_perp_cvd returns windows when 24 closed rows exist", _good["bars"] == 24)

    check("oi_change with one sample returns None, not an exception",
          oi_change([100.0], [0], 4) is None)

    _t0 = 1_700_000_000_000
    # OKX sends newest first: hour 25 is the still-forming one, so it comes first in the feed
    _open_rows = [[str(_t0 + h * 3600_000), "1", "2"] for h in range(25, -1, -1)]
    _closed = closed_bars(_open_rows, _t0 + 25 * 3600_000 + 600_000)        # 10 min into hour 25
    check("the still-forming hour is dropped from perp CVD", len(_closed) == 25)
    check("dropped bar is the newest one", _closed[-1]["t"] == _t0 + 24 * 3600_000)

    check("a suspended gate prints no binding arithmetic", "Binding Arithmetic" not in part_md)
    check("the banner names the state token", "state: FULL" in render(full))

    # ── audit regressions (F1-F7: must fail red before fix, pass green after) ──
    _f1_dump = [{"open_time": i * 3600_000, "o": 60500.0, "h": 60550.0, "l": 59400.0,
                 "c": 59500.0, "v": 10.0, "close_time": (i + 1) * 3600_000 - 1, "taker_buy": 4.0}
                for i in range(6)]
    check("breakdown candle through support is not a bearish sweep",
          sweep(_f1_dump, None, None, [], [{"center": 60000.0, "touches": 3}])["flag"] == "NONE")
    _f1_brk = [{"open_time": i * 3600_000, "o": 59500.0, "h": 60600.0, "l": 59450.0,
                "c": 60500.0, "v": 10.0, "close_time": (i + 1) * 3600_000 - 1, "taker_buy": 6.0}
               for i in range(6)]
    check("breakout candle through resistance is not a bullish sweep",
          sweep(_f1_brk, None, None, [{"center": 60000.0, "touches": 3}], [])["flag"] == "NONE")
    _f1_broken = _f1_brk[:4] + [
        {"open_time": 4 * 3600_000, "o": 60200.0, "h": 60250.0, "l": 59800.0, "c": 60100.0,
         "v": 10.0, "close_time": 5 * 3600_000 - 1, "taker_buy": 6.0},
        {"open_time": 5 * 3600_000, "o": 60100.0, "h": 60120.0, "l": 59700.0, "c": 59750.0,
         "v": 10.0, "close_time": 6 * 3600_000 - 1, "taker_buy": 3.0},
    ]
    check("a sweep broken by a later closed bar is invalidated",
          sweep(_f1_broken, None, None, [{"center": 60000.0, "touches": 3}], [])["flag"] == "NONE")
    _f1_d1 = [{"open_time": i * 86400_000,
               "o": (60000.0 if i in (5, 15, 22) else 63000.0) + 200.0,
               "h": (60000.0 if i in (5, 15, 22) else 63000.0) + 400.0,
               "l": (60000.0 if i in (5, 15, 22) else 63000.0),
               "c": (60000.0 if i in (5, 15, 22) else 63000.0) + 200.0,
               "v": 100.0, "close_time": (i + 1) * 86400_000 - 1, "taker_buy": 50.0}
              for i in range(30)]
    _f1_tight = [{"open_time": i * 3600_000, "o": 60200.0, "h": 60250.0, "l": 60100.0,
                  "c": 60150.0, "v": 10.0, "close_time": (i + 1) * 3600_000 - 1, "taker_buy": 5.0}
                 for i in range(5)] + [
        {"open_time": 5 * 3600_000, "o": 60200.0, "h": 60250.0, "l": 59800.0, "c": 60080.0,
         "v": 10.0, "close_time": 6 * 3600_000 - 1, "taker_buy": 6.0}]
    _f1_a = analyse({"problems": [], "deriv_src": "BINANCE", "price_src": "TICKER",
                     "price": 60080.0, "d1": _f1_d1, "h4": [], "h1": _f1_tight, "fh1": [],
                     "oi_btc": None, "oi_4h_chg": None, "oi_24h_chg": None, "funding": None,
                     "funding_pct90": None, "ls_ratio": None, "etf": None})
    check("a reclaim closing within 0.25% of macro support still registers",
          _f1_a["sweep"]["flag"] == "MACRO BULLISH SWEEP")

    _nosw = render({"price": 60000.0, "problems": []})
    check("missing sweep dict never prints $0",
          "at $0" not in _nosw and "Sweep Status:** UNAVAILABLE" in _nosw)
    _nullsw = render(dict(base, exec_state="FULL",
                          sweep={"flag": "BULLISH SWEEP", "level": None, "at": None}))
    check("sweep with null level never prints $0",
          "at $0" not in _nullsw and "Sweep Status:** UNAVAILABLE" in _nullsw)

    _dup_okx = [[str(1_700_000_000_000), "1", "2"] for _ in range(25)]
    try:
        okx_perp_cvd(fetch=lambda _u: {"data": _dup_okx},
                     now_ms=1_700_000_000_000 + 3600_000 + 60_000)
        _dup_blocked = False
    except ValueError:
        _dup_blocked = True
    check("okx_perp_cvd refuses 24 copies of one hour", _dup_blocked)
    _gap_okx = [[str(1_700_000_000_000 + (h if h < 12 else h + 3) * 3600_000), "1", "2"]
                for h in range(24, -1, -1)]
    try:
        okx_perp_cvd(fetch=lambda _u: {"data": _gap_okx},
                     now_ms=1_700_000_000_000 + 27 * 3600_000 + 60_000)
        _gap_blocked = False
    except ValueError:
        _gap_blocked = True
    check("okx_perp_cvd refuses a gapped 24h window", _gap_blocked)

    _f4_d1 = [{"open_time": i * 86400_000,
               "o": (60000.0 if i == 15 else 63000.0) + 1500.0,
               "h": (60000.0 if i == 15 else 63000.0) + 3000.0,
               "l": (60000.0 if i == 15 else 63000.0),
               "c": (60000.0 if i == 15 else 63000.0) + 1500.0,
               "v": 100.0, "close_time": (i + 1) * 86400_000 - 1, "taker_buy": 50.0}
              for i in range(30)]
    _f4_h4 = []
    for i in range(40):
        _lo = 58500.0 if i == 10 else (59000.0 if i == 16 else (
            59700.0 if i == 22 else (60600.0 if i == 28 else 62000.0)))
        _hi = 60600.0 if i == 28 else _lo + 800.0
        _f4_h4.append({"open_time": i * 14400_000, "o": _lo + 200.0, "h": _hi, "l": _lo,
                       "c": _lo + 200.0, "v": 50.0, "close_time": (i + 1) * 14400_000 - 1,
                       "taker_buy": 25.0})
    _f4_a = analyse({"problems": [], "deriv_src": "OKX", "price_src": "TICKER",
                     "price": 60693.04, "d1": _f4_d1, "h4": _f4_h4, "h1": [], "fh1": [],
                     "oi_btc": 31843.0, "oi_4h_chg": None, "oi_24h_chg": None,
                     "funding": None, "funding_pct90": None, "ls_ratio": None, "etf": None})
    check("liquidation tier inside a wide tactical band is tagged",
          _f4_a["sup_band"] is not None and _f4_a["sup_band"]["liq"] is not None)
    check("inside_band carries its liquidation overlay",
          _f4_a["inside_band"] is not None and _f4_a["inside_band"].get("liq") is not None)
    check("1-touch macro pivot is not tagged with liquidation fuel",
          bool(_f4_a["macro_sup"]) and _f4_a["macro_sup"][0]["touches"] == 1
          and _f4_a["macro_sup"][0]["liq"] is None)

    check("missing ls_ratio prints UNAVAILABLE",
          "Long/Short account ratio (4H):** UNAVAILABLE"
          in render(dict(base, exec_state="FULL", ls_ratio=None)))
    check("CLOSE-1D fallback tags Section 1 Current Price",
          "**Current Price:** $1,000 [BIN-CLOSE 1D]"
          in render(dict(base, exec_state="FULL", price_src="CLOSE-1D")))
    check("NONE perp_src does not label Perp CVD as [BIN]",
          "Perp [BIN]" not in render(dict(base, exec_state="NONE", perp_src=None,
                                          cvd_perp={"1h": None, "4h": None, "24h": None})))
    _mixed_md = render(dict(base, exec_state="FULL", deriv_src="OKX", oi_btc=98000.0,
                            oi_src="BINANCE", funding=0.01, fund_src="BINANCE",
                            fund_hist_src="OKX", funding_pct90=None, ls_ratio=2.1,
                            lsr_src="OKX"))
    check("mixed Binance/OKX metrics render per-field venue tags",
          "98,000 BTC [BIN]" in _mixed_md and "2.10 [OKX]" in _mixed_md)

    import io as _aio, zipfile as _azip, datetime as _adt
    def _az(rows):
        buf = _aio.BytesIO()
        with _azip.ZipFile(buf, "w") as z:
            z.writestr("BTCUSDT-1h.csv", "\n".join(rows))
        return buf.getvalue()
    _ad1 = _adt.datetime.now(timezone.utc).date() - _adt.timedelta(days=1)
    _ad2 = _adt.datetime.now(timezone.utc).date() - _adt.timedelta(days=2)
    _ab1 = int(_adt.datetime(_ad1.year, _ad1.month, _ad1.day, tzinfo=timezone.utc).timestamp() * 1000)
    _ab2 = int(_adt.datetime(_ad2.year, _ad2.month, _ad2.day, tzinfo=timezone.utc).timestamp() * 1000)
    _rev_rows = [f"{_ab1 + h * 3600000},1,1,1,1,1.0,0,0,1,{1.0 if h >= 20 else 0.5},0,0"
                 for h in range(23, -1, -1)]
    _d_rev, _ = perp_cvd_from_dump(1, fetch=lambda _u: _az(_rev_rows))
    check("archive 4H CVD sorts rows chronologically before slicing",
          _d_rev is not None and abs(_d_rev["cvd_4h"] - 4.0) < 1e-9)
    _d2_rows = [f"{_ab2 + h * 3600000},1,1,1,1,1.0,0,0,1,0.75,0,0" for h in range(24)]
    _d_fb, _ = perp_cvd_from_dump(
        2, fetch=lambda u: b"not-a-zip" if _ad1.isoformat() in u else _az(_d2_rows))
    check("corrupt yesterday archive falls back to prior day",
          _d_fb is not None and _d_fb["date"] == _ad2.isoformat())

    _band_md = render(dict(base, exec_state="FULL",
                           res_band={"low": 1050.0, "high": 1100.0, "score": 3,
                                     "why": ["round-1k"], "liq": None}))
    check("tactical band prints confluence reason", "round-1k" in _band_md)
    _f7_h1 = [{"open_time": h * 3600_000, "o": 100.0, "h": 105.0, "l": 99.0,
               "c": (100.0 if h < 24 else 102.0), "v": 10.0,
               "close_time": (h + 1) * 3600_000 - 1, "taker_buy": 5.0} for h in range(25)]
    _f7_a = analyse({"problems": [], "deriv_src": "BINANCE", "price_src": "TICKER",
                     "price": 102.0, "d1": _f1_d1, "h4": [], "h1": _f7_h1, "fh1": [],
                     "oi_btc": None, "oi_4h_chg": None, "oi_24h_chg": None,
                     "funding": None, "funding_pct90": None, "ls_ratio": None, "etf": None})
    _chg_md = render(dict(_f7_a, exec_state="FULL", cvd_spot=_flow, cvd_perp=_flow))
    check("packet prints closed-bar 1H/4H/24H price change",
          "Price Change" in _chg_md and "+2.00%" in _chg_md)
    check("suspended packet keeps the Never forecast rule", "Never forecast." in part_md)
    _full_md = render(full)
    check("embedded prompt names HTTP 451 venue rule and separates no-sweep from sweep details",
          "HTTP 451" in _full_md and "When a sweep is present" in _full_md)

    import datetime as _dt
    _day = _dt.date(2026, 11, 24)
    _base_ms = int(_dt.datetime(2026, 11, 24, tzinfo=timezone.utc).timestamp() * 1000)
    good = [{"t": _base_ms + h * 3600_000, "v": 1.0, "taker_buy": 0.6} for h in range(24)]
    dup = [{"t": _base_ms, "v": 1.0, "taker_buy": 0.6} for _ in range(24)]
    split = [{"t": _base_ms + h * 3600_000, "v": 1.0, "taker_buy": 0.6} for h in range(12)] + \
            [{"t": _base_ms + 86_400_000 + h * 3600_000, "v": 1.0, "taker_buy": 0.6}
             for h in range(12)]
    _h = 3600_000
    _t0 = 1_700_000_000_000
    _reg = list(range(0, 24))                      # 24 contiguous hourly samples
    _treg = [_t0 + h * _h for h in _reg]
    # index 20 is the 4-hour mark: 90 -> 95 is +5.56%. The first version of this fixture put
    # 90 at index 21 and asserted against index 20, so the test failed against correct code.
    # 24 samples, index 23 is newest; the 4H mark is index 19. 90 -> 95 = +5.56%.
    # Two earlier fixtures put the 90 one or two slots late and asserted against the wrong
    # index, which failed against correct code — the fixture was wrong, not the function.
    _sreg = [100.0] * 19 + [90.0, 91.0, 92.0, 93.0, 95.0]
    check("OI change matches the horizon by timestamp",
          oi_change(_sreg, _treg, 4) is not None
          and abs(oi_change(_sreg, _treg, 4) - (95.0 / 90.0 - 1) * 100) < 1e-9,
          f"{oi_change(_sreg, _treg, 4)}")
    _gap_t = [t for i, t in enumerate(_treg) if not (19 <= i <= 21)]   # drop 3 hours at the mark
    _gap_s = [v for i, v in enumerate(_sreg) if not (19 <= i <= 21)]
    check("a gap at the horizon returns UNAVAILABLE, not a shifted window",
          oi_change(_gap_s, _gap_t, 4) is None, f"{oi_change(_gap_s, _gap_t, 4)}")
    check("mismatched series and stamps return UNAVAILABLE",
          oi_change(_sreg, _treg[:-1], 4) is None)

    import io as _io
    import zipfile as _zip

    def _z(rows):
        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w") as z:
            z.writestr("BTCUSDT-1h.csv", "\n".join(rows))
        return buf.getvalue()

    _yday = _dt.datetime.now(timezone.utc).date() - _dt.timedelta(days=1)
    _b = int(_dt.datetime(_yday.year, _yday.month, _yday.day, tzinfo=timezone.utc).timestamp() * 1000)
    _real = [f"{_b + h * 3600000},1,1,1,1,1.0,0,0,1,0.6,0,0" for h in range(24)]
    _d, _e = perp_cvd_from_dump(1, fetch=lambda _u: _z(_real))
    check("the loader accepts a genuine 24-hour dump", _d is not None, str(_e))
    _d2, _e2 = perp_cvd_from_dump(1, fetch=lambda _u: _z([_real[0]] * 24))
    check("the loader refuses 24 copies of one hour",
          _d2 is None and "unusable" in (_e2 or ""), str(_e2))

    check("a complete 24-hour archive day is accepted", dump_day_problem(good, _day) is None)
    check("24 copies of one hour are rejected", dump_day_problem(dup, _day) is not None,
          str(dump_day_problem(dup, _day)))
    check("a day split across two dates is rejected", dump_day_problem(split, _day) is not None,
          str(dump_day_problem(split, _day)))
    check("23 rows are rejected", dump_day_problem(good[:23], _day) is not None)

    _noatr = render(dict(base, perp_cvd_ok=True, exec_state="FULL", atr1h=None))
    check("missing ATR never prints a zero stop distance",
          "UNAVAILABLE)" in _noatr and "= 0)" not in _noatr)
    _settling = render(dict(base, perp_cvd_ok=True, exec_state="FULL", etf={
        "latest_date": "26 Nov 2026", "one_day_m": -100.0, "one_day_settling": True,
        "five_day_m": -200.0}))
    check("a settling ETF row is labelled settling", "settling" in _settling)

    check("a candle-close price is never labelled as a ticker",
          "[BIN-CLOSE 1D]" in render(dict(base, perp_cvd_ok=True, exec_state="FULL",
                                          price_src="CLOSE-1D")))
    check("a ticker price still reads [BIN]",
          "[BIN]" in render(dict(base, perp_cvd_ok=True, exec_state="FULL", price_src="TICKER")))

    okx_md = render(dict(base, perp_cvd_ok=True, exec_state="FULL", perp_src="OKX-RUBIK"))
    check("OKX perp CVD is labelled and still execution-grade",
          "OKX-RUBIK" in okx_md and "Execution Rules" in okx_md)
    _, ok_num = parse_manual(f"perp_cvd_24h=+2663,at={fresh}")
    _, ok_adj = parse_manual(f"perp_cvd=falling,spot_cvd=flat,at={fresh}")
    _, ok_junk = parse_manual("perp_cvd_24h=+2663,at=garbageZ")
    _, ok_stale = parse_manual(f"perp_cvd_24h=+2663,at={stale}")
    _, ok_noat = parse_manual("perp_cvd_24h=+2663")
    check("manual with a number + fresh time unlocks", ok_num is True)
    check("manual adjective does NOT unlock", ok_adj is False)
    check("manual with an unparseable time does NOT unlock", ok_junk is False)
    check("manual older than the freshness ceiling does NOT unlock", ok_stale is False)
    check("manual with no time does NOT unlock", ok_noat is False)

    # ── Project F Sleeve #1 & #2 + 3-Verdict Pro Max checks ──
    _s1_t0 = 1_700_000_000_000 - (1_700_000_000_000 % 86_400_000)
    _s1_bull = []
    for _i in range(780):
        _c = 100.0 + (0.2 if _i % 2 == 0 else -0.2) if _i < 765 else 100.0 + (_i - 764) * 1.5
        _s1_bull.append({
            "open_time": _s1_t0 + _i * 14_400_000,
            "o": _c - 0.1, "h": _c + 0.5, "l": _c - 0.5, "c": _c, "v": 10.0,
            "close_time": _s1_t0 + (_i + 1) * 14_400_000 - 1, "taker_buy": 5.0,
        })
    _res1 = sleeve1_vwap_shield(_s1_bull)
    check("Sleeve #1 bullish breakout fires +1 with 3.0x ATR stop",
          _res1.get("status") == "LIVE"
          and _res1["state"]["raw_signal"] == 1
          and _res1["state"]["if_flat"] == "BUY BTC at next bar open"
          and _res1["state"]["reference_3x_atr_sl"] < _res1["indicators"]["close_price"],
          str(_res1.get("state")))

    _s1_bear = []
    for _i in range(780):
        _c = 200.0 + (0.2 if _i % 2 == 0 else -0.2) if _i < 732 else 100.0 + (_i - 732) * 0.25
        _s1_bear.append({
            "open_time": _s1_t0 + _i * 14_400_000,
            "o": _c - 0.1, "h": _c + 0.5, "l": _c - 0.5, "c": _c, "v": 10.0,
            "close_time": _s1_t0 + (_i + 1) * 14_400_000 - 1, "taker_buy": 5.0,
        })
    _res1_bear = sleeve1_vwap_shield(_s1_bear)
    check("Sleeve #1 macro shield blocks buys when below 120D EMA",
          _res1_bear.get("status") == "LIVE"
          and not _res1_bear["conditions"]["above_macro_shield"]
          and _res1_bear["state"]["raw_signal"] == -1)

    _s1_full_sigs, _, _ = _sleeve1_signals(_s1_bull)
    _s1_cut_sigs, _, _ = _sleeve1_signals(_s1_bull[:770])
    check("Sleeve #1 passes bit-for-bit truncation invariance",
          _s1_cut_sigs == _s1_full_sigs[:770])

    _s2_bars = []
    for _i in range(66):
        if _i < 45:
            _c = 100.0 + (3.0 if _i % 2 == 0 else -3.0)
            _rng = 4.0
        elif _i < 65:
            _c = 100.0 + (0.05 if _i % 2 == 0 else -0.05) + (0.2 if _i >= 63 else 0.0)
            _rng = 0.1
        else:
            _c = 118.0
            _rng = 1.0
        _s2_bars.append({
            "open_time": _s1_t0 + _i * 86_400_000,
            "o": 101.0 if _i == 65 else _c,
            "h": _c + _rng,
            "l": 101.0 if _i == 65 else _c - _rng,
            "c": _c, "v": 100.0,
            "close_time": _s1_t0 + (_i + 1) * 86_400_000 - 1, "taker_buy": 50.0,
        })
    _res2 = sleeve2_ttm_squeeze(_s2_bars)
    check("Sleeve #2 3-day squeeze release fires +1 with 2.0x ATR stop",
          _res2.get("status") == "LIVE"
          and _res2["conditions"]["squeeze_release"]
          and _res2["state"]["raw_signal"] == 1
          and _res2["state"]["reference_2x_atr_sl"] < 118.0,
          str((_res2.get("conditions"), _res2.get("state"))))

    _s2_short_sq = _s2_bars[:47] + [_s2_bars[65]]
    _s2_short_sq[-1] = dict(_s2_short_sq[-1], open_time=_s1_t0 + 47 * 86_400_000,
                            close_time=_s1_t0 + 48 * 86_400_000 - 1)
    _res2_short = sleeve2_ttm_squeeze(_s2_short_sq)
    check("Sleeve #2 rejects squeeze release with fewer than 3 squeeze days",
          _res2_short.get("status") == "LIVE" and _res2_short["state"]["raw_signal"] != 1)

    _s2_exit = _s2_bars + [{
        "open_time": _s1_t0 + 66 * 86_400_000, "o": 117.0, "h": 117.0, "l": 90.0, "c": 91.0,
        "v": 100.0, "close_time": _s1_t0 + 67 * 86_400_000 - 1, "taker_buy": 20.0,
    }]
    _res2_exit = sleeve2_ttm_squeeze(_s2_exit)
    check("Sleeve #2 exits (-1) when close drops below SMA(21)",
          _res2_exit.get("status") == "LIVE" and _res2_exit["state"]["raw_signal"] == -1)

    _s2_full_sigs, _, _ = _sleeve2_signals(_s2_bars)
    _s2_cut_sigs, _, _ = _sleeve2_signals(_s2_bars[:60])
    check("Sleeve #2 passes bit-for-bit truncation invariance",
          _s2_cut_sigs == _s2_full_sigs[:60])

    _pm_full = render(dict(full, sleeve1=_res1, sleeve2=_res2))
    _pm_part = render(dict(part, sleeve1=_res1, sleeve2=_res2))
    check("SALAM Pro Max FULL packet renders 3-Verdict sections",
          "SALAM PRO MAX" in _pm_full
          and "3-VERDICT SUMMARY TABLE" in _pm_full
          and "PROJECT F — SLEEVE #1" in _pm_full
          and "PROJECT F — SLEEVE #2" in _pm_full)
    check("SALAM Pro Max PARTIAL keeps Sleeves #1/#2 live while SALAM gate stays suspended",
          "EXECUTION SUSPENDED" in _pm_part
          and "PROJECT F — SLEEVE #1" in _pm_part
          and "PROJECT F — SLEEVE #2" in _pm_part
          and "Execution Rules" not in _pm_part
          and "Binding Arithmetic" not in _pm_part)

    # ── Enhancements #1-#4 checks ──
    check("Sleeve #1 readiness reports 3/3 gates passed on bull breakout and >0 shield distance",
          _res1.get("readiness", {}).get("gates_passed") == 3
          and (_res1.get("readiness", {}).get("shield_dist_pct") or 0) > 0)
    check("Sleeve #1 bear fixture reports <0 shield distance and >0 rally hurdle",
          (_res1_bear.get("readiness", {}).get("shield_dist_pct") or 0) < 0
          and (_res1_bear.get("readiness", {}).get("rally_to_hurdle_pct") or 0) > 0
          and _res1_bear["state"].get("last_transition") is not None)
    _res2_sq = sleeve2_ttm_squeeze(_s2_bars[:64])
    check("Sleeve #2 mid-squeeze reports compression_ratio < 1.0 and >=3d streak",
          _res2_sq.get("status") == "LIVE"
          and (_res2_sq["readiness"]["compression_ratio"] or 9.0) < 1.0
          and _res2_sq["readiness"]["squeeze_streak_days"] >= 3)
    check("Sleeve #2 breakout sets flipped_on_last_bar and 5/5 gates",
          _res2.get("readiness", {}).get("gates_passed") == 5
          and _res2["state"].get("flipped_on_last_bar") is True
          and "Readiness Radar:" in _pm_full
          and "[NEW SIGNAL ON LATEST BAR]" in _pm_full)

    _mw_hw, _rbs_tight = compute_salam_diagnostics({
        "price": 70000.0, "sma200": 90000.0, "atr1h": 300.0,
        "etf": {"five_day_m": -250.0, "one_day_m": -50.0},
        "funding_pct90": 40.0,
        "sup_band": {"low": 68000.0, "high": 69000.0}, "macro_sup": [],
    })
    _mw_tw, _rbs_wide = compute_salam_diagnostics({
        "price": 95000.0, "sma200": 80000.0, "atr1h": 3500.0,
        "etf": {"five_day_m": 400.0, "one_day_m": 120.0},
        "funding_pct90": 35.0,
        "sup_band": None, "macro_sup": [{"center": 90000.0}],
    })
    check("Macro Weather classifies HEADWIND vs TAILWIND cleanly",
          _mw_hw["regime"] == "HEADWIND" and _mw_tw["regime"] == "TAILWIND")
    check("Pre-computed Rail B sizing flags tight ATR cash-cap conflict and passes wide ATR",
          _rbs_tight is not None and _rbs_tight["vetoed_at_50_50"] is True
          and _rbs_tight["vetoed_at_100_usdt"] is True
          and _rbs_wide is not None and _rbs_wide["vetoed_at_50_50"] is False)

    _sc_full = render(dict(full, macro_weather=_mw_hw, rail_b_sizing=_rbs_tight,
                           spot_check={"bin_price": 1000.0, "okx_price": 1000.2,
                                       "spread_pct": 0.02, "ok": True}))
    _sc_part = render(dict(part, macro_weather=_mw_hw, rail_b_sizing=_rbs_tight,
                           spot_check={"bin_price": 1000.0, "okx_price": 1008.0,
                                       "spread_pct": 0.80, "ok": False}))
    check("FULL renders spot cross-check, Macro Weather, and Pre-Computed Sizing Check",
          "spread 0.020% [OK]" in _sc_full
          and "Macro Weather" in _sc_full and "HEADWIND" in _sc_full
          and "Pre-Computed Sizing Check" in _sc_full)
    check("PARTIAL withholds Pre-Computed Sizing Check and Binding Arithmetic even when populated",
          "spread 0.800% [WARN >0.50%]" in _sc_part
          and "Pre-Computed Sizing Check" not in _sc_part
          and "Binding Arithmetic" not in _sc_part
          and "Execution Rules" not in _sc_part)

    print("live")
    try:
        binance = float(get_json(f"{SPOT}/ticker/price?symbol=BTCUSDT")["price"])
        okx = float(get_json(f"{OKX}/api/v5/market/ticker?instId=BTC-USDT")["data"][0]["last"])
        div = abs(binance - okx) / binance * 100
        check("spot BIN vs OKX within 0.50%", div <= 0.5,
              f"{binance:,.1f} vs {okx:,.1f} = {div:.3f}%")
    except Exception as e:                                     # noqa: BLE001
        print(f"  SKIP  spot cross-venue ({type(e).__name__})")

    try:
        oi, err = safe(lambda: float(get_json(
            f"{FAPI}/fapi/v1/openInterest?symbol=BTCUSDT")["openInterest"]), "oi")
        if err:
            oi, err = safe(lambda: float(get_json(
                f"{OKX}/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP"
            )["data"][0]["oiCcy"]), "okx_oi")
        check("open interest > 0", bool(oi) and oi > 0, f"{oi or 0:,.0f} BTC")
    except Exception as e:                                     # noqa: BLE001
        print(f"  SKIP  open interest ({type(e).__name__})")

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 0 if not fails else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Salam Data Packet Protocol v1.0")
    ap.add_argument("--out", default=".", help="output directory (default: current)")
    ap.add_argument("--stdout", action="store_true", help="print instead of writing")
    ap.add_argument("--json", action="store_true", help="also write SALAM_DATA_HUB.json")
    ap.add_argument("--check", action="store_true", help="endpoint health only")
    ap.add_argument("--selftest", action="store_true", help="assert maths + cross-venue agreement")
    ap.add_argument("--manual", default=None,
                    help='screenshot reading, e.g. "perp_cvd=falling,spot_cvd=flat,at=14:32Z" '
                         '— printed verbatim, tagged [MANUAL], never merged into a live field')
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    data, problems = collect()
    if args.check:
        rows = len(data["d1"])
        print(f"closed 1D bars: {rows} | 4H: {len(data['h4'])} | 1H: {len(data['h1'])} | "
              f"perp 1H: {len(data['fh1'])} | price: {data['price']}")
        print("ETF:", data["etf"] if data["etf"] else "UNAVAILABLE")
        for p in problems:
            print("  !", p)
        return 0 if not problems else 1

    a = analyse(data)
    _g = datetime.now(timezone.utc)
    a["generated_at_utc"] = _g.strftime("%Y-%m-%dT%H:%M:%SZ")
    a["generated_at_sgt"] = (_g + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    man, man_ok = parse_manual(args.manual)
    a["manual"], a["manual_ok"], a["manual_at"] = (man or None), man_ok, man.get("at")
    # the JSON carries exec_state too, and the page reads it: the gate must be decided once, here,
    # from BOTH halves — otherwise the markdown says NONE while the JSON says FULL
    if a.get("spot_cvd_ok") and a.get("perp_cvd_ok"):
        a["exec_state"] = "FULL"
    elif a.get("spot_cvd_ok") and man_ok:
        a["exec_state"] = "MANUAL"
    elif a.get("perp_dump"):
        a["exec_state"] = "PARTIAL"
    else:
        a["exec_state"] = "NONE"
    md = render(a)
    if args.stdout:
        sys.stdout.write(md)
    else:
        import pathlib
        out = pathlib.Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        path = out / "SALAM_DATA_HUB.md"
        path.write_text(md, encoding="utf-8")
        print(f"wrote {path}  ({len(md):,} chars)")
        if args.json:
            jp = out / "SALAM_DATA_HUB.json"
            jp.write_text(json.dumps(a, indent=1, default=str), encoding="utf-8")
            print(f"wrote {jp}")
    for p in a.get("problems", []):
        print(f"  ! {p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
