"""Fail-soft News & Macro intelligence engine (CMC Keyless + Verified RSS + Macro Calendar)."""
from __future__ import annotations

import datetime as dt
import email.utils
import html as _html
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

CMC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://coinmarketcap.com/",
    "Origin": "https://coinmarketcap.com",
}

RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}

RSS_SOURCES: list[tuple[str, str, bool]] = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", False),
    ("CoinTelegraph BTC", "https://cointelegraph.com/rss/tag/bitcoin", False),
    ("Decrypt", "https://decrypt.co/feed", False),
    ("CNBC Economy", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258", True),
    ("CNBC Markets", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069", True),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", True),
]

MACRO_RELEVANCE_RE = re.compile(
    r"\b(fed|fomc|powell|cpi|pce|gdp|treasury|yield|yields|inflation|rate|rates|dollar|dxy|"
    r"tariff|tariffs|recession|jobs|payroll|payrolls|unemployment|liquidity|sec|cftc|etf|etfs|"
    r"bitcoin|btc|crypto|stablecoin|stablecoins|oil|gold|debt|bond|bonds|s&p|nasdaq|stocks|equit(?:y|ies))\b",
    re.I,
)

CRYPTO_RELEVANCE_RE = re.compile(
    r"\b(bitcoin|btc|crypto|etf|etfs|blackrock|ibit|fidelity|stablecoin|usdt|usdc|tether|"
    r"fed|fomc|powell|cpi|pce|gdp|treasury|inflation|rates|sec|cftc|coinbase|binance|okx|"
    r"derivatives|futures|options|liquidation|liquidations|miner|miners|halving|whale|spot)\b",
    re.I,
)

FED_NOISE_RE = re.compile(r"\b(fed challenge|college fed|student|contest|winner|winners)\b", re.I)

STOPWORDS = frozenset({
    "the", "a", "an", "to", "of", "in", "on", "for", "as", "at", "by", "is", "are", "was",
    "were", "be", "and", "or", "with", "from", "into", "over", "amid", "after", "says", "said",
    "new", "how", "why", "what", "will", "its", "this", "that", "usd", "nov", "update", "updates",
})


def _clean_text(text: str | None, max_len: int = 0) -> str:
    if not text:
        return ""
    stripped = re.sub(r"<[^>]+>", " ", str(text))
    unescaped = _html.unescape(stripped)
    collapsed = re.sub(r"\s+", " ", unescaped).strip()
    if max_len > 0 and len(collapsed) > max_len:
        return collapsed[: max_len - 1].rstrip() + "…"
    return collapsed


def _parse_any_datetime(raw: Any) -> dt.datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e12:
            ts /= 1000.0
        if ts <= 0:
            return None
        return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
    s = str(raw).strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return _parse_any_datetime(float(s))
    try:
        iso = s[:-1] + "+00:00" if s.endswith("Z") else s
        parsed = dt.datetime.fromisoformat(iso)
        return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(dt.timezone.utc)
    except Exception:
        pass
    try:
        parsed_rfc = email.utils.parsedate_to_datetime(s)
        if parsed_rfc is not None:
            return (
                parsed_rfc.replace(tzinfo=dt.timezone.utc)
                if parsed_rfc.tzinfo is None
                else parsed_rfc.astimezone(dt.timezone.utc)
            )
    except Exception:
        pass
    return None


def _http_get_bytes(url: str, headers: dict[str, str], label: str, errors: list[str], timeout: int = 10) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as exc:
        code = getattr(exc, "code", "")
        errors.append(f"{label}: {type(exc).__name__} {code}".strip())
        return None


def _http_get_json(url: str, headers: dict[str, str], label: str, errors: list[str], timeout: int = 10) -> Any:
    raw = _http_get_bytes(url, headers, label, errors, timeout=timeout)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as exc:
        errors.append(f"{label}: JSONDecodeError {exc}")
        return None


def classify_headline(title: str, summary: str = "", is_macro_feed: bool = False) -> tuple[str, list[str]]:
    """Deterministically assign primary category and secondary catalyst tags."""
    blob = f"{title} {summary}".strip()
    tags: list[str] = []

    is_etf = bool(re.search(r"\b(etf|etfs|ibit|fbtc|gbtc|arkb|blackrock|fidelity|grayscale|inflow|inflows|outflow|outflows)\b", blob, re.I))
    is_fed = bool(re.search(r"\b(fed|fomc|powell|cpi|pce|gdp|payroll|payrolls|unemployment|treasury|yield|yields|inflation|rate cut|rate hike|interest rate|rates|tariff|tariffs|recession|central bank|dollar|dxy)\b", blob, re.I))
    is_reg = bool(re.search(r"\b(sec|cftc|regulat\w+|lawsuit|bill|legislation|congress|senate|ban|tax|mica|treasury dept|doj|stablecoin\s+(?:bill|rule|rules|framework)|stakes?|license)\b", blob, re.I))
    is_deriv = bool(re.search(r"\b(liquidat\w+|short squeeze|long squeeze|funding rate|open interest|futures|perpetual|perp|options|expiry|leverage|whale|whales)\b", blob, re.I))

    if is_etf:
        tags.append("ETF")
    if is_fed or is_macro_feed:
        tags.append("MACRO")
    if is_reg:
        tags.append("REGULATION")
    if is_deriv:
        tags.append("DERIVS")
    if re.search(r"\b(bitcoin|btc|spot)\b", blob, re.I):
        tags.append("BTC")

    if is_etf:
        cat = "BTC_ETF"
    elif is_fed or (is_macro_feed and not is_reg):
        cat = "FED_MACRO"
    elif is_reg:
        cat = "REGULATION"
    elif is_deriv:
        cat = "DERIVS_LIQ"
    else:
        cat = "MARKET_WIRE"

    return cat, tags[:3]


def _title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", title.lower())
    filtered = {w for w in words if w not in STOPWORDS}
    return filtered or set(words)


def deduplicate_headlines(items: list[dict[str, Any]], threshold: float = 0.55) -> list[dict[str, Any]]:
    """Remove near-duplicate headlines using title token Jaccard similarity."""
    kept: list[dict[str, Any]] = []
    kept_tokens: list[set[str]] = []
    kept_urls: set[str] = set()

    for item in items:
        url = (item.get("url") or "").strip().split("?")[0].rstrip("/")
        if url and url in kept_urls:
            continue
        toks = _title_tokens(item.get("title") or "")
        is_dup = False
        for prev in kept_tokens:
            if not toks or not prev:
                continue
            union = toks | prev
            if union and (len(toks & prev) / len(union)) >= threshold:
                is_dup = True
                break
        if is_dup:
            continue
        kept.append(item)
        kept_tokens.append(toks)
        if url:
            kept_urls.add(url)

    return kept


def parse_cmc_news_payload(payload: Any, now_utc: dt.datetime, max_age_hours: int = 168) -> list[dict[str, Any]]:
    """Parse CoinMarketCap content/v3/news JSON payload into normalized headline items."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else row
        lang = str(meta.get("language") or "en").lower()
        if not lang.startswith("en"):
            continue
        title = _clean_text(meta.get("title"), max_len=160)
        url = str(meta.get("sourceUrl") or meta.get("url") or "").strip()
        if not title or not url.startswith("http"):
            continue
        pub_dt = _parse_any_datetime(meta.get("releasedAt") or meta.get("createdAt") or meta.get("updatedAt"))
        if pub_dt is None:
            continue
        age_min = round((now_utc - pub_dt).total_seconds() / 60.0, 1)
        if age_min > max_age_hours * 60.0 or age_min < -60.0:
            continue
        summary = _clean_text(meta.get("subtitle") or meta.get("description") or "", max_len=180)
        src_name = _clean_text(meta.get("sourceName") or "CoinMarketCap") or "CoinMarketCap"
        cat, tags = classify_headline(title, summary, is_macro_feed=False)
        out.append(
            {
                "title": title,
                "summary": summary,
                "url": url,
                "source": src_name,
                "feed": "CMC News",
                "category": cat,
                "tags": tags,
                "published_utc": pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ts_ms": int(pub_dt.timestamp() * 1000),
                "age_minutes": max(0.0, age_min),
                "is_macro_feed": False,
                "priority": 1,
            }
        )
    return out


def _first_elem(node: ET.Element, *tags: str) -> ET.Element | None:
    """Return first matching XML child element without relying on Element truthiness."""
    for tag in tags:
        el = node.find(tag)
        if el is not None:
            return el
    return None


def parse_rss_xml(
    raw_bytes: bytes,
    source_name: str,
    is_macro_feed: bool,
    now_utc: dt.datetime,
    max_age_hours: int = 168,
) -> list[dict[str, Any]]:
    """Parse RSS 2.0 or Atom XML bytes into normalized, relevance-filtered headlines."""
    if not raw_bytes:
        return []
    try:
        root = ET.fromstring(raw_bytes)
    except Exception:
        return []

    atom_ns = "{http://www.w3.org/2005/Atom}"
    dc_date_tag = "{http://purl.org/dc/elements/1.1/}date"
    nodes = root.findall(".//item")
    is_atom = False
    if not nodes:
        nodes = root.findall(f".//{atom_ns}entry")
        is_atom = True

    out: list[dict[str, Any]] = []
    for node in nodes[:30]:
        if is_atom:
            t_el = _first_elem(node, f"{atom_ns}title")
            l_el = _first_elem(node, f"{atom_ns}link")
            d_el = _first_elem(node, f"{atom_ns}updated", f"{atom_ns}published")
            s_el = _first_elem(node, f"{atom_ns}summary", f"{atom_ns}content")
            link = (l_el.attrib.get("href") if l_el is not None else "") or ""
        else:
            t_el = _first_elem(node, "title")
            l_el = _first_elem(node, "link")
            d_el = _first_elem(node, "pubDate", dc_date_tag, "updated")
            s_el = _first_elem(node, "description", "{http://purl.org/rss/1.0/modules/content/}encoded")
            link = (l_el.text if l_el is not None else "") or ""

        title = _clean_text(t_el.text if t_el is not None else "", max_len=160)
        url = link.strip()
        if not title or not url.startswith("http"):
            continue
        pub_dt = _parse_any_datetime(d_el.text if d_el is not None else None)
        if pub_dt is None:
            continue
        age_min = round((now_utc - pub_dt).total_seconds() / 60.0, 1)
        if age_min > max_age_hours * 60.0 or age_min < -60.0:
            continue
        summary = _clean_text(s_el.text if s_el is not None else "", max_len=180)
        blob = f"{title} {summary}"

        if is_macro_feed:
            if "Federal Reserve" in source_name and FED_NOISE_RE.search(blob):
                continue
            if not MACRO_RELEVANCE_RE.search(blob):
                continue
        else:
            if source_name in ("CoinDesk", "Decrypt") and not CRYPTO_RELEVANCE_RE.search(blob):
                continue

        cat, tags = classify_headline(title, summary, is_macro_feed=is_macro_feed)
        out.append(
            {
                "title": title,
                "summary": summary,
                "url": url,
                "source": source_name,
                "feed": source_name,
                "category": cat,
                "tags": tags,
                "published_utc": pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ts_ms": int(pub_dt.timestamp() * 1000),
                "age_minutes": max(0.0, age_min),
                "is_macro_feed": is_macro_feed,
                "priority": 2,
            }
        )
    return out


def fetch_cmc_global_metrics(errors: list[str], ok_list: list[str]) -> dict[str, Any] | None:
    obj = _http_get_json(
        "https://api.coinmarketcap.com/data-api/v3/global-metrics/quotes/latest",
        CMC_HEADERS,
        "CMC Global Metrics",
        errors,
    )
    d = obj.get("data") if isinstance(obj, dict) else None
    if not isinstance(d, dict):
        return None
    q = (d.get("quotes") or [{}])[0] if isinstance(d.get("quotes"), list) else {}
    ok_list.append("CMC Global")
    vol_raw = q.get("totalVolume24H") if q.get("totalVolume24H") is not None else q.get("totalVolume24h")
    return {
        "btc_dominance_pct": round(float(d["btcDominance"]), 2) if d.get("btcDominance") is not None else None,
        "eth_dominance_pct": round(float(d["ethDominance"]), 2) if d.get("ethDominance") is not None else None,
        "total_market_cap_usd": round(float(q["totalMarketCap"]), 0) if q.get("totalMarketCap") is not None else None,
        "total_market_cap_24h_pct": (
            round(float(q["totalMarketCapYesterdayPercentageChange"]), 2)
            if q.get("totalMarketCapYesterdayPercentageChange") is not None
            else None
        ),
        "total_volume_24h_usd": round(float(vol_raw), 0) if vol_raw is not None else None,
    }


def fetch_cmc_fear_greed(now_ts: int, errors: list[str], ok_list: list[str]) -> dict[str, Any] | None:
    start = max(0, now_ts - 30 * 86400)
    obj = _http_get_json(
        f"https://api.coinmarketcap.com/data-api/v3/fear-greed/chart?start={start}&end={now_ts}",
        CMC_HEADERS,
        "CMC Fear & Greed",
        errors,
    )
    d = obj.get("data") if isinstance(obj, dict) else None
    if not isinstance(d, dict):
        return None
    dl = d.get("dataList") or []
    hist = d.get("historicalValues") or {}
    latest = dl[-1] if dl else (hist.get("now") or {})
    if not latest or latest.get("score") is None:
        return None
    ok_list.append("CMC F&G")
    return {
        "score": int(latest["score"]),
        "label": str(latest.get("name") or ""),
        "yesterday_score": (hist.get("yesterday") or {}).get("score"),
        "last_week_score": (hist.get("lastWeek") or {}).get("score"),
        "last_month_score": (hist.get("lastMonth") or {}).get("score"),
        "yearly_high_score": (hist.get("yearlyHigh") or {}).get("score"),
        "yearly_low_score": (hist.get("yearlyLow") or {}).get("score"),
    }


def fetch_cmc_altseason(now_ts: int, errors: list[str], ok_list: list[str]) -> dict[str, Any] | None:
    start = max(0, now_ts - 30 * 86400)
    obj = _http_get_json(
        f"https://api.coinmarketcap.com/data-api/v3/altcoin-season/chart?start={start}&end={now_ts}",
        CMC_HEADERS,
        "CMC AltSeason",
        errors,
    )
    d = obj.get("data") if isinstance(obj, dict) else None
    if not isinstance(d, dict):
        return None
    pts = d.get("points") or []
    if not pts:
        return None
    last = pts[-1]
    if last.get("altcoinIndex") is None:
        return None
    idx = int(float(last["altcoinIndex"]))
    label = "Bitcoin Season" if idx <= 25 else ("Altcoin Season" if idx >= 75 else "Neutral")
    ok_list.append("CMC AltSeason")
    return {
        "index": idx,
        "label": label,
        "altcoin_mcap_usd": round(float(last["altcoinMarketcap"]), 0) if last.get("altcoinMarketcap") is not None else None,
    }


def fetch_cmc_etf_netflow(errors: list[str], ok_list: list[str]) -> dict[str, Any] | None:
    obj = _http_get_json(
        "https://api.coinmarketcap.com/data-api/v3/etf/overview/netflow/chart?category=all&range=30d",
        CMC_HEADERS,
        "CMC ETF Netflow",
        errors,
    )
    d = obj.get("data") if isinstance(obj, dict) else None
    if not isinstance(d, dict):
        return None
    pts = d.get("points") or []
    if not pts:
        return None
    chron = sorted(pts, key=lambda p: int(p.get("timestamp") or 0))
    rows: list[dict[str, Any]] = []
    for p in chron[-5:]:
        dt_obj = _parse_any_datetime(p.get("timestamp"))
        btc_m = round(float(p.get("btcValue") or 0.0) / 1e6, 1)
        eth_m = round(float(p.get("ethValue") or 0.0) / 1e6, 1)
        tot_m = round(float(p.get("value") or 0.0) / 1e6, 1)
        rows.append(
            {
                "date": dt_obj.strftime("%d %b %Y") if dt_obj else str(p.get("timestamp")),
                "btc_usd_m": btc_m,
                "eth_usd_m": eth_m,
                "total_usd_m": tot_m,
            }
        )
    latest = rows[-1]
    ok_list.append("CMC ETF")
    return {
        "latest_date": latest["date"],
        "btc_latest_usd_m": latest["btc_usd_m"],
        "eth_latest_usd_m": latest["eth_usd_m"],
        "total_latest_usd_m": latest["total_usd_m"],
        "btc_5d_sum_usd_m": round(sum(r["btc_usd_m"] for r in rows), 1),
        "eth_5d_sum_usd_m": round(sum(r["eth_usd_m"] for r in rows), 1),
        "last5": rows,
    }


def fetch_usd_calendar_full(now_utc: dt.datetime, errors: list[str], ok_list: list[str]) -> list[dict[str, Any]]:
    """Fetch upcoming USD High & Medium-impact ForexFactory calendar events."""
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    got_any = False

    for idx, url in enumerate((
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
    )):
        if idx == 1:
            tmp_errs: list[str] = []
            r = _http_get_json(url, RSS_HEADERS, "ForexFactory nextweek", tmp_errs, timeout=8)
        else:
            r = _http_get_json(url, RSS_HEADERS, "ForexFactory calendar", errors, timeout=8)
        if not isinstance(r, list):
            continue
        got_any = True
        for ev in r:
            imp = str(ev.get("impact") or "")
            if ev.get("country") != "USD" or imp not in ("High", "Medium"):
                continue
            ev_dt = _parse_any_datetime(ev.get("date"))
            if ev_dt is None:
                continue
            diff_min = (ev_dt - now_utc).total_seconds() / 60.0
            if -60.0 <= diff_min <= 7 * 24 * 60.0:
                key = (str(ev.get("title")), ev_dt.isoformat())
                if key in seen:
                    continue
                seen.add(key)
                imp_up = imp.upper()
                events.append(
                    {
                        "title": str(ev.get("title") or "USD Macro Release"),
                        "impact": imp_up,
                        "time_utc": ev_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "ts_ms": int(ev_dt.timestamp() * 1000),
                        "minutes_away": round(diff_min, 1),
                        "forecast": str(ev.get("forecast") or ""),
                        "previous": str(ev.get("previous") or ""),
                        "blackout_60m": imp_up == "HIGH" and abs(diff_min) <= 60.0,
                    }
                )
    if got_any:
        ok_list.append("ForexFactory USD")
    events.sort(key=lambda x: x["minutes_away"])
    return events[:16]


def compute_macro_bias(
    market: dict[str, Any],
    cmc_etf: dict[str, Any] | None,
    cal: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministically score cross-asset + liquidity backdrop into RISK_ON / MIXED / RISK_OFF."""
    macro = market.get("macro") or {}
    farside = market.get("etf") or {}
    stables = market.get("stables") or {}

    score = 0
    drivers: list[dict[str, Any]] = []

    dxy = macro.get("dxy") or {}
    if isinstance(dxy.get("chg1d_pct"), (int, float)):
        v = float(dxy["chg1d_pct"])
        tone = "bull" if v <= -0.25 else ("bear" if v >= 0.25 else "neutral")
        score += 1 if tone == "bull" else (-1 if tone == "bear" else 0)
        drivers.append({"label": "DXY", "value": f"{dxy.get('value')} ({v:+.2f}% 1D)", "tone": tone})

    us10y = macro.get("us10y") or {}
    if isinstance(us10y.get("chg1d_pct"), (int, float)):
        v = float(us10y["chg1d_pct"])
        tone = "bull" if v <= -1.0 else ("bear" if v >= 1.0 else "neutral")
        score += 1 if tone == "bull" else (-1 if tone == "bear" else 0)
        drivers.append({"label": "US10Y", "value": f"{us10y.get('value')}% ({v:+.2f}% 1D)", "tone": tone})

    vix = macro.get("vix") or {}
    if isinstance(vix.get("value"), (int, float)):
        vx = float(vix["value"])
        vc = float(vix.get("chg1d_pct") or 0.0)
        tone = "bear" if (vx >= 24.0 or vc >= 5.0) else ("bull" if (vx < 18.0 or vc <= -4.0) else "neutral")
        score += 1 if tone == "bull" else (-1 if tone == "bear" else 0)
        drivers.append({"label": "VIX", "value": f"{vx:.2f} ({vc:+.2f}% 1D)", "tone": tone})

    spx = macro.get("spx") or {}
    ndx = macro.get("ndx") or {}
    eq_changes = [float(x["chg1d_pct"]) for x in (spx, ndx) if isinstance(x.get("chg1d_pct"), (int, float))]
    if eq_changes:
        avg_eq = sum(eq_changes) / len(eq_changes)
        tone = "bull" if avg_eq >= 0.4 else ("bear" if avg_eq <= -0.4 else "neutral")
        score += 1 if tone == "bull" else (-1 if tone == "bear" else 0)
        drivers.append({"label": "US Equities", "value": f"Avg {avg_eq:+.2f}% 1D", "tone": tone})

    etf_5d = farside.get("sum5_usd_m")
    if etf_5d is None and cmc_etf:
        etf_5d = cmc_etf.get("btc_5d_sum_usd_m")
    if isinstance(etf_5d, (int, float)):
        e5 = float(etf_5d)
        tone = "bull" if e5 >= 100.0 else ("bear" if e5 <= -100.0 else "neutral")
        score += 1 if tone == "bull" else (-1 if tone == "bear" else 0)
        etf_str = f"-${abs(e5):,.1f}M" if e5 < 0 else f"+${e5:,.1f}M"
        drivers.append({"label": "BTC Spot ETF 5D", "value": etf_str, "tone": tone})

    if isinstance(stables.get("chg7d_pct"), (int, float)):
        s7 = float(stables["chg7d_pct"])
        tone = "bull" if s7 >= 0.5 else ("bear" if s7 <= -0.3 else "neutral")
        score += 1 if tone == "bull" else (-1 if tone == "bear" else 0)
        drivers.append({"label": "USDT+USDC 7D", "value": f"{s7:+.2f}%", "tone": tone})

    status = "RISK_ON" if score >= 2 else ("RISK_OFF" if score <= -2 else "MIXED")
    high_evs = [ev for ev in cal if ev.get("impact") == "HIGH" and float(ev.get("minutes_away", -999)) >= -30.0]
    next_high = high_evs[0] if high_evs else None
    blackout = any(bool(ev.get("blackout_60m")) for ev in cal)

    return {
        "status": status,
        "score": score,
        "max_abs_score": max(1, len(drivers)),
        "blackout_active": blackout,
        "next_high_impact": next_high,
        "drivers": drivers,
    }


def _compact_cross_asset(macro: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("dxy", "us10y", "vix", "spx", "ndx"):
        row = macro.get(key)
        if not isinstance(row, dict):
            out[key] = None
            continue
        out[key] = {
            "value": row.get("value"),
            "chg1d_pct": row.get("chg1d_pct"),
            "roc10_pct": row.get("roc10_pct"),
            "vs_sma20_pct": row.get("vs_sma20_pct"),
            "vs_sma50_pct": row.get("vs_sma50_pct"),
        }
    return out


def _fallback_calendar_from_market(market: dict[str, Any]) -> list[dict[str, Any]]:
    """Reuse already-fetched USD HIGH-impact calendar entries if extended ForexFactory query rate-limits."""
    raw = market.get("macro_calendar")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for ev in raw:
        if not isinstance(ev, dict):
            continue
        mins = ev.get("minutes_away")
        diff_min = float(mins) if isinstance(mins, (int, float)) else 9999.0
        out.append(
            {
                "title": str(ev.get("title") or "USD High Impact"),
                "impact": str(ev.get("impact") or "HIGH").upper(),
                "time_utc": str(ev.get("time_utc") or ""),
                "ts_ms": ev.get("ts_ms"),
                "minutes_away": round(diff_min, 1) if isinstance(mins, (int, float)) else None,
                "forecast": str(ev.get("forecast") or ""),
                "previous": str(ev.get("previous") or ""),
                "blackout_60m": abs(diff_min) <= 60.0,
            }
        )
    return out[:16]


def compute_news_macro(market: dict[str, Any], now_utc: dt.datetime | None = None) -> dict[str, Any]:
    """Assemble live News & Macro desk telemetry from CMC keyless endpoints, RSS feeds, Yahoo, and ForexFactory."""
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    now_ts = int(now.timestamp())
    errors: list[str] = []
    ok_list: list[str] = []

    cmc_global = fetch_cmc_global_metrics(errors, ok_list)
    cmc_fg = fetch_cmc_fear_greed(now_ts, errors, ok_list)
    cmc_alt = fetch_cmc_altseason(now_ts, errors, ok_list)
    cmc_etf = fetch_cmc_etf_netflow(errors, ok_list)
    calendar_usd = fetch_usd_calendar_full(now, errors, ok_list)
    if not calendar_usd:
        fallback_cal = _fallback_calendar_from_market(market)
        if fallback_cal:
            calendar_usd = fallback_cal
            ok_list.append("ForexFactory USD (fallback)")

    all_items: list[dict[str, Any]] = []

    cmc_news_obj = _http_get_json(
        "https://api.coinmarketcap.com/content/v3/news?coins=1&language=en&page=1&size=20",
        CMC_HEADERS,
        "CMC BTC News",
        errors,
    )
    cmc_news = parse_cmc_news_payload(cmc_news_obj, now)
    if cmc_news:
        ok_list.append("CMC News")
        all_items.extend(cmc_news)

    for src_name, url, is_macro in RSS_SOURCES:
        raw_xml = _http_get_bytes(url, RSS_HEADERS, f"RSS {src_name}", errors, timeout=9)
        if not raw_xml:
            continue
        parsed = parse_rss_xml(raw_xml, src_name, is_macro, now)
        ok_list.append(src_name)
        all_items.extend(parsed)

    # Sort newest first (tie-break by CMC priority), deduplicate, and balance macro visibility.
    all_items.sort(key=lambda x: (-int(x.get("ts_ms") or 0), int(x.get("priority") or 9)))
    deduped = deduplicate_headlines(all_items)

    macro_reserved = [x for x in deduped if x.get("category") == "FED_MACRO"][:8]
    reserved_urls = {x["url"] for x in macro_reserved}
    remainder = [x for x in deduped if x["url"] not in reserved_urls]
    combined = (macro_reserved + remainder)[:25]
    combined.sort(key=lambda x: -int(x.get("ts_ms") or 0))

    # Strip internal sort keys before serializing into state.json
    headlines = [
        {
            "title": x["title"],
            "summary": x["summary"],
            "url": x["url"],
            "source": x["source"],
            "category": x["category"],
            "tags": x["tags"],
            "published_utc": x["published_utc"],
            "age_minutes": x["age_minutes"],
        }
        for x in combined
    ]

    counts = {
        "total": len(headlines),
        "BTC_ETF": sum(1 for h in headlines if h["category"] == "BTC_ETF"),
        "FED_MACRO": sum(1 for h in headlines if h["category"] == "FED_MACRO"),
        "DERIVS_LIQ": sum(1 for h in headlines if h["category"] == "DERIVS_LIQ"),
        "REGULATION": sum(1 for h in headlines if h["category"] == "REGULATION"),
        "MARKET_WIRE": sum(1 for h in headlines if h["category"] == "MARKET_WIRE"),
    }

    macro_bias = compute_macro_bias(market, cmc_etf, calendar_usd)
    extras = market.get("extras") or {}

    return {
        "updated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources_ok": ok_list,
        "sources_failed": errors,
        "macro_bias": macro_bias,
        "cross_asset": _compact_cross_asset(market.get("macro") or {}),
        "crypto_pulse": {
            "cmc_global": cmc_global,
            "cmc_fear_greed": cmc_fg,
            "cmc_altseason": cmc_alt,
            "cmc_etf": cmc_etf,
            "farside_etf": market.get("etf"),
            "stables": market.get("stables"),
            "dvol": extras.get("dvol"),
            "alt_fng_value": extras.get("fng_value"),
            "alt_fng_label": extras.get("fng_label"),
        },
        "calendar_usd": calendar_usd,
        "news_counts": counts,
        "headlines": headlines,
    }
