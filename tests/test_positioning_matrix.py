"""Unit tests for Project G 8-Cell Positioning Decision Matrix."""
from __future__ import annotations

import unittest

from engine.positioning_matrix import compute_positioning_matrix_g


def _market(funding_8h: float | None, oi_3d: float | None, above_200d: bool = False) -> dict:
    base_close = 70000.0
    cur_close = 80000.0 if above_200d else 60000.0
    d1 = [{"close": base_close} for _ in range(210)]
    return {
        "ticker": {"price": cur_close},
        "klines": {"1d": d1},
        "derivatives": {
            "current_rate_pct": funding_8h,
            "btc_oi_change_pct_3d": oi_3d,
        },
    }


class TestPositioningMatrixG(unittest.TestCase):
    def test_below_200d_crowded_shorts_matches_directional_colour(self) -> None:
        res = compute_positioning_matrix_g(_market(funding_8h=-0.004, oi_3d=5.2, above_200d=False))
        self.assertEqual(res["status"], "LIVE")
        self.assertEqual(res["regime_200d"], "below_200d")
        self.assertEqual(res["leverage_state"], "crowded_shorts")
        self.assertEqual(res["funding_daily_pct"], -0.012)
        self.assertTrue(res["extreme_short_tail_active"])
        self.assertEqual(res["daily_funding_band"]["band"], "< -0.01%")
        self.assertEqual(res["active_cell"]["n"], 18)
        self.assertEqual(res["active_cell"]["hit_rate_pct"], 72)
        self.assertEqual(res["active_cell"]["reading"], "directional colour only")

    def test_below_200d_positions_leaving_separates_from_crowded_shorts(self) -> None:
        res = compute_positioning_matrix_g(_market(funding_8h=-0.0016, oi_3d=-3.5, above_200d=False))
        self.assertEqual(res["leverage_state"], "positions_leaving")
        self.assertFalse(res["extreme_short_tail_active"])
        self.assertEqual(res["daily_funding_band"]["band"], "-0.01% .. 0%")
        self.assertEqual(res["active_cell"]["n"], 14)
        self.assertEqual(res["active_cell"]["hit_rate_pct"], 50)
        self.assertEqual(res["active_cell"]["reading"], "colour only")

    def test_positive_funding_above_and_below_200d(self) -> None:
        r_above = compute_positioning_matrix_g(_market(funding_8h=0.006, oi_3d=2.1, above_200d=True))
        self.assertEqual(r_above["active_cell"]["id"], "above_200d_crowded_longs")
        self.assertEqual(r_above["active_cell"]["reading"], "no edge")

        r_below = compute_positioning_matrix_g(_market(funding_8h=0.002, oi_3d=-8.1, above_200d=False))
        self.assertEqual(r_below["active_cell"]["id"], "below_200d_quiet_deleveraging")
        self.assertEqual(r_below["active_cell"]["n"], 37)
        self.assertEqual(r_below["active_cell"]["reading"], "no edge")

    def test_above_200d_crowded_shorts_edge_case(self) -> None:
        res = compute_positioning_matrix_g(_market(funding_8h=-0.005, oi_3d=4.0, above_200d=True))
        self.assertEqual(res["active_cell"]["id"], "above_200d_crowded_shorts")
        self.assertEqual(res["active_cell"]["n"], 0)
        self.assertEqual(res["active_cell"]["reading"], "never occurred in 299 weeks")

    def test_uses_cortex_rhyme_200d_when_d1_short_and_fails_soft(self) -> None:
        cr = {"current_state": {"regime_context": {"trend_regime": "BELOW_200D_SMA", "sma_200d": 76000.0}}}
        res = compute_positioning_matrix_g(
            {"ticker": {"price": 60000.0}, "klines": {"1d": []}, "derivatives": {"current_rate_pct": 0.001, "btc_oi_change_pct_24h": -2.0}},
            cortex_rhyme=cr,
        )
        self.assertEqual(res["status"], "LIVE")
        self.assertEqual(res["oi_window"], "24h")
        self.assertEqual(res["active_cell"]["id"], "below_200d_quiet_deleveraging")

        off = compute_positioning_matrix_g({"ticker": {}, "klines": {}, "derivatives": {}})
        self.assertEqual(off["status"], "unavailable")
        self.assertEqual(len(off["matrix_rows"]), 8)


if __name__ == "__main__":
    unittest.main()
