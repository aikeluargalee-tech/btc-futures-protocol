"""Unit tests verifying BTC Short-Term Futures Protocol v4.0 deterministic rules."""
from __future__ import annotations

import datetime as dt
import math
import unittest

from engine.config import load_config
from engine.paper_ledger import (
    execute_signal_entry,
    init_ledger,
    process_cycle,
)
from engine.regime_engine import compute_regime
from engine.signal_engine import calculate_position_sizing, check_macro_release_window, evaluate_signal


def _make_candles(
    count: int,
    start_price: float,
    step_pct: float,
    step_ms: int,
    wick_pct: float = 0.0025,
    vol: float = 1000.0,
) -> list[dict[str, float]]:
    base_ts = 1700000000000
    out = []
    p = start_price
    for i in range(count):
        wave = math.sin(i * 0.55) * 0.018
        op = p
        cl = p * (1.0 + step_pct + wave * 0.35)
        hi = max(op, cl) * (1.0 + wick_pct)
        lo = min(op, cl) * (1.0 - wick_pct)
        out.append({"ts": base_ts + i * step_ms, "open": op, "high": hi, "low": lo, "close": cl, "volume": vol})
        p = cl
    return out


def _make_market(trend: str = "bull", funding_pct: float = 0.005) -> dict:
    if trend == "bull":
        d1 = _make_candles(260, 50000.0, 0.0030, 86400000)
        h4 = _make_candles(180, d1[-30]["close"], 0.0042, 14400000)
        # Clean bullish BOS on last 4H bar
        h4[-1]["open"] = h4[-2]["close"]
        h4[-1]["close"] = max(c["high"] for c in h4[-10:-1]) * 1.003
        h4[-1]["high"] = h4[-1]["close"] * 1.001
        h4[-1]["low"] = h4[-1]["open"] * 0.998
        h4[-1]["volume"] = 1800.0
        h1 = _make_candles(100, h4[-10]["close"], 0.0004, 3600000)
        macro = {
            "spx": {"value": 6000.0, "roc10_pct": 1.2, "vs_sma20_pct": 2.5},
            "ndx": {"value": 21000.0, "roc10_pct": 1.5, "vs_sma20_pct": 3.0},
            "vix": {"value": 14.5},
            "dxy": {"value": 101.0, "roc10_pct": -1.8},
            "us10y": {"value": 4.0, "roc10_pct": -4.0},
        }
        etf = {"latest_date": "13 Nov 2026", "latest_usd_m": 250.0, "sum5_usd_m": 850.0, "last5": []}
        stables = {"total_usd_b": 190.0, "chg7d_pct": 1.2}
    elif trend == "bear":
        d1 = _make_candles(260, 95000.0, -0.0030, 86400000)
        h4 = _make_candles(180, d1[-30]["close"], -0.0042, 14400000)
        h4[-1]["open"] = h4[-2]["close"]
        h4[-1]["close"] = min(c["low"] for c in h4[-10:-1]) * 0.997
        h4[-1]["low"] = h4[-1]["close"] * 0.999
        h4[-1]["high"] = h4[-1]["open"] * 1.002
        h4[-1]["volume"] = 1800.0
        h1 = _make_candles(100, h4[-10]["close"], -0.0004, 3600000)
        macro = {
            "spx": {"value": 5400.0, "roc10_pct": -3.0, "vs_sma20_pct": -3.2},
            "ndx": {"value": 18000.0, "roc10_pct": -4.0, "vs_sma20_pct": -3.8},
            "vix": {"value": 29.0},
            "dxy": {"value": 107.0, "roc10_pct": 2.2},
            "us10y": {"value": 4.8, "roc10_pct": 6.5},
        }
        etf = {"latest_date": "13 Nov 2026", "latest_usd_m": -220.0, "sum5_usd_m": -850.0, "last5": []}
        stables = {"total_usd_b": 180.0, "chg7d_pct": -1.1}
    else:  # neutral choppy
        d1 = _make_candles(260, 70000.0, 0.0, 86400000)
        h4 = _make_candles(180, 70000.0, 0.0, 14400000)
        h1 = _make_candles(100, 70000.0, 0.0, 3600000)
        macro = {"spx": {"vs_sma20_pct": 0.0}, "dxy": {"roc10_pct": 0.0}, "vix": {"value": 18.0}}
        etf = {"latest_date": "13 Nov 2026", "latest_usd_m": 0.0, "sum5_usd_m": 0.0, "last5": []}
        stables = {"total_usd_b": 185.0, "chg7d_pct": 0.0}

    price = h4[-1]["close"]
    eth_d1 = _make_candles(40, 2500.0, 0.0005 if trend == "bull" else -0.001, 86400000)
    return {
        "fetched_at_utc": "2026-11-12T14:00:00Z",  # Thursday London/NY overlap
        "ticker": {"price": price, "high24": price * 1.01, "low24": price * 0.99, "chg24_pct": 1.2, "source": "test"},
        "klines": {"1d": d1, "4h": h4, "1h": h1, "eth_1d": eth_d1},
        "derivatives": {"current_rate_pct": funding_pct, "history_pct": [0.005] * 60, "oi_btc": 50000.0, "venues": {}},
        "macro": macro,
        "etf": etf,
        "stables": stables,
        "extras": {},
        "macro_calendar": [],
        "fetch_errors": [],
    }


def _qualifying_regime(score: float, daily_bias: str = "BULL", is_weekend: bool = False) -> dict:
    bias = "LONG" if score >= 68.0 else ("SHORT" if score <= 32.0 else "FLAT")
    return {
        "ok": True,
        "score": score,
        "bias": bias,
        "daily_bias": daily_bias,
        "thresholds": {"long": 68.0, "short": 32.0, "dd_tier1_active": False, "weekend_long": 80.0, "weekend_short": 20.0},
        "groups": {},
        "dominant_factors": [],
        "last_4h_close_ts": 1794600000000,
        "is_weekend_utc": is_weekend,
    }


class ProtocolV4Tests(unittest.TestCase):
    def test_v4_sizing_04pct_risk_and_2x_leverage_cap(self):
        # Wide stop: exact 0.4% risk
        s_risk = calculate_position_sizing(equity=100000.0, entry=100000.0, stop=99000.0, risk_pct=0.004, max_leverage=2.0)
        self.assertTrue(s_risk["valid"])
        self.assertFalse(s_risk["leverage_capped"])
        self.assertAlmostEqual(s_risk["actual_risk_usd"], 400.0, places=2)
        self.assertAlmostEqual(s_risk["actual_risk_pct"], 0.4, places=3)

        # Tight stop: clamped by 1:2 leverage cap
        s_cap = calculate_position_sizing(equity=100000.0, entry=100000.0, stop=99900.0, risk_pct=0.004, max_leverage=2.0)
        self.assertTrue(s_cap["leverage_capped"])
        self.assertEqual(s_cap["size_btc"], 2.0)
        self.assertEqual(s_cap["notional_usd"], 200000.0)
        self.assertLessEqual(s_cap["leverage"], 2.0)

    def test_v4_regime_68_32_thresholds_and_4h_weights(self):
        cfg = load_config()
        weekday_dt = dt.datetime(2026, 11, 12, 14, 0, tzinfo=dt.timezone.utc)
        r_bull = compute_regime(_make_market("bull"), cfg, now_utc=weekday_dt)
        r_bear = compute_regime(_make_market("bear"), cfg, now_utc=weekday_dt)
        r_flat = compute_regime(_make_market("flat"), cfg, now_utc=weekday_dt)

        self.assertTrue(r_bull["ok"] and r_bear["ok"])
        self.assertGreaterEqual(r_bull["score"], 68.0)
        self.assertEqual(r_bull["bias"], "LONG")
        self.assertLessEqual(r_bear["score"], 32.0)
        self.assertEqual(r_bear["bias"], "SHORT")
        self.assertGreater(r_flat["score"], 32.0)
        self.assertLess(r_flat["score"], 68.0)
        self.assertEqual(r_flat["bias"], "FLAT")
        self.assertIn("session_context", r_bull["groups"])

    def test_strict_flat_zone_33_to_67_no_exceptions(self):
        cfg = load_config()
        mkt = _make_market("bull")
        ledger = init_ledger(cfg)
        sig = evaluate_signal(mkt, _qualifying_regime(67.5, "BULL"), ledger, cfg)
        self.assertEqual(sig["status"], "FLAT")
        self.assertEqual(sig["active_signals"], ["FLAT"])
        self.assertNotIn("sell_inventory", sig)
        self.assertFalse(sig["checklist"][0]["passed"])

    def test_macro_blackout_60m_strict_rule(self):
        cfg = load_config()
        mkt = _make_market("bull")
        mkt["macro_calendar"] = [{"title": "US CPI", "minutes_away": 55.0}]
        chk = check_macro_release_window(mkt["macro_calendar"], cfg["leverage_and_risk"]["macro_blackout_minutes"])
        self.assertTrue(chk["blocked"])

        ledger = init_ledger(cfg)
        sig = evaluate_signal(mkt, _qualifying_regime(78.0, "BULL"), ledger, cfg)
        self.assertEqual(sig["status"], "FLAT")
        self.assertFalse(sig["checklist"][8]["passed"])

    def test_max_stop_distance_2_2_pct_and_min_rr_1_6(self):
        cfg = load_config()
        # High volatility 4H bars forcing stop > 2.2%
        mkt = _make_market("bear")
        for bar in mkt["klines"]["4h"][-25:]:
            mid = bar["close"]
            bar["high"] = mid * 1.035
            bar["low"] = mid * 0.965
        ledger = init_ledger(cfg)
        sig = evaluate_signal(mkt, _qualifying_regime(20.0, "BEAR"), ledger, cfg)
        self.assertEqual(sig["status"], "FLAT")
        self.assertEqual(sig["active_signals"], ["FLAT"])
        self.assertFalse(sig["checklist"][4]["passed"])  # Rule 5: Stop <= 2.2%

        # Min R:R 1.6 check via custom cfg threshold
        cfg_rr = load_config()
        cfg_rr["leverage_and_risk"]["min_rr"] = 99.0
        sig_rr = evaluate_signal(_make_market("bull"), _qualifying_regime(78.0, "BULL"), ledger, cfg_rr)
        self.assertEqual(sig_rr["status"], "FLAT")
        self.assertFalse(sig_rr["checklist"][3]["passed"])

    def test_weekly_halt_blocks_futures_signal(self):
        cfg = load_config()
        mkt = _make_market("bear")
        ledger = init_ledger(cfg)
        ledger["breakers"]["weekly_halted"] = True
        sig = evaluate_signal(mkt, _qualifying_regime(28.0, "BEAR"), ledger, cfg)
        self.assertEqual(sig["status"], "FLAT")
        self.assertEqual(sig["active_signals"], ["FLAT"])
        self.assertFalse(sig["checklist"][7]["passed"])

    def test_weekend_80_20_extreme_and_half_size(self):
        cfg = load_config()
        mkt = _make_market("bull")
        ledger = init_ledger(cfg)
        # Score 74 on weekend -> blocked (requires >= 80)
        sig_blocked = evaluate_signal(mkt, _qualifying_regime(74.0, "BULL", is_weekend=True), ledger, cfg)
        self.assertEqual(sig_blocked["status"], "FLAT")
        self.assertFalse(sig_blocked["checklist"][0]["passed"])

        # Score 82 on weekend -> half risk sizing (0.2% risk)
        sig_wk = evaluate_signal(mkt, _qualifying_regime(82.0, "BULL", is_weekend=True), ledger, cfg)
        self.assertTrue(sig_wk["proposal"]["weekend_halved"])
        self.assertLessEqual(sig_wk["proposal"]["actual_risk_pct"], 0.2001)

    def test_time_stops_8h_12h_24h_and_daily_close(self):
        cfg = load_config()
        mkt = _make_market("bull")
        price = mkt["ticker"]["price"]
        t0 = dt.datetime(2026, 11, 12, 2, 0, tzinfo=dt.timezone.utc)
        ledger = init_ledger(cfg, t0)
        reg = _qualifying_regime(76.0, "BULL", is_weekend=False)
        sig = evaluate_signal(mkt, reg, ledger, cfg)
        # Construct deterministic valid LONG signal for lifecycle tests
        sig["status"] = "LONG"
        sig["proposal"] = {
            "valid": True,
            "entry_price": price,
            "stop_price": round(price * 0.985, 1),
            "target1_price": round(price * 1.03, 1),
            "size_btc": 0.4,
            "notional_usd": round(0.4 * price, 2),
            "leverage": 0.4,
            "actual_risk_pct": 0.4,
            "weekend_halved": False,
        }
        execute_signal_entry(ledger, sig, regime=reg, now=t0)
        self.assertEqual(len(ledger["open_positions"]), 1)

        # At +8.5h with < +1R: reduces 50%
        process_cycle(ledger, mkt, reg, cfg, t0 + dt.timedelta(hours=8, minutes=30))
        self.assertEqual(len(ledger["open_positions"]), 1)
        self.assertAlmostEqual(ledger["open_positions"][0]["size_btc"], 0.2, places=4)
        self.assertEqual(ledger["closed_trades"][-1]["reason"], "TIME_STOP_8H_REDUCE")

        # At +12.5h still < +1R: full exit
        process_cycle(ledger, mkt, reg, cfg, t0 + dt.timedelta(hours=12, minutes=30))
        self.assertEqual(len(ledger["open_positions"]), 0)
        self.assertEqual(ledger["closed_trades"][-1]["reason"], "TIME_STOP_12H_EXIT")

        # Test 24h max hold & daily close rule (when trade DID reach +1.1R previously)
        t1 = dt.datetime(2026, 11, 12, 22, 0, tzinfo=dt.timezone.utc)
        ledger2 = init_ledger(cfg, t1)
        execute_signal_entry(ledger2, sig, regime=reg, now=t1)
        ledger2["open_positions"][0]["max_favorable_r"] = 1.1  # exempt from 8h/12h time stop
        # Cross UTC midnight with non-improved score (74 <= 76) -> daily close 50% reduce
        reg_same = _qualifying_regime(74.0, "BULL", is_weekend=False)
        process_cycle(ledger2, mkt, reg_same, cfg, t1 + dt.timedelta(hours=3))
        self.assertEqual(ledger2["closed_trades"][-1]["reason"], "DAILY_CLOSE_NO_IMPROVEMENT_REDUCE")
        self.assertEqual(len(ledger2["open_positions"]), 1)
        # Hit 24h max hold -> full exit
        process_cycle(ledger2, mkt, reg_same, cfg, t1 + dt.timedelta(hours=24, minutes=5))
        self.assertEqual(len(ledger2["open_positions"]), 0)
        self.assertEqual(ledger2["closed_trades"][-1]["reason"], "MAX_HOLD_24H_EXIT")

    def test_all_five_circuit_breakers(self):
        cfg = load_config()
        now = dt.datetime(2026, 11, 12, 12, 0, tzinfo=dt.timezone.utc)
        mkt = _make_market("bull")
        price = mkt["ticker"]["price"]
        reg = _qualifying_regime(75.0, "BULL")

        # 1) Intraday -1.2% & Daily -2.0%
        l1 = init_ledger(cfg, now)
        l1["realized_equity"] = 98700.0  # -1.3% intraday & day
        process_cycle(l1, mkt, reg, cfg, now)
        self.assertTrue(l1["breakers"]["intraday_halted"])
        self.assertFalse(l1["breakers"]["daily_halted"])

        l1["realized_equity"] = 97900.0  # -2.1% daily
        process_cycle(l1, mkt, reg, cfg, now)
        self.assertTrue(l1["breakers"]["daily_halted"])

        # 2) Weekly -4.0% flattens futures
        l2 = init_ledger(cfg, now)
        l2["open_positions"].append(
            {
                "id": "POS1",
                "direction": "LONG",
                "entry_price": price,
                "stop_price": price * 0.99,
                "initial_stop_dist": price * 0.01,
                "size_btc": 0.2,
                "risk_pct": 0.4,
                "opened_at": "2026-11-12T10:00:00Z",
                "opened_at_ms": int((now - dt.timedelta(hours=2)).timestamp() * 1000),
            }
        )
        l2["realized_equity"] = 95800.0  # -4.2% weekly
        process_cycle(l2, mkt, reg, cfg, now)
        self.assertTrue(l2["breakers"]["weekly_halted"])
        self.assertEqual(len(l2["open_positions"]), 0)

        # 3) -6% DD Tier 1 (0.2% risk, 75/25 thresholds)
        l3 = init_ledger(cfg, now)
        l3["realized_equity"] = 93500.0  # -6.5% DD
        process_cycle(l3, mkt, reg, cfg, now)
        self.assertTrue(l3["breakers"]["dd_tier1_active"])
        self.assertFalse(l3["breakers"]["dd_tier2_locked"])
        r_t1 = compute_regime(mkt, cfg, dd_tier1_active=True, now_utc=now)
        self.assertEqual(r_t1["thresholds"]["long"], 75.0)
        self.assertEqual(r_t1["thresholds"]["short"], 25.0)

        # 4) -10% DD Tier 2 lock
        l3["realized_equity"] = 89500.0  # -10.5% DD
        process_cycle(l3, mkt, reg, cfg, now)
        self.assertTrue(l3["breakers"]["dd_tier2_locked"])


if __name__ == "__main__":
    unittest.main()
