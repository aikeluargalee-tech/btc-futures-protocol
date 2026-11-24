"""Unit tests verifying Milo Hermes audit P0/P1 engine fixes."""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from engine.cortex_rhyme_engine import (
    _causal_z_scores,
    _compute_causal_sma_regimes,
    _derive_posture,
    _lift_se_pts,
)
from engine.data_fetcher import _parse_binance_candles, _parse_farside_etf_html
from engine.run_cycle import _load_json, _save_json
from engine.spot_magnet_engine import compute_spot_magnet


class TestMiloAuditFixes(unittest.TestCase):
    def test_atomic_save_and_corrupt_ledger_protection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "ledger.json"
            self.assertIsNone(_load_json(p, abort_on_corrupt=True))

            _save_json(p, {"equity": 100000.0, "open_positions": []})
            loaded = _load_json(p, abort_on_corrupt=True)
            self.assertEqual(loaded["equity"], 100000.0)
            self.assertFalse(any(f.name.endswith(".tmp") for f in pathlib.Path(tmp).iterdir()))

            p.write_text('{"equity": 100000.0, ', encoding="utf-8")
            self.assertIsNone(_load_json(p, abort_on_corrupt=False))
            with self.assertRaises(RuntimeError):
                _load_json(p, abort_on_corrupt=True)

    def test_farside_skips_unsettled_today_row_and_bad_sum(self) -> None:
        html = """
        <table>
          <tr><th>Date</th><th>IBIT</th><th>FBTC</th><th>BITB</th><th>Total</th></tr>
          <tr><td>16 Nov 2026</td><td>-50.0</td><td>-20.0</td><td>-6.5</td><td>(76.5)</td></tr>
          <tr><td>17 Nov 2026</td><td>100.0</td><td>50.0</td><td>10.0</td><td>160.0</td></tr>
          <tr><td>18 Nov 2026</td><td>(300.0)</td><td>(200.0)</td><td>(10.0)</td><td>(510.0)</td></tr>
          <tr><td>19 Nov 2026</td><td>999.0</td><td>1.0</td><td>0.0</td><td>10.0</td></tr>
          <tr><td>20 Nov 2026</td><td>(400.0)</td><td>(100.0)</td><td>(20.0)</td><td>(520.0)</td></tr>
          <tr><td>21 Nov 2026</td><td>(300.0)</td><td>(200.0)</td><td>(69.7)</td><td>(569.7)</td></tr>
          <tr><td>24 Nov 2026</td><td>-</td><td>-</td><td>-</td><td>0.0</td></tr>
        </table>
        """
        out = _parse_farside_etf_html(html)
        self.assertIsNotNone(out)
        self.assertEqual(out["latest_date"], "21 Nov 2026")
        self.assertEqual(out["latest_usd_m"], -569.7)
        self.assertEqual(out["sum5_usd_m"], -1516.2)
        self.assertEqual(len(out["last5"]), 5)
        self.assertEqual(out["last5"][0][0], "16 Nov 2026")

    def test_parse_binance_candles_uses_close_time_filter(self) -> None:
        rows = [
            [1000, "60000", "60500", "59900", "60200", "10", 1999, "602000", 100, "5.5"],
            [2000, "60200", "60600", "60100", "60500", "12", 2999, "726000", 120, "6.0"],
        ]
        all_closed = _parse_binance_candles(rows, closed_only=True, now_ms=3000)
        self.assertEqual(len(all_closed), 2)
        self.assertEqual(all_closed[-1]["ts"], 2000)

        one_forming = _parse_binance_candles(rows, closed_only=True, now_ms=2500)
        self.assertEqual(len(one_forming), 1)
        self.assertEqual(one_forming[0]["ts"], 1000)

    def test_cortex_rhyme_z_mask_unknown_200d_and_2sigma_posture_gate(self) -> None:
        vals = [100.0 + (i % 5) for i in range(40)]
        z = _causal_z_scores(vals, window=168)
        self.assertTrue(all(v is None for v in z[:24]))
        self.assertIsNotNone(z[24])

        # Verify current index i is excluded from its own standardization mean/std
        spike = [10.0, 12.0] * 12 + [1000.0]
        zs = _causal_z_scores(spike, window=24)
        self.assertGreater(zs[-1], 3.9)

        regimes = _compute_causal_sma_regimes([60000.0] * 10, window=4800)
        self.assertTrue(all(tag == "UNKNOWN" for _, tag in regimes))

        se = _lift_se_pts(20, 10000)
        self.assertAlmostEqual(se, 11.19, places=2)
        sum24 = {"up_share": 56.0, "median_up_pct": 1.2, "median_down_pct": -0.7, "tail_skew_ratio": 1.71}
        _, verdict_noise = _derive_posture("solid", sum24, lift_24h=6.0, lift_se_24h=se)
        self.assertEqual(verdict_noise, "NEUTRAL_CHOP")

        _, verdict_sig = _derive_posture("solid", sum24, lift_24h=23.5, lift_se_24h=se)
        self.assertEqual(verdict_sig, "POSITIVE_SKEW_LOOP_A")

    def test_spot_magnet_uses_modelled_observational_language(self) -> None:
        h1 = [
            {"ts": 1_700_000_000_000 + i * 3600_000, "open": 60000.0, "high": 60300.0, "low": 59900.0, "close": 60100.0, "volume": 100.0, "taker_buy_volume": 55.0}
            for i in range(30)
        ]
        h4 = [
            {"ts": 1_700_000_000_000 + i * 14400_000, "open": 60000.0, "high": 60500.0, "low": 59800.0, "close": 60200.0, "volume": 400.0}
            for i in range(30)
        ]
        d1 = [
            {"ts": 1_700_000_000_000 + i * 86400_000, "open": 60000.0, "high": 61000.0, "low": 59500.0, "close": 60200.0, "volume": 2000.0, "taker_buy_volume": 1100.0}
            for i in range(35)
        ]
        market = {
            "ticker": {"price": 60200.0, "chg24_pct": 0.5},
            "klines": {"1h": h1, "4h": h4, "1d": d1, "spot_1h": h1, "spot_4h": h4, "spot_1d": d1},
            "derivatives": {"current_rate_pct": 0.01, "mark_price": 60250.0, "oi_btc": 30000.0, "btc_oi_change_pct_24h": 2.0, "orderbook_1pct": {"bids_asks_ratio": 1.1}},
            "extras": {},
        }
        out = compute_spot_magnet(market, {}, {})
        self.assertEqual(out["data_quality"], "LIVE")
        self.assertTrue(out["lsce"]["cluster_tested"].startswith("Modelled "))
        instr = out["dibse"]["actionable_trade_instruction"]
        for banned in ("Rotate ", "Sell 10%", "Deploy 75%", "confirmed"):
            self.assertNotIn(banned, instr)
        self.assertNotIn("CONFIRMED", out["lsce"]["status"])


if __name__ == "__main__":
    unittest.main()
