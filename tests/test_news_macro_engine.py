"""Unit tests for News & Macro keyless aggregation, classification, and risk scoring."""
from __future__ import annotations

import datetime as dt
import unittest
import urllib.error
from unittest.mock import patch

from engine.news_macro_engine import (
    classify_headline,
    compute_macro_bias,
    compute_news_macro,
    deduplicate_headlines,
    parse_cmc_news_payload,
    parse_rss_xml,
)


class TestNewsMacroEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.now = dt.datetime(2026, 11, 24, 13, 30, tzinfo=dt.timezone.utc)

    def test_classify_headline_buckets(self) -> None:
        c1, t1 = classify_headline("BlackRock IBIT sees $569M Spot Bitcoin ETF outflow")
        self.assertEqual(c1, "BTC_ETF")
        self.assertIn("ETF", t1)

        c2, t2 = classify_headline("Powell signals caution ahead of Core PCE inflation report", is_macro_feed=True)
        self.assertEqual(c2, "FED_MACRO")
        self.assertIn("MACRO", t2)

        c3, _ = classify_headline("South Korea lawmakers limit crypto exchange stakes to 20% under new bill")
        self.assertEqual(c3, "REGULATION")

        c4, _ = classify_headline("$310M short squeeze hits Bitcoin perpetual futures as funding flips")
        self.assertEqual(c4, "DERIVS_LIQ")

        c5, _ = classify_headline("Bitcoin trades near $60,000 in quiet Asia session")
        self.assertEqual(c5, "MARKET_WIRE")

    def test_parse_cmc_news_filters_language_and_unescapes(self) -> None:
        payload = {
            "data": [
                {
                    "meta": {
                        "language": "en",
                        "title": "Bitcoin &amp; Spot ETF Flows Cool Ahead of Core PCE",
                        "subtitle": "<p>ETF outflows weigh on risk appetite.</p>",
                        "sourceName": "CoinDesk",
                        "sourceUrl": "https://www.coindesk.com/example-1",
                        "releasedAt": "2026-11-24T12:45:00.000Z",
                    }
                },
                {
                    "meta": {
                        "language": "tr",
                        "title": "Analistler Bitcoin icin 2 Seviyeye Dikkat Cekti",
                        "sourceName": "CoinMuhendisi",
                        "sourceUrl": "https://coinmarketcap.com/community/articles/tr-1",
                        "releasedAt": "2026-11-24T12:30:00.000Z",
                    }
                },
            ]
        }
        items = parse_cmc_news_payload(payload, self.now)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Bitcoin & Spot ETF Flows Cool Ahead of Core PCE")
        self.assertEqual(items[0]["summary"], "ETF outflows weigh on risk appetite.")
        self.assertEqual(items[0]["category"], "BTC_ETF")
        self.assertEqual(items[0]["age_minutes"], 45.0)

    def test_parse_rss_and_atom_relevance_filters(self) -> None:
        rss = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
          <item>
            <title>Fed keeps rates steady as Core PCE holds above target</title>
            <link>https://example.com/fed-1</link>
            <pubDate>Tue, 24 Nov 2026 12:00:00 GMT</pubDate>
            <description>FOMC officials monitor inflation trajectory.</description>
          </item>
          <item>
            <title>Federal Reserve announces College Fed Challenge winners</title>
            <link>https://example.com/fed-student</link>
            <pubDate>Tue, 24 Nov 2026 11:00:00 GMT</pubDate>
            <description>Student economics competition results.</description>
          </item>
        </channel></rss>"""
        macro_items = parse_rss_xml(rss, "Federal Reserve", is_macro_feed=True, now_utc=self.now)
        self.assertEqual(len(macro_items), 1)
        self.assertEqual(macro_items[0]["category"], "FED_MACRO")

        atom = b"""<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Bitcoin pulls back to $60k ahead of US GDP data</title>
            <link href="https://example.com/atom-btc"/>
            <updated>2026-11-24T13:00:00Z</updated>
            <summary>Spot buyers step back before macro releases.</summary>
          </entry>
        </feed>"""
        atom_items = parse_rss_xml(atom, "CoinDesk", is_macro_feed=False, now_utc=self.now)
        self.assertEqual(len(atom_items), 1)
        self.assertEqual(atom_items[0]["url"], "https://example.com/atom-btc")

    def test_deduplicate_headlines_jaccard(self) -> None:
        items = [
            {
                "title": "Live updates: Bitcoin pulls back to $60,000 as stock rally fails to budge crypto",
                "url": "https://coindesk.com/1",
            },
            {
                "title": "Bitcoin pulls back to $60,000 while stock rally fails to budge crypto markets",
                "url": "https://cmc.com/mirror-1",
            },
            {
                "title": "Core PCE inflation data arrives Wednesday alongside US GDP revision",
                "url": "https://cnbc.com/pce",
            },
        ]
        deduped = deduplicate_headlines(items)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0]["url"], "https://coindesk.com/1")
        self.assertEqual(deduped[1]["url"], "https://cnbc.com/pce")

    def test_compute_macro_bias_risk_off_vs_risk_on_and_blackout(self) -> None:
        risk_off_market = {
            "macro": {
                "dxy": {"value": 107.2, "chg1d_pct": 0.45},
                "us10y": {"value": 4.48, "chg1d_pct": 1.6},
                "vix": {"value": 25.4, "chg1d_pct": 6.2},
                "spx": {"value": 5820.0, "chg1d_pct": -0.8},
                "ndx": {"value": 20100.0, "chg1d_pct": -1.1},
            },
            "etf": {"sum5_usd_m": -450.0},
            "stables": {"chg7d_pct": -0.5},
        }
        cal = [{"title": "Core PCE Price Index m/m", "impact": "HIGH", "minutes_away": 35.0, "blackout_60m": True}]
        res_off = compute_macro_bias(risk_off_market, None, cal)
        self.assertEqual(res_off["status"], "RISK_OFF")
        self.assertTrue(res_off["blackout_active"])
        self.assertEqual(res_off["next_high_impact"]["title"], "Core PCE Price Index m/m")

        risk_on_market = {
            "macro": {
                "dxy": {"value": 103.5, "chg1d_pct": -0.45},
                "us10y": {"value": 4.02, "chg1d_pct": -1.5},
                "vix": {"value": 14.2, "chg1d_pct": -5.0},
                "spx": {"value": 6050.0, "chg1d_pct": 0.75},
                "ndx": {"value": 21200.0, "chg1d_pct": 1.1},
            },
            "etf": {"sum5_usd_m": 620.0},
            "stables": {"chg7d_pct": 1.25},
        }
        res_on = compute_macro_bias(risk_on_market, None, [])
        self.assertEqual(res_on["status"], "RISK_ON")
        self.assertFalse(res_on["blackout_active"])

    def test_compute_news_macro_fail_soft(self) -> None:
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            res = compute_news_macro({"macro": {}, "extras": {}}, now_utc=self.now)
        self.assertEqual(res["headlines"], [])
        self.assertEqual(res["calendar_usd"], [])
        self.assertEqual(res["macro_bias"]["status"], "MIXED")
        self.assertEqual(res["sources_ok"], [])
        self.assertGreater(len(res["sources_failed"]), 0)


if __name__ == "__main__":
    unittest.main()
