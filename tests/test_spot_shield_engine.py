"""Unit & bit-for-bit truncation-invariance tests for Project F Spot Shield (80/20)."""
from __future__ import annotations

import datetime as dt
import math
import unittest
from unittest.mock import patch

from engine.spot_shield_engine import (
    compute_spot_shield,
    evaluate_sleeve1_vwap_shield,
    evaluate_sleeve2_ttm_squeeze,
)


def _make_daily_and_4h(days: int = 210) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    """Build deterministic multi-regime synthetic closed 1D and 4H Binance bars."""
    start_ms = int(dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
    day_ms = 86_400_000
    h4_ms = 14_400_000
    bars_4h: list[dict[str, float]] = []
    bars_1d: list[dict[str, float]] = []

    price = 60000.0
    for d in range(days):
        d_ts = start_ms + d * day_ms
        d_open = price
        d_high = price
        d_low = price
        d_vol = 0.0
        for sub in range(6):
            idx = d * 6 + sub
            ts = d_ts + sub * h4_ms
            if d < 140:
                drift = 0.0005 * math.sin(idx * 0.25)
                amp = 0.006
            elif d < 165:
                # Prolonged tight squeeze followed by strong trend expansion
                drift = 0.0045 if d >= 158 else 0.0001 * math.sin(idx)
                amp = 0.0012 if d < 158 else 0.012
            elif d < 185:
                drift = 0.0032 + 0.001 * math.sin(idx * 0.3)
                amp = 0.008
            else:
                drift = -0.0055
                amp = 0.009
            op = price
            cl = op * (1.0 + drift)
            hi = max(op, cl) * (1.0 + amp)
            lo = min(op, cl) * (1.0 - amp)
            vol = 1200.0 + (idx % 7) * 150.0
            bars_4h.append(
                {
                    "ts": ts,
                    "close_ts": ts + h4_ms - 1,
                    "open": op,
                    "high": hi,
                    "low": lo,
                    "close": cl,
                    "volume": vol,
                }
            )
            d_high = max(d_high, hi)
            d_low = min(d_low, lo)
            d_vol += vol
            price = cl
        bars_1d.append(
            {
                "ts": d_ts,
                "close_ts": d_ts + day_ms - 1,
                "open": d_open,
                "high": d_high,
                "low": d_low,
                "close": price,
                "volume": d_vol,
            }
        )
    return bars_4h, bars_1d


class TestSpotShieldEngine(unittest.TestCase):
    def test_truncation_invariance_zero_lookahead(self) -> None:
        bars_4h, bars_1d = _make_daily_and_4h(220)
        full_s1 = evaluate_sleeve1_vwap_shield(bars_4h, bars_1d)
        full_s2 = evaluate_sleeve2_ttm_squeeze(bars_1d)
        self.assertEqual(full_s1["status"], "LIVE")
        self.assertEqual(full_s2["status"], "LIVE")

        for cut_4h in (900, 1020, 1180):
            cut_ts = bars_4h[cut_4h - 1]["ts"]
            d_sub = [d for d in bars_1d if d["ts"] <= cut_ts]
            tr_s1 = evaluate_sleeve1_vwap_shield(bars_4h[:cut_4h], d_sub)
            self.assertEqual(tr_s1["series"]["signals"], full_s1["series"]["signals"][:cut_4h])
            self.assertEqual(tr_s1["series"]["stops"], full_s1["series"]["stops"][:cut_4h])

        for cut_1d in (120, 165, 200):
            tr_s2 = evaluate_sleeve2_ttm_squeeze(bars_1d[:cut_1d])
            self.assertEqual(tr_s2["series"]["signals"], full_s2["series"]["signals"][:cut_1d])
            self.assertEqual(tr_s2["series"]["stops"], full_s2["series"]["stops"][:cut_1d])

    def test_sleeve1_uptrend_entry_and_bear_exit(self) -> None:
        bars_4h, bars_1d = _make_daily_and_4h(210)
        # During uptrend peak (~day 175 -> 4H bar 1050)
        mid_ts = bars_4h[1050]["ts"]
        d_mid = [d for d in bars_1d if d["ts"] <= mid_ts]
        res_bull = evaluate_sleeve1_vwap_shield(bars_4h[:1051], d_mid)
        self.assertIn(res_bull["action"], ("BUY BTC", "HOLD BTC"))
        self.assertTrue(res_bull["conditions"]["above_120d_ema"])

        # After sharp selloff through day 210, bear shield closes
        res_bear = evaluate_sleeve1_vwap_shield(bars_4h, bars_1d)
        self.assertIn(res_bear["action"], ("SELL BTC", "HOLD USDT"))
        self.assertFalse(res_bear["conditions"]["above_120d_ema"])

    def test_sleeve2_squeeze_breakout_triggers_and_exits(self) -> None:
        _, bars_1d = _make_daily_and_4h(210)
        res = evaluate_sleeve2_ttm_squeeze(bars_1d)
        self.assertEqual(res["status"], "LIVE")
        self.assertIn(1, res["series"]["signals"])
        self.assertIn(-1, res["series"]["signals"])

    def test_compute_spot_shield_fail_soft(self) -> None:
        with patch("engine.spot_shield_engine.fetch_binance_spot_closed_klines", return_value=[]):
            out = compute_spot_shield(dt.datetime(2026, 11, 24, 12, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(out["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
