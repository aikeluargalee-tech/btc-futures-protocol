"""Unit tests verifying BTC Futures Swing Trading Protocol v1.0 deterministic rules."""
from __future__ import annotations

import datetime as dt
import math
import unittest

from engine.config import load_config
from engine.paper_ledger import execute_signal_entry, init_ledger, process_cycle
from engine.regime_engine import compute_regime
from engine.signal_engine import calculate_position_sizing, check_macro_blackout, evaluate_signal


def _make_candles(
    count: int,
    start_price: float,
    step_pct: float,
    step_ms: int,
    wick_pct: float = 0.004,
    vol: float = 1000.0,
) -> list[dict[str, float]]:
    base_ts = 1700000000000
    out = []
    p = start_price
    for i in range(count):
        wave = math.sin(i * 0.45) * 0.008
        op = p
        cl = p * (1.0 + step_pct + wave * 0.25)
        hi = max(op, cl) * (1.0 + wick_pct)
        lo = min(op, cl) * (1.0 - wick_pct)
        out.append({"ts": base_ts + i * step_ms, "open": op, "high": hi, "low": lo, "close": cl, "volume": vol})
        p = cl
    return out


def _make_market(trend: str = "bull", funding_pct: float = 0.005) -> dict:
    if trend == "bull":
        d1 = _make_candles(260, 50000.0, 0.0022, 86400000)
        h4 = _make_candles(180, d1[-30]["close"], 0.0012, 14400000)
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
    else:
        d1 = _make_candles(260, 95000.0, -0.0022, 86400000)
        h4 = _make_candles(180, d1[-30]["close"], -0.0012, 14400000)
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

    price = h4[-1]["close"]
    eth_d1 = _make_candles(40, 2500.0, 0.0005 if trend == "bull" else -0.001, 86400000)
    return {
        "fetched_at_utc": "2026-11-14T00:00:00Z",
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


class ProtocolTests(unittest.TestCase):
    def test_leverage_hard_cap_2x(self):
        s = calculate_position_sizing(equity=100000.0, entry=100000.0, stop=99900.0, risk_pct=0.005, max_leverage=2.0)
        self.assertTrue(s["valid"])
        self.assertTrue(s["leverage_capped"])
        self.assertLessEqual(s["leverage"], 2.0)
        self.assertEqual(s["size_btc"], 2.0)
        self.assertEqual(s["notional_usd"], 200000.0)

    def test_regime_engine_directional_separation(self):
        cfg = load_config()
        r_bull = compute_regime(_make_market("bull"), cfg)
        r_bear = compute_regime(_make_market("bear"), cfg)
        self.assertTrue(r_bull["ok"] and r_bear["ok"])
        self.assertGreaterEqual(r_bull["score"], 65.0)
        self.assertEqual(r_bull["bias"], "LONG_ELIGIBLE")
        self.assertLessEqual(r_bear["score"], 35.0)
        self.assertEqual(r_bear["bias"], "SHORT_ELIGIBLE")
        self.assertEqual(len(r_bull["dominant_factors"]), 2)

    def test_macro_blackout_30m_rule(self):
        cfg = load_config()
        cal = [{"title": "US CPI m/m", "minutes_away": 15.0}]
        blk = check_macro_blackout(cal, 30, 68.0, cfg)
        self.assertTrue(blk["blocked"])
        self.assertFalse(blk["halve_size"])

        alw = check_macro_blackout(cal, 30, 78.0, cfg)
        self.assertFalse(alw["blocked"])
        self.assertTrue(alw["halve_size"])

    def test_funding_degradation_rejection(self):
        cfg = load_config()
        mkt = _make_market("bull", funding_pct=0.25)
        h4 = mkt["klines"]["4h"]
        prev_hi = max(c["high"] for c in h4[-7:-1])
        h4[-1]["close"] = prev_hi * 1.005
        h4[-1]["open"] = prev_hi * 0.998
        h4[-1]["high"] = h4[-1]["close"] * 1.001
        mkt["ticker"]["price"] = h4[-1]["close"]
        mkt["klines"]["1d"][-1]["high"] = h4[-1]["close"]

        ledger = init_ledger(cfg)
        regime = compute_regime(mkt, cfg)
        sig = evaluate_signal(mkt, regime, ledger, cfg)
        self.assertEqual(sig["status"], "FLAT")
        self.assertTrue(any("R:R" in r for r in sig["rejection_reasons"]))

    def test_circuit_breakers_daily_weekly_and_drawdowns(self):
        cfg = load_config()
        mkt = _make_market("bull")
        now = dt.datetime(2026, 11, 14, 12, 0, tzinfo=dt.timezone.utc)
        ledger = init_ledger(cfg, now)
        price = mkt["ticker"]["price"]
        ledger["open_positions"].append(
            {
                "id": "BTC-0001",
                "role": "primary",
                "direction": "LONG",
                "opened_at_utc": "2026-11-14T01:00:00Z",
                "entry_price": price,
                "stop_price": price * 0.96,
                "initial_stop_price": price * 0.96,
                "target1_price": price * 1.10,
                "target1_label": "Test TP",
                "size_btc": 2.0,
                "initial_size_btc": 2.0,
                "notional_usd": 2.0 * price,
                "leverage": 1.5,
                "risk_usd": 500.0,
                "initial_risk_usd": 500.0,
                "risk_pct": 0.5,
                "regime_score_at_entry": 72.0,
                "dominant_factors": [],
                "actions": [],
            }
        )
        ledger["realized_equity"] = 98400.0
        mkt["klines"]["1h"][-1]["low"] = price * 0.99
        regime = compute_regime(mkt, cfg)
        ledger, _ = process_cycle(ledger, mkt, regime, cfg, now_utc=now)
        self.assertTrue(ledger["circuit_breakers"]["daily_halted"])
        self.assertFalse(ledger["circuit_breakers"]["weekly_halted"])

        ledger["realized_equity"] = 96500.0
        ledger, _ = process_cycle(ledger, mkt, regime, cfg, now_utc=now)
        self.assertTrue(ledger["circuit_breakers"]["weekly_halted"])
        self.assertEqual(len(ledger["open_positions"]), 0)

        ledger["realized_equity"] = 91500.0
        ledger, _ = process_cycle(ledger, mkt, regime, cfg, now_utc=now)
        self.assertTrue(ledger["circuit_breakers"]["dd_tier1_active"])
        self.assertFalse(ledger["circuit_breakers"]["dd_tier2_locked"])

        ledger["realized_equity"] = 87500.0
        ledger, _ = process_cycle(ledger, mkt, regime, cfg, now_utc=now)
        self.assertTrue(ledger["circuit_breakers"]["dd_tier2_locked"])

        ledger, _ = process_cycle(ledger, mkt, regime, cfg, now_utc=now, reset_review_lock=True)
        self.assertFalse(ledger["circuit_breakers"]["dd_tier2_locked"])

    def test_position_lifecycle_scale_out_and_be_trail(self):
        cfg = load_config()
        mkt = _make_market("bull")
        now = dt.datetime(2026, 11, 14, 12, 0, tzinfo=dt.timezone.utc)
        ledger = init_ledger(cfg, now)
        regime = compute_regime(mkt, cfg)

        entry = 70000.0
        stop = 68600.0
        fake_signal = {
            "status": "LONG",
            "proposal": {
                "valid": True,
                "role": "primary",
                "entry_method": "LIMIT_AT_LEVEL",
                "entry_price": entry,
                "stop_price": stop,
                "target1_price": 73000.0,
                "target1_label": "Prior Weekly High",
                "size_btc": 0.357,
                "notional_usd": 24990.0,
                "leverage": 0.25,
                "actual_risk_usd": 500.0,
                "actual_risk_pct": 0.5,
                "raw_rr": 2.14,
                "funding_adjusted_rr": 2.05,
            },
        }
        pos = execute_signal_entry(ledger, fake_signal, regime, now_utc=now)
        self.assertIsNotNone(pos)
        self.assertEqual(len(ledger["open_positions"]), 1)

        mkt["ticker"]["price"] = 72240.0
        mkt["klines"]["1h"][-1]["low"] = 71800.0
        ledger, events = process_cycle(ledger, mkt, regime, cfg, now_utc=now + dt.timedelta(hours=12))
        pos = ledger["open_positions"][0]
        self.assertTrue(pos["scale_out_done"])
        self.assertLess(pos["size_btc"], 0.357)
        self.assertGreaterEqual(pos["stop_price"], entry)
        self.assertTrue(any(e["event"] == "SCALE_OUT_PARTIAL" for e in events))
