"""Unit tests for Multi-Timeframe S/R Bands & Liquidation Magnet Overlap Engine."""
from __future__ import annotations

import datetime as dt
import math
import unittest

from engine.sr_bands_engine import (
    compute_confluence_zones,
    compute_magnet_overlaps,
    compute_sr_bands,
    compute_tf_sr_bands,
)


def _make_wave_bars(count: int, step_ms: int, base: float = 60000.0, amp: float = 1800.0) -> list[dict]:
    start_ts = 1790000000000
    bars = []
    for i in range(count):
        wave = amp * math.sin(i * 0.45)
        o = base + wave
        c = base + amp * math.sin((i + 0.5) * 0.45)
        hi = max(o, c) + 250.0
        lo = min(o, c) - 250.0
        bars.append({
            "ts": start_ts + i * step_ms,
            "open": round(o, 1),
            "high": round(hi, 1),
            "low": round(lo, 1),
            "close": round(c, 1),
            "volume": 1200.0,
        })
    return bars


class TestSrBandsEngine(unittest.TestCase):
    def test_tf_bands_extracts_support_and_resistance_with_atr_padding(self) -> None:
        bars = _make_wave_bars(80, 4 * 3600 * 1000, base=60000.0, amp=1800.0)
        res = compute_tf_sr_bands(bars, ref_price=60000.0, tf_label="4H", role="Core Swing")
        self.assertEqual(res["tf"], "4H")
        self.assertGreater(res["atr14_usd"], 0)
        self.assertTrue(len(res["resistance"]) >= 1)
        self.assertTrue(len(res["support"]) >= 1)
        for z in res["resistance"]:
            self.assertGreaterEqual(z["mid"], 60000.0)
            self.assertLessEqual(z["low"], z["mid"])
            self.assertGreaterEqual(z["high"], z["mid"])
        for z in res["support"]:
            self.assertLess(z["mid"], 60000.0)

    def test_weekly_fallback_from_daily_and_confluence(self) -> None:
        d1 = _make_wave_bars(120, 24 * 3600 * 1000, base=60000.0, amp=2200.0)
        h4 = _make_wave_bars(100, 4 * 3600 * 1000, base=60000.0, amp=1600.0)
        h1 = _make_wave_bars(100, 3600 * 1000, base=60000.0, amp=900.0)
        m15 = _make_wave_bars(96, 15 * 60 * 1000, base=60000.0, amp=400.0)
        market = {
            "ticker": {"price": 60000.0},
            "klines": {"1w": [], "1d": d1, "4h": h4, "1h": h1, "15m": m15},
            "derivatives": {
                "cmc_liquidations": {
                    "tactical_long_clusters_within_8pct": [
                        {"price": 57600.0, "usd_m": 42.0, "leverage": 20, "distance_pct": -4.0}
                    ],
                    "tactical_short_clusters_within_8pct": [],
                }
            },
        }
        out = compute_sr_bands(market, spot_magnet=None, now_utc=dt.datetime(2026, 11, 25, 2, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(out["status"], "LIVE")
        self.assertGreaterEqual(out["timeframes"]["1W"]["bars"], 10)
        self.assertEqual(out["core_order"], ["1W", "1D", "4H", "1H"])
        self.assertIn("12H", out["intraday_snapshot"])
        self.assertIn("30m", out["intraday_snapshot"])
        self.assertIn("15m", out["intraday_snapshot"])

        # Synthetic confluence check
        core = {
            "1W": {"support": [{"tf": "1W", "mid": 58100.0, "low": 57800.0, "high": 58400.0, "touches": 2}], "resistance": []},
            "1D": {"support": [{"tf": "1D", "mid": 58200.0, "low": 58000.0, "high": 58350.0, "touches": 3}], "resistance": []},
            "4H": {"support": [], "resistance": [{"tf": "4H", "mid": 62000.0, "low": 61850.0, "high": 62150.0, "touches": 2}]},
            "1H": {"support": [], "resistance": [{"tf": "1H", "mid": 62100.0, "low": 61980.0, "high": 62200.0, "touches": 1}]},
        }
        confs = compute_confluence_zones(core, ref_price=60000.0)
        self.assertEqual(len(confs["support"]), 1)
        self.assertEqual(confs["support"][0]["timeframes"], ["1W", "1D"])
        self.assertEqual(len(confs["resistance"]), 1)
        self.assertEqual(confs["resistance"][0]["tf_count"], 2)

    def test_magnet_overlap_detects_lower_cluster_below_support(self) -> None:
        core = {
            "1H": {
                "support": [{"tf": "1H", "mid": 59200.0, "low": 59100.0, "high": 59300.0}],
                "resistance": [{"tf": "1H", "mid": 61000.0, "low": 60900.0, "high": 61100.0}],
            },
            "4H": {"support": [], "resistance": []},
        }
        cmc = {
            "tactical_long_clusters_within_8pct": [{"price": 58600.0, "usd_m": 45.0, "leverage": 40}],
            "tactical_short_clusters_within_8pct": [{"price": 61800.0, "usd_m": 25.0, "leverage": 30}],
        }
        sm = {
            "magnets": {
                "liquidation_ladder": [
                    {"tier": "100x Longs", "side": "lower", "price": 58950.0, "estimated_vol_m": 120.0}
                ]
            }
        }
        overlaps = compute_magnet_overlaps(core, cmc, sm, ref_price=60000.0)
        self.assertEqual(len(overlaps), 3)
        self.assertEqual(overlaps[0]["trap_ref"], "trap_05")
        self.assertEqual(overlaps[0]["side"], "LOWER_BELOW_SUPPORT")

    def test_fail_soft_on_empty_inputs(self) -> None:
        out = compute_sr_bands({"klines": {}, "ticker": {}}, spot_magnet=None)
        self.assertEqual(out["status"], "DEGRADED")
        self.assertEqual(out["magnet_overlaps"], [])
        self.assertEqual(out["confluence_zones"], {"resistance": [], "support": []})


if __name__ == "__main__":
    unittest.main()
