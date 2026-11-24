"""Unit tests for Project ETF, Project L (Market Time), and Project H context overlays."""
from __future__ import annotations

import datetime as dt
import unittest

from engine.context_overlays import (
    compute_etf_flow_regime,
    compute_market_time_profile,
    compute_patient_money_h,
)


class TestContextOverlays(unittest.TestCase):
    def test_etf_flow_regimes(self) -> None:
        base_m = {"etf": {"latest_usd_m": -570.0, "sum5_usd_m": -2127.0}, "derivatives": {"btc_oi_change_pct_24h": -8.13, "current_rate_pct": 0.004}}
        r_unwind = compute_etf_flow_regime(base_m, spot_magnet={"metrics": {"spot_cvd_ratio": 0.99, "spot_cvd_slope_7d": -5000.0}})
        self.assertEqual(r_unwind["regime"], "CARRY UNWIND")

        m_shorts = {"etf": {"latest_usd_m": -300.0, "sum5_usd_m": -800.0}, "derivatives": {"btc_oi_change_pct_24h": 4.5, "current_rate_pct": -0.002}}
        self.assertEqual(compute_etf_flow_regime(m_shorts)["regime"], "NEW SHORTS")

        m_abs = {"etf": {"latest_usd_m": -250.0, "sum5_usd_m": -600.0}, "derivatives": {"btc_oi_change_pct_24h": -2.0, "current_rate_pct": -0.005}}
        r_abs = compute_etf_flow_regime(m_abs, spot_magnet={"metrics": {"spot_cvd_ratio": 1.08, "spot_cvd_slope_7d": 500.0}})
        self.assertEqual(r_abs["regime"], "ABSORPTION")

        r_in = compute_etf_flow_regime({"etf": {"latest_usd_m": 400.0, "sum5_usd_m": 1200.0}, "derivatives": {"btc_oi_change_pct_24h": 3.0, "current_rate_pct": 0.02}})
        self.assertEqual(r_in["regime"], "CARRY BUILD")

    def test_market_time_l_day_hour_vol_cluster_and_stop_ratio(self) -> None:
        fri_14 = dt.datetime(2026, 11, 20, 14, 15, tzinfo=dt.timezone.utc)
        res_fri = compute_market_time_profile(
            {"klines": {"1h": [{"open": 60000.0, "high": 61500.0, "low": 60000.0, "close": 61400.0}]}},
            signal={"proposal": {"stop_distance_pct": 1.5}},
            now_utc=fri_14,
        )
        self.assertEqual(res_fri["day_of_week"], "Fri")
        self.assertEqual(res_fri["expected_day_range_pct"], 3.98)
        self.assertEqual(res_fri["awake_state"], "PEAK_AWAKE")
        self.assertTrue(res_fri["vol_cluster_active"])
        self.assertEqual(res_fri["proposal_stop_vs_day_range_x"], 0.38)
        self.assertTrue(res_fri["stop_noise_warning"])

        sat_10 = dt.datetime(2026, 11, 21, 10, 5, tzinfo=dt.timezone.utc)
        res_sat = compute_market_time_profile({"klines": {"1h": [{"open": 60000.0, "high": 60300.0, "low": 59950.0, "close": 60100.0}]}}, now_utc=sat_10)
        self.assertEqual(res_sat["expected_day_range_pct"], 1.91)
        self.assertEqual(res_sat["awake_state"], "QUIET_THIN")
        self.assertFalse(res_sat["vol_cluster_active"])

    def test_patient_money_h_dollar_funding_and_aggression(self) -> None:
        market = {
            "ticker": {"price": 60000.0},
            "derivatives": {
                "current_rate_pct": 0.01,
                "btc_oi_change_pct_24h": -4.0,
                "cmc_liquidations": {"realized": {"global_btc_oi_usd_b": 6.0}},
            },
        }
        cr = {"current_state": {"raw_metrics": {"taker_buy_ratio": 0.54}}}
        res = compute_patient_money_h(market, cortex_rhyme=cr)
        self.assertEqual(res["funding_8h_usd"], 600000.0)
        self.assertEqual(res["funding_24h_usd"], 1800000.0)
        self.assertEqual(res["crowd_payer"], "Longs paying Shorts")
        self.assertEqual(res["aggression_oi_state"], "SHORT COVERING")

        res_new_longs = compute_patient_money_h(
            {"ticker": {"price": 60000.0}, "derivatives": {"current_rate_pct": 0.01, "btc_oi_change_pct_24h": 3.5, "total_oi_btc": 50000.0}},
            cortex_rhyme={"current_state": {"raw_metrics": {"taker_buy_ratio": 0.55}}},
        )
        self.assertEqual(res_new_longs["aggression_oi_state"], "NEW LONGS ENTERING")


if __name__ == "__main__":
    unittest.main()
