"""Fail-soft multi-source market, derivatives, macro, and calendar fetcher."""
from __future__ import annotations

import datetime as dt
import html as _html
import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

UA = {"User-Agent": "Mozilla/5.0 btc-futures-protocol/1.0"}
OKX_BASE = "https://www.okx.com/api/v5"
BINANCE_VISION = "https://data-api.binance.vision/api/v3"
KRAKEN_FUTURES = "https://futures.kraken.com/derivatives/api/v3"
DERIBIT_PUBLIC = "https://www.deribit.com/api/v2/public"
HYPERLIQUID_INFO = "https://api.hyperliquid.xyz/info"
CMC_DATA_API = "https://api.coinmarketcap.com/data-api/v3"


def _get_json(
    url: str,
    name: str,
    errors: list[str],
    timeout: int = 12,
    headers: dict[str, str] | None = None,
) -> Any:
    try:
        req = urllib.request.Request(url, headers=headers or UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        code = getattr(exc, "code", "")
        errors.append(f"{name}: {type(exc).__name__} {code}".strip())
        return None


def _post_json(url: str, payload: dict[str, Any], name: str, errors: list[str], timeout: int = 12) -> Any:
    try:
        data = json.dumps(payload).encode("utf-8")
        headers = {**UA, "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        code = getattr(exc, "code", "")
        errors.append(f"{name}: {type(exc).__name__} {code}".strip())
        return None


def _get_text(url: str, name: str, errors: list[str], timeout: int = 15) -> str | None:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
                "Accept": "text/html,application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:
        code = getattr(exc, "code", "")
        errors.append(f"{name}: {type(exc).__name__} {code}".strip())
        return None


def _parse_okx_candles(rows: list[list[str]], closed_only: bool = True) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for x in reversed(rows):
        # [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        confirm = x[8] if len(x) > 8 else "1"
        if closed_only and confirm == "0":
            continue
        out.append(
            {
                "ts": int(x[0]),
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
                "volume": float(x[5]),
            }
        )
    return out


def _parse_binance_candles(rows: list[list[Any]], closed_only: bool = True) -> list[dict[str, Any]]:
    items = rows[:-1] if closed_only and len(rows) > 1 else rows
    return [
        {
            "ts": int(x[0]),
            "open": float(x[1]),
            "high": float(x[2]),
            "low": float(x[3]),
            "close": float(x[4]),
            "volume": float(x[5]),
            "taker_buy_volume": float(x[9]) if len(x) > 9 else None,
        }
        for x in items
    ]


def fetch_spot_klines_with_taker(
    interval: str, limit: int, errors: list[str]
) -> list[dict[str, Any]]:
    """Fetch closed spot BTCUSDT klines including taker buy base volume from Binance Vision."""
    r = _get_json(
        f"{BINANCE_VISION}/klines?symbol=BTCUSDT&interval={interval}&limit={min(limit + 1, 1000)}",
        f"BinanceVision spot taker {interval}",
        errors,
    )
    if isinstance(r, list) and len(r) > 5:
        return _parse_binance_candles(r, closed_only=True)
    return []


def fetch_klines(
    symbol_okx: str,
    symbol_binance: str,
    bar_okx: str,
    interval_binance: str,
    limit: int,
    errors: list[str],
) -> tuple[list[dict[str, float]], str]:
    """Fetch closed OHLCV bars from OKX SWAP first, falling back to Binance Vision spot."""
    r = _get_json(
        f"{OKX_BASE}/market/candles?instId={symbol_okx}&bar={bar_okx}&limit={min(limit, 300)}",
        f"OKX {symbol_okx} {bar_okx}",
        errors,
    )
    if r and r.get("data"):
        parsed = _parse_okx_candles(r["data"], closed_only=True)
        if len(parsed) >= 10:
            return parsed, f"OKX {symbol_okx}"

    r2 = _get_json(
        f"{BINANCE_VISION}/klines?symbol={symbol_binance}&interval={interval_binance}&limit={min(limit + 1, 1000)}",
        f"BinanceVision {symbol_binance} {interval_binance}",
        errors,
    )
    if isinstance(r2, list) and len(r2) > 10:
        return _parse_binance_candles(r2, closed_only=True), f"BinanceVision {symbol_binance}"

    return [], "unavailable"


def fetch_live_ticker(errors: list[str]) -> dict[str, Any]:
    """Fetch current BTC perp mark/last price with spot fallback."""
    r = _get_json(f"{OKX_BASE}/market/ticker?instId=BTC-USDT-SWAP", "OKX SWAP ticker", errors)
    if r and r.get("data"):
        d = r["data"][0]
        last = float(d["last"])
        open24 = float(d["open24h"])
        return {
            "price": last,
            "high24": float(d["high24h"]),
            "low24": float(d["low24h"]),
            "chg24_pct": round((last / open24 - 1.0) * 100.0, 2) if open24 else 0.0,
            "source": "OKX BTC-USDT-SWAP",
        }
    r2 = _get_json(f"{BINANCE_VISION}/ticker/24hr?symbol=BTCUSDT", "BinanceVision ticker", errors)
    if r2 and "lastPrice" in r2:
        return {
            "price": float(r2["lastPrice"]),
            "high24": float(r2["highPrice"]),
            "low24": float(r2["lowPrice"]),
            "chg24_pct": float(r2["priceChangePercent"]),
            "source": "BinanceVision BTCUSDT",
        }
    return {"price": None, "source": "unavailable"}


def fetch_funding_and_oi(errors: list[str]) -> dict[str, Any]:
    """Fetch current 8h-equivalent funding rates, 30d history, and open interest across US-accessible venues."""
    out: dict[str, Any] = {
        "current_rate_pct": None,
        "history_pct": [],
        "oi_btc": None,
        "total_oi_btc": None,
        "btc_oi_change_pct_1h": None,
        "btc_oi_change_pct_4h": None,
        "venues": {},
        "venue_oi_btc": {},
    }
    r = _get_json(f"{OKX_BASE}/public/funding-rate?instId=BTC-USDT-SWAP", "OKX funding", errors)
    if r and r.get("data"):
        fr = float(r["data"][0]["fundingRate"]) * 100.0
        out["current_rate_pct"] = round(fr, 5)
        out["venues"]["okx"] = round(fr, 5)

    rh = _get_json(f"{OKX_BASE}/public/funding-rate-history?instId=BTC-USDT-SWAP&limit=90", "OKX funding hist", errors)
    if rh and rh.get("data"):
        # ordered newest first -> reverse to chronological
        out["history_pct"] = [round(float(x["fundingRate"]) * 100.0, 5) for x in reversed(rh["data"])]

    roi = _get_json(f"{OKX_BASE}/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP", "OKX OI", errors)
    if roi and roi.get("data"):
        okx_oi = round(float(roi["data"][0]["oiCcy"]), 1)
        out["oi_btc"] = okx_oi
        out["venue_oi_btc"]["okx"] = okx_oi

    # Kraken Futures PF_XBTUSD (fundingRate is 1h USD/BTC; divide by markPrice -> 1h rel rate, x8x100 -> 8h %)
    kf = _get_json(f"{KRAKEN_FUTURES}/tickers", "Kraken Futures ticker", errors)
    if kf and isinstance(kf.get("tickers"), list):
        pf = next((t for t in kf["tickers"] if t.get("symbol") == "PF_XBTUSD"), None)
        if pf:
            mark = float(pf.get("markPrice") or pf.get("last") or 0.0)
            if mark > 0 and pf.get("fundingRate") is not None:
                kfr = round((float(pf["fundingRate"]) / mark) * 8.0 * 100.0, 5)
                out["venues"]["kraken_futures"] = kfr
            if pf.get("openInterest") is not None:
                out["venue_oi_btc"]["kraken_futures"] = round(float(pf["openInterest"]), 1)

    # Deribit BTC-PERPETUAL (funding_8h decimal fraction, open_interest in USD inverse)
    db = _get_json(f"{DERIBIT_PUBLIC}/get_book_summary_by_currency?currency=BTC&kind=future", "Deribit perp", errors)
    if db and isinstance(db.get("result"), list):
        perp = next((x for x in db["result"] if x.get("instrument_name") == "BTC-PERPETUAL"), None)
        if perp:
            if perp.get("funding_8h") is not None:
                out["venues"]["deribit"] = round(float(perp["funding_8h"]) * 100.0, 5)
            mark = float(perp.get("mark_price") or perp.get("last") or 0.0)
            if mark > 0 and perp.get("open_interest") is not None:
                out["venue_oi_btc"]["deribit"] = round(float(perp["open_interest"]) / mark, 1)

    # Hyperliquid BTC perp (funding is 1h decimal fraction, openInterest in BTC)
    hl = _post_json(HYPERLIQUID_INFO, {"type": "metaAndAssetCtxs"}, "Hyperliquid perp", errors)
    if isinstance(hl, list) and len(hl) >= 2:
        universe = (hl[0] or {}).get("universe") or []
        ctxs = hl[1] or []
        idx = next((i for i, u in enumerate(universe) if u.get("name") == "BTC"), None)
        if idx is not None and idx < len(ctxs):
            ctx = ctxs[idx] or {}
            if ctx.get("funding") is not None:
                out["venues"]["hyperliquid"] = round(float(ctx["funding"]) * 8.0 * 100.0, 5)
            if ctx.get("openInterest") is not None:
                out["venue_oi_btc"]["hyperliquid"] = round(float(ctx["openInterest"]), 1)

    if out["current_rate_pct"] is None and out["venues"]:
        vals = sorted(out["venues"].values())
        out["current_rate_pct"] = vals[len(vals) // 2]

    if out["venue_oi_btc"]:
        tot = round(sum(out["venue_oi_btc"].values()), 1)
        out["total_oi_btc"] = tot
        if out["oi_btc"] is None:
            out["oi_btc"] = tot

    # Soft-probe OKX 1H BTC open-interest history for Rulebook 3.2 (1H / 4H OI change %)
    soft_errs: list[str] = []
    oi_hist = _get_json(
        f"{OKX_BASE}/rubik/stat/contracts/open-interest-history?instId=BTC-USDT-SWAP&period=1H&limit=6",
        "OKX OI history",
        soft_errs,
    )
    if oi_hist and isinstance(oi_hist.get("data"), list) and len(oi_hist["data"]) >= 2:
        try:
            chron = sorted(oi_hist["data"], key=lambda row: int(row[0]))
            latest_oi = float(chron[-1][2])
            prev_1h_oi = float(chron[-2][2])
            if prev_1h_oi > 0:
                out["btc_oi_change_pct_1h"] = round((latest_oi / prev_1h_oi - 1.0) * 100.0, 2)
            if len(chron) >= 5:
                prev_4h_oi = float(chron[-5][2])
                if prev_4h_oi > 0:
                    out["btc_oi_change_pct_4h"] = round((latest_oi / prev_4h_oi - 1.0) * 100.0, 2)
        except Exception:
            pass

    return out


def fetch_orderbook_imbalance(errors: list[str]) -> dict[str, Any]:
    """Fetch top L2 depth within +-1% of mid-price, bid/ask ratio, and spread bps."""
    empty = {
        "bid_depth_1pct_usd": None,
        "ask_depth_1pct_usd": None,
        "imbalance_ratio": None,
        "imbalance_pct": None,
        "spread_bps": None,
        "source": "unavailable",
    }

    def _compute(
        bids: list[Any],
        asks: list[Any],
        contract_mult: float,
        source_name: str,
    ) -> dict[str, Any] | None:
        if not bids or not asks:
            return None
        try:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
                return None
            mid = (best_bid + best_ask) / 2.0
            spread_bps = round(((best_ask - best_bid) / mid) * 10000.0, 4)
            bid_floor = mid * 0.99
            ask_ceil = mid * 1.01
            bid_usd = 0.0
            for row in bids:
                px = float(row[0])
                if px < bid_floor:
                    break
                bid_usd += px * float(row[1]) * contract_mult
            ask_usd = 0.0
            for row in asks:
                px = float(row[0])
                if px > ask_ceil:
                    break
                ask_usd += px * float(row[1]) * contract_mult
            tot = bid_usd + ask_usd
            ratio = round(bid_usd / ask_usd, 2) if ask_usd > 0 else None
            imb_pct = round(((bid_usd - ask_usd) / tot) * 100.0, 1) if tot > 0 else None
            return {
                "bid_depth_1pct_usd": round(bid_usd, 0),
                "ask_depth_1pct_usd": round(ask_usd, 0),
                "imbalance_ratio": ratio,
                "imbalance_pct": imb_pct,
                "spread_bps": spread_bps,
                "source": source_name,
            }
        except Exception:
            return None

    ob = _get_json(f"{OKX_BASE}/market/books?instId=BTC-USDT-SWAP&sz=400", "OKX L2 book", errors)
    if ob and ob.get("data"):
        row = ob["data"][0]
        res = _compute(row.get("bids") or [], row.get("asks") or [], 0.01, "OKX BTC-USDT-SWAP")
        if res is not None:
            return res

    bz = _get_json(f"{BINANCE_VISION}/depth?symbol=BTCUSDT&limit=500", "BinanceVision L2 book", errors)
    if bz and isinstance(bz, dict):
        res = _compute(bz.get("bids") or [], bz.get("asks") or [], 1.0, "BinanceVision BTCUSDT")
        if res is not None:
            return res

    return empty


def fetch_cmc_liquidations(errors: list[str]) -> dict[str, Any] | None:
    """Fetch keyless CoinMarketCap BTC Liquidation Map ($50 bins) and 4H/24H Realized Liquidations."""
    cmc_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
        "Accept": "application/json",
    }

    def _fmt_bucket(b: dict[str, Any], mark: float) -> dict[str, Any]:
        p0 = float(b.get("price") or 0.0)
        p1 = float(b.get("endPrice") or p0)
        mid = round((p0 + p1) / 2.0, 1)
        amt_m = round(float(b.get("amount") or 0.0) / 1e6, 2)
        dist_pct = round(((mid - mark) / mark) * 100.0, 2) if mark > 0 else 0.0
        return {
            "price": mid,
            "range": [round(p0, 1), round(p1, 1)],
            "usd_m": amt_m,
            "leverage": b.get("leverage"),
            "distance_pct": dist_pct,
        }

    out: dict[str, Any] = {"source": "CoinMarketCap (Hyperliquid Exact Map + Multi-Exchange Realized)"}

    rm = _get_json(
        f"{CMC_DATA_API}/liquidations/map/latest?exchangeId=8112&baseId=1&scope=token&convertId=2781",
        "CMC liquidation map",
        errors,
        headers=cmc_headers,
    )
    if rm and isinstance(rm.get("data"), dict):
        d = rm["data"]
        mark = float(d.get("mark") or 0.0)
        long_buckets = d.get("longBuckets") or []
        short_buckets = d.get("shortBuckets") or []
        if mark > 0 and (long_buckets or short_buckets):
            total_long_below_m = round(float(long_buckets[-1].get("cumulative") or 0.0) / 1e6, 2) if long_buckets else 0.0
            total_short_above_m = round(float(short_buckets[-1].get("cumulative") or 0.0) / 1e6, 2) if short_buckets else 0.0
            longs_2pct_m = round(
                sum(float(b.get("amount") or 0.0) for b in long_buckets if float(b.get("price") or 0.0) >= mark * 0.98) / 1e6,
                2,
            )
            shorts_2pct_m = round(
                sum(float(b.get("amount") or 0.0) for b in short_buckets if float(b.get("endPrice") or b.get("price") or 0.0) <= mark * 1.02) / 1e6,
                2,
            )
            longs_5pct_m = round(
                sum(float(b.get("amount") or 0.0) for b in long_buckets if float(b.get("price") or 0.0) >= mark * 0.95) / 1e6,
                2,
            )
            shorts_5pct_m = round(
                sum(float(b.get("amount") or 0.0) for b in short_buckets if float(b.get("endPrice") or b.get("price") or 0.0) <= mark * 1.05) / 1e6,
                2,
            )
            squeeze_bias = (
                "SHORT_SQUEEZE_HEAVY"
                if shorts_2pct_m > longs_2pct_m * 1.15
                else ("LONG_FLUSH_HEAVY" if longs_2pct_m > shorts_2pct_m * 1.15 else "BALANCED")
            )
            tac_longs = sorted(
                [b for b in long_buckets if float(b.get("price") or 0.0) >= mark * 0.92],
                key=lambda b: float(b.get("amount") or 0.0),
                reverse=True,
            )[:3]
            tac_shorts = sorted(
                [b for b in short_buckets if float(b.get("endPrice") or b.get("price") or 0.0) <= mark * 1.08],
                key=lambda b: float(b.get("amount") or 0.0),
                reverse=True,
            )[:3]
            macro_long = max(long_buckets, key=lambda b: float(b.get("amount") or 0.0), default=None)
            macro_short = max(short_buckets, key=lambda b: float(b.get("amount") or 0.0), default=None)

            out["mark_price"] = round(mark, 1)
            out["cumulative_fuel"] = {
                "total_long_below_usd_m": total_long_below_m,
                "total_short_above_usd_m": total_short_above_m,
                "longs_within_2pct_usd_m": longs_2pct_m,
                "shorts_within_2pct_usd_m": shorts_2pct_m,
                "longs_within_5pct_usd_m": longs_5pct_m,
                "shorts_within_5pct_usd_m": shorts_5pct_m,
                "squeeze_bias_2pct": squeeze_bias,
            }
            out["tactical_long_clusters_within_8pct"] = [_fmt_bucket(b, mark) for b in tac_longs]
            out["tactical_short_clusters_within_8pct"] = [_fmt_bucket(b, mark) for b in tac_shorts]
            out["largest_macro_long_cluster"] = _fmt_bucket(macro_long, mark) if macro_long else None
            out["largest_macro_short_cluster"] = _fmt_bucket(macro_short, mark) if macro_short else None

    r4 = _get_json(
        f"{CMC_DATA_API}/liquidations/table?page=1&pageSize=25&sort=totalLiquidations4h&ascendingOrder=false&interval=4h",
        "CMC 4h liquidations",
        errors,
        headers=cmc_headers,
    )
    r24 = _get_json(
        f"{CMC_DATA_API}/liquidations/table?page=1&pageSize=25&sort=totalLiquidations1d&ascendingOrder=false&interval=1d",
        "CMC 24h liquidations",
        errors,
        headers=cmc_headers,
    )
    items4 = ((r4 or {}).get("data") or {}).get("items") or []
    items24 = ((r24 or {}).get("data") or {}).get("items") or []
    btc4 = next((x for x in items4 if x.get("symbol") == "BTC" or x.get("coinId") == 1), None)
    btc24 = next((x for x in items24 if x.get("symbol") == "BTC" or x.get("coinId") == 1), None)
    if btc4 or btc24:
        b4 = btc4 or {}
        b24 = btc24 or {}
        oi_usd = float(b24.get("openInterestUsd") or b4.get("openInterestUsd") or 0.0)
        tot4 = float(b4.get("totalLiquidations") or 0.0)
        tot24 = float(b24.get("totalLiquidations") or 0.0)
        out["realized"] = {
            "h4_long_usd_m": round(float(b4.get("longLiquidations") or 0.0) / 1e6, 2),
            "h4_short_usd_m": round(float(b4.get("shortLiquidations") or 0.0) / 1e6, 2),
            "h4_total_usd_m": round(tot4 / 1e6, 2),
            "h4_long_flush_pct": round((float(b4.get("longLiquidations") or 0.0) / tot4) * 100.0, 1) if tot4 > 0 else 0.0,
            "h24_long_usd_m": round(float(b24.get("longLiquidations") or 0.0) / 1e6, 2),
            "h24_short_usd_m": round(float(b24.get("shortLiquidations") or 0.0) / 1e6, 2),
            "h24_total_usd_m": round(tot24 / 1e6, 2),
            "h24_long_flush_pct": round((float(b24.get("longLiquidations") or 0.0) / tot24) * 100.0, 1) if tot24 > 0 else 0.0,
            "global_btc_oi_usd_b": round(oi_usd / 1e9, 2),
        }

    return out if len(out) > 1 else None


def fetch_macro(errors: list[str]) -> dict[str, Any]:
    """Fetch 3-month daily series from Yahoo Finance for VIX, DXY, US10Y, SPX, NDX."""
    symbols = [
        ("vix", "^VIX"),
        ("dxy", "DX-Y.NYB"),
        ("us10y", "^TNX"),
        ("spx", "^GSPC"),
        ("ndx", "^IXIC"),
    ]
    out: dict[str, Any] = {}
    for key, sym in symbols:
        r = _get_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=3mo&interval=1d",
            f"Yahoo {sym}",
            errors,
        )
        try:
            q = r["chart"]["result"][0]
            closes = [float(c) for c in q["indicators"]["quote"][0]["close"] if c is not None]
            if len(closes) >= 20:
                sma20 = sum(closes[-20:]) / 20.0
                sma50 = sum(closes[-50:]) / 50.0 if len(closes) >= 50 else None
                last = closes[-1]
                prev = closes[-2]
                roc10 = (last / closes[-11] - 1.0) * 100.0 if len(closes) > 11 else 0.0
                out[key] = {
                    "value": round(last, 2),
                    "chg1d_pct": round((last / prev - 1.0) * 100.0, 2),
                    "roc10_pct": round(roc10, 2),
                    "vs_sma20_pct": round((last / sma20 - 1.0) * 100.0, 2),
                    "vs_sma50_pct": round((last / sma50 - 1.0) * 100.0, 2) if sma50 else None,
                    "closes": closes[-30:],
                }
        except Exception:
            pass
    return out


def fetch_etf_flows(errors: list[str]) -> dict[str, Any] | None:
    """Parse Farside daily BTC Spot ETF flows."""
    s = _get_text("https://farside.co.uk/btc/", "Farside ETF", errors, timeout=20)
    if not s:
        return None
    try:
        rows = [
            [_html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
            for r in re.findall(r"<tr[^>]*>(.*?)</tr>", s, re.S)
        ]
        hdr = next((r for r in rows if "IBIT" in r), None)
        num = lambda t: None if t in ("", "-") else -float(t.strip("()").replace(",", "")) if t.startswith("(") else float(t.replace(",", ""))
        days = [r for r in rows if r and re.match(r"\d{2} \w{3} \d{4}$", r[0]) and len(r) >= 3]
        days = [r for r in days if num(r[-1]) is not None]
        if not days or not hdr:
            return None
        last = days[-1]
        last5 = [[d[0], num(d[-1])] for d in days[-5:]]
        return {
            "latest_date": last[0],
            "latest_usd_m": num(last[-1]),
            "sum5_usd_m": round(sum(x[1] for x in last5 if x[1] is not None), 1),
            "last5": last5,
        }
    except Exception as exc:
        errors.append(f"Farside parse: {exc}")
        return None


def fetch_stablecoins(errors: list[str]) -> dict[str, Any] | None:
    """Fetch USDT + USDC 7d circulating supply change from DefiLlama."""
    r = _get_json("https://stablecoins.llama.fi/stablecoins?includePrices=false", "DefiLlama stablecoins", errors)
    if not r:
        return None
    now_tot = 0.0
    prev_tot = 0.0
    for asset in r.get("peggedAssets", []):
        if asset.get("symbol") in ("USDT", "USDC"):
            cur = (asset.get("circulating") or {}).get("peggedUSD")
            wk = (asset.get("circulatingPrevWeek") or {}).get("peggedUSD")
            if cur and wk:
                now_tot += float(cur)
                prev_tot += float(wk)
    if prev_tot <= 0:
        return None
    return {
        "total_usd_b": round(now_tot / 1e9, 2),
        "chg7d_pct": round((now_tot / prev_tot - 1.0) * 100.0, 2),
    }


def fetch_dvol_and_fng(errors: list[str]) -> dict[str, Any]:
    """Fetch Deribit DVOL and Alternative.me Fear & Greed."""
    out: dict[str, Any] = {}
    now_ms = int(time.time() * 1000)
    dv = _get_json(
        f"https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&resolution=3600&start_timestamp={now_ms - 6 * 3600000}&end_timestamp={now_ms}",
        "Deribit DVOL",
        errors,
    )
    if dv and (dv.get("result") or {}).get("data"):
        out["dvol"] = round(float(dv["result"]["data"][-1][4]), 2)

    fg = _get_json("https://api.alternative.me/fng/?limit=1", "Fear & Greed", errors)
    if fg and fg.get("data"):
        out["fng_value"] = int(fg["data"][0]["value"])
        out["fng_label"] = fg["data"][0]["value_classification"]
    return out


def fetch_macro_calendar(errors: list[str]) -> list[dict[str, Any]]:
    """Fetch upcoming USD High-Impact macro events from Forex Factory for ±30m blackout checks."""
    now = dt.datetime.now(dt.timezone.utc)
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for idx, url in enumerate((
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
    )):
        if idx == 1:
            # nextweek.json frequently 404s until Sunday/Monday; probe silently
            tmp_errs: list[str] = []
            r = _get_json(url, "ForexFactory nextweek", tmp_errs)
        else:
            r = _get_json(url, "ForexFactory calendar", errors)
        if not isinstance(r, list):
            continue
        for ev in r:
            if ev.get("country") != "USD" or ev.get("impact") != "High":
                continue
            try:
                ev_dt = dt.datetime.fromisoformat(ev["date"]).astimezone(dt.timezone.utc)
            except Exception:
                continue
            diff_min = (ev_dt - now).total_seconds() / 60.0
            if -60.0 <= diff_min <= 7 * 24 * 60.0:
                key = (str(ev.get("title")), ev_dt.isoformat())
                if key in seen:
                    continue
                seen.add(key)
                events.append(
                    {
                        "title": ev.get("title", "USD High Impact"),
                        "time_utc": ev_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "ts_ms": int(ev_dt.timestamp() * 1000),
                        "minutes_away": round(diff_min, 1),
                        "forecast": ev.get("forecast") or "",
                        "previous": ev.get("previous") or "",
                    }
                )
    events.sort(key=lambda x: x["minutes_away"])
    return events[:12]


def fetch_all_market_data() -> dict[str, Any]:
    """Collect full market snapshot needed for regime analysis, signals, and paper ledger."""
    errors: list[str] = []
    now_utc = dt.datetime.now(dt.timezone.utc)
    ticker = fetch_live_ticker(errors)
    d1, d1_src = fetch_klines("BTC-USDT-SWAP", "BTCUSDT", "1Dutc", "1d", 265, errors)
    h4, h4_src = fetch_klines("BTC-USDT-SWAP", "BTCUSDT", "4H", "4h", 200, errors)
    h1, h1_src = fetch_klines("BTC-USDT-SWAP", "BTCUSDT", "1H", "1h", 168, errors)
    m15, m15_src = fetch_klines("BTC-USDT-SWAP", "BTCUSDT", "15m", "15m", 120, errors)
    spot_h1 = fetch_spot_klines_with_taker("1h", 120, errors)
    spot_h4 = fetch_spot_klines_with_taker("4h", 90, errors)
    eth_d1, _ = fetch_klines("ETH-USDT-SWAP", "ETHUSDT", "1Dutc", "1d", 40, errors)

    if ticker.get("price") is None and h1:
        ticker["price"] = h1[-1]["close"]
        ticker["source"] = f"Fallback {h1_src} last close"

    funding = fetch_funding_and_oi(errors)
    funding["orderbook_1pct"] = fetch_orderbook_imbalance(errors)
    funding["cmc_liquidations"] = fetch_cmc_liquidations(errors)
    macro = fetch_macro(errors)
    etf = fetch_etf_flows(errors)
    stables = fetch_stablecoins(errors)
    extras = fetch_dvol_and_fng(errors)
    calendar = fetch_macro_calendar(errors)

    return {
        "fetched_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at_ms": int(now_utc.timestamp() * 1000),
        "ticker": ticker,
        "klines": {
            "1d": d1,
            "4h": h4,
            "1h": h1,
            "15m": m15,
            "spot_1h": spot_h1,
            "spot_4h": spot_h4,
            "eth_1d": eth_d1,
            "sources": {"1d": d1_src, "4h": h4_src, "1h": h1_src, "15m": m15_src},
        },
        "derivatives": funding,
        "macro": macro,
        "etf": etf,
        "stables": stables,
        "extras": extras,
        "macro_calendar": calendar,
        "fetch_errors": errors,
    }
