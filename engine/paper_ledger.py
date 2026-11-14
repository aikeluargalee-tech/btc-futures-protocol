"""Version 4.0 Paper Trading Ledger, Trade Management (8h/12h/24h/Weekend) & 5-Tier Circuit Breakers."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from .indicators import ema_series


def _utc_iso(now: dt.datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_week_key(now: dt.datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _hours_open(pos: dict[str, Any], now: dt.datetime) -> float:
    opened_ms = float(pos.get("opened_at_ms", 0.0))
    if opened_ms <= 0:
        return 0.0
    now_ms = now.timestamp() * 1000.0
    return max(0.0, (now_ms - opened_ms) / 3_600_000.0)


def migrate_ledger_schema(ledger: dict[str, Any], cfg: dict[str, Any], now: dt.datetime | None = None) -> dict[str, Any]:
    """Normalize older v1.0 ledger keys into v4.0 schema without losing history."""
    now = now or dt.datetime.now(dt.timezone.utc)
    eq = float(cfg["account"]["initial_equity_usd"])
    ledger["protocol_version"] = cfg["protocol_version"]
    ledger.setdefault("initial_equity", eq)
    ledger.setdefault("realized_equity", ledger.get("equity", eq))
    ledger.setdefault("equity", ledger["realized_equity"])
    ledger.setdefault("high_water_mark", ledger["equity"])
    ledger.setdefault("drawdown_pct", 0.0)
    ledger.pop("spot_inventory_btc", None)
    ledger.setdefault("day_key", ledger.get("utc_day", now.strftime("%Y-%m-%d")))
    ledger.setdefault("day_start_equity", ledger["equity"])
    ledger.setdefault("intraday_peak_equity", ledger["equity"])
    ledger.setdefault("week_key", ledger.get("utc_week", _utc_week_key(now)))
    ledger.setdefault("week_start_equity", ledger["equity"])
    ledger.pop("last_sell_inventory_4h_ts", None)
    ledger.setdefault("open_positions", [])
    ledger.setdefault("closed_trades", [])
    ledger.setdefault("audit_log", [])
    if "breakers" not in ledger:
        old_cb = ledger.pop("circuit_breakers", {}) or {}
        ledger["breakers"] = {
            "intraday_halted": bool(old_cb.get("intraday_halted", False)),
            "daily_halted": bool(old_cb.get("daily_halted", False)),
            "weekly_halted": bool(old_cb.get("weekly_halted", False)),
            "dd_tier1_active": bool(old_cb.get("dd_tier1_active", False)),
            "dd_tier2_locked": bool(old_cb.get("dd_tier2_locked", False)),
        }
    else:
        for k in ("intraday_halted", "daily_halted", "weekly_halted", "dd_tier1_active", "dd_tier2_locked"):
            ledger["breakers"].setdefault(k, False)
    return ledger


def init_ledger(cfg: dict[str, Any], now: dt.datetime | None = None) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    eq = float(cfg["account"]["initial_equity_usd"])
    return {
        "protocol_version": cfg["protocol_version"],
        "initial_equity": eq,
        "realized_equity": eq,
        "equity": eq,
        "high_water_mark": eq,
        "drawdown_pct": 0.0,
        "day_key": now.strftime("%Y-%m-%d"),
        "day_start_equity": eq,
        "intraday_peak_equity": eq,
        "week_key": _utc_week_key(now),
        "week_start_equity": eq,
        "breakers": {
            "intraday_halted": False,
            "daily_halted": False,
            "weekly_halted": False,
            "dd_tier1_active": False,
            "dd_tier2_locked": False,
        },
        "open_positions": [],
        "closed_trades": [],
        "audit_log": [
            {
                "ts": _utc_iso(now),
                "event": "LEDGER_INIT_V4",
                "detail": f"Initialized v{cfg['protocol_version']} paper ledger with ${eq:,.2f}",
            }
        ],
    }


def _close_fraction(
    ledger: dict[str, Any],
    pos: dict[str, Any],
    fraction: float,
    exit_price: float,
    reason: str,
    now: dt.datetime,
) -> float:
    close_btc = round(pos["size_btc"] * fraction, 6)
    if close_btc <= 0:
        return 0.0
    sign = 1.0 if pos["direction"] == "LONG" else -1.0
    pnl_usd = sign * (exit_price - pos["entry_price"]) * close_btc
    pnl_r = sign * (exit_price - pos["entry_price"]) / max(pos["initial_stop_dist"], 1e-9)
    ledger["realized_equity"] = round(ledger["realized_equity"] + pnl_usd, 2)
    pos["size_btc"] = round(pos["size_btc"] - close_btc, 6)
    pos["realized_pnl_usd"] = round(pos.get("realized_pnl_usd", 0.0) + pnl_usd, 2)
    pos["risk_pct"] = round(pos["risk_pct"] * max(0.0, 1.0 - fraction), 4)

    record = {
        "trade_id": pos["id"],
        "direction": pos["direction"],
        "entry_price": pos["entry_price"],
        "exit_price": round(exit_price, 2),
        "size_btc": close_btc,
        "pnl_usd": round(pnl_usd, 2),
        "r_multiple": round(pnl_r, 3),
        "reason": reason,
        "opened_at": pos["opened_at"],
        "closed_at": _utc_iso(now),
        "hold_hours": round(_hours_open(pos, now), 2),
        "partial": fraction < 0.999,
    }
    ledger["closed_trades"].append(record)
    ledger["audit_log"].append(
        {
            "ts": _utc_iso(now),
            "event": f"CLOSE_{pos['direction']}",
            "detail": f"{reason} @ {exit_price:,.1f} ({close_btc:.4f} BTC, PnL ${pnl_usd:+,.2f}, {pnl_r:+.2f}R)",
        }
    )
    return pnl_usd


def _update_equity_and_breakers(
    ledger: dict[str, Any],
    price: float,
    cfg: dict[str, Any],
    now: dt.datetime,
) -> None:
    unrealized = 0.0
    for pos in ledger["open_positions"]:
        sign = 1.0 if pos["direction"] == "LONG" else -1.0
        unrealized += sign * (price - pos["entry_price"]) * pos["size_btc"]
        pos["unrealized_pnl_usd"] = round(sign * (price - pos["entry_price"]) * pos["size_btc"], 2)

    eq = round(ledger["realized_equity"] + unrealized, 2)
    ledger["equity"] = eq
    if eq > ledger["high_water_mark"]:
        ledger["high_water_mark"] = eq
    if eq > ledger.get("intraday_peak_equity", eq):
        ledger["intraday_peak_equity"] = eq

    dd = (eq - ledger["high_water_mark"]) / ledger["high_water_mark"] if ledger["high_water_mark"] > 0 else 0.0
    ledger["drawdown_pct"] = round(dd * 100.0, 3)

    intraday_peak = ledger.get("intraday_peak_equity") or ledger["day_start_equity"] or eq
    intraday_pnl = (eq - intraday_peak) / intraday_peak if intraday_peak > 0 else 0.0
    day_pnl = (eq - ledger["day_start_equity"]) / ledger["day_start_equity"] if ledger["day_start_equity"] > 0 else 0.0
    wk_pnl = (eq - ledger["week_start_equity"]) / ledger["week_start_equity"] if ledger["week_start_equity"] > 0 else 0.0

    cb_cfg = cfg["circuit_breakers"]
    b = ledger["breakers"]

    if intraday_pnl <= cb_cfg["intraday_loss_limit_pct"] and not b.get("intraday_halted"):
        b["intraday_halted"] = True
        ledger["audit_log"].append(
            {
                "ts": _utc_iso(now),
                "event": "BREAKER_INTRADAY",
                "detail": f"Intraday loss {intraday_pnl*100:.2f}% breached {cb_cfg['intraday_loss_limit_pct']*100:.1f}% limit",
            }
        )

    if day_pnl <= cb_cfg["daily_loss_limit_pct"] and not b["daily_halted"]:
        b["daily_halted"] = True
        ledger["audit_log"].append(
            {
                "ts": _utc_iso(now),
                "event": "BREAKER_DAILY",
                "detail": f"Daily loss {day_pnl*100:.2f}% breached {cb_cfg['daily_loss_limit_pct']*100:.1f}% limit",
            }
        )

    if wk_pnl <= cb_cfg["weekly_loss_limit_pct"] and not b["weekly_halted"]:
        b["weekly_halted"] = True
        for pos in list(ledger["open_positions"]):
            _close_fraction(ledger, pos, 1.0, price, "WEEKLY_LOSS_FLATTEN", now)
        ledger["open_positions"] = [p for p in ledger["open_positions"] if p["size_btc"] > 1e-6]
        ledger["audit_log"].append(
            {
                "ts": _utc_iso(now),
                "event": "BREAKER_WEEKLY",
                "detail": f"Weekly loss {wk_pnl*100:.2f}% breached {cb_cfg['weekly_loss_limit_pct']*100:.1f}% -> flattened futures",
            }
        )

    if dd <= cb_cfg["drawdown_tier2_pct"] and not b["dd_tier2_locked"]:
        b["dd_tier2_locked"] = True
        b["dd_tier1_active"] = True
        for pos in list(ledger["open_positions"]):
            _close_fraction(ledger, pos, 1.0, price, "DD_TIER2_FLATTEN", now)
        ledger["open_positions"] = [p for p in ledger["open_positions"] if p["size_btc"] > 1e-6]
        ledger["audit_log"].append(
            {
                "ts": _utc_iso(now),
                "event": "BREAKER_DD_10",
                "detail": f"Drawdown {dd*100:.2f}% breached -10.0% -> flattened futures & locked pending manual review",
            }
        )
    elif dd <= cb_cfg["drawdown_tier1_pct"]:
        if not b["dd_tier1_active"]:
            b["dd_tier1_active"] = True
            ledger["audit_log"].append(
                {
                    "ts": _utc_iso(now),
                    "event": "BREAKER_DD_6",
                    "detail": f"Drawdown {dd*100:.2f}% breached -6.0% -> risk 0.2%, thresholds 75/25",
                }
            )
    else:
        if not b["dd_tier2_locked"] and dd > cb_cfg["drawdown_tier1_pct"] * 0.5:
            b["dd_tier1_active"] = False


def process_cycle(
    ledger: dict[str, Any],
    market_data: dict[str, Any],
    regime: dict[str, Any],
    cfg: dict[str, Any],
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Handle UTC rollovers, 4H trade management (stops/1.5R partial/8h-12h/24h/weekend/daily close), and breakers."""
    now = now or dt.datetime.now(dt.timezone.utc)
    migrate_ledger_schema(ledger, cfg, now)

    price = float(market_data["ticker"].get("price") or 0.0)
    if price <= 0:
        return ledger

    # UTC Day & Week rollovers
    day_key = now.strftime("%Y-%m-%d")
    wk_key = _utc_week_key(now)
    if ledger.get("day_key") != day_key:
        ledger["day_key"] = day_key
        ledger["day_start_equity"] = ledger["equity"]
        ledger["intraday_peak_equity"] = ledger["equity"]
        ledger["breakers"]["intraday_halted"] = False
        ledger["breakers"]["daily_halted"] = False
    if ledger.get("week_key") != wk_key:
        ledger["week_key"] = wk_key
        ledger["week_start_equity"] = ledger["equity"]
        ledger["breakers"]["weekly_halted"] = False

    h4 = (market_data.get("klines") or {}).get("4h") or []
    tm = cfg["trade_management"]
    th = cfg["timeframe_and_hold"]
    ema20_vals = ema_series([c["close"] for c in h4], tm["trail_ema_period_4h"]) if len(h4) >= tm["trail_ema_period_4h"] else []
    trail_ema = ema20_vals[-1] if ema20_vals else None

    score = float(regime.get("score", 50.0))
    long_th = float((regime.get("thresholds") or {}).get("long", cfg["regime"]["long_threshold"]))
    short_th = float((regime.get("thresholds") or {}).get("short", cfg["regime"]["short_threshold"]))
    is_weekend = now.weekday() >= 5
    wk_long = float(th["weekend_extreme_long"])
    wk_short = float(th["weekend_extreme_short"])

    for pos in list(ledger["open_positions"]):
        sign = 1.0 if pos["direction"] == "LONG" else -1.0
        dist = max(pos["initial_stop_dist"], 1e-9)
        cur_r = sign * (price - pos["entry_price"]) / dist
        pos["current_r"] = round(cur_r, 3)
        pos["max_favorable_r"] = round(max(float(pos.get("max_favorable_r", 0.0)), cur_r), 3)
        hours_open = _hours_open(pos, now)
        pos["hold_hours"] = round(hours_open, 2)

        # 1. Hard / trailing stop check
        stopped = (price <= pos["stop_price"]) if pos["direction"] == "LONG" else (price >= pos["stop_price"])
        if stopped:
            _close_fraction(ledger, pos, 1.0, pos["stop_price"], "HARD_OR_TRAIL_STOP", now)
            continue

        # 2. Maximum hold 24h exit (Section 3 & 7)
        if hours_open >= float(th["max_hold_hours"]):
            _close_fraction(ledger, pos, 1.0, price, "MAX_HOLD_24H_EXIT", now)
            continue

        # 3. Weekend rule (Section 3): weekend hold only if extreme >= 80 / <= 20 and size halved
        if is_weekend:
            extreme_ok = (pos["direction"] == "LONG" and score >= wk_long) or (
                pos["direction"] == "SHORT" and score <= wk_short
            )
            if not extreme_ok:
                _close_fraction(ledger, pos, 1.0, price, "WEEKEND_NON_EXTREME_EXIT", now)
                continue
            if not pos.get("weekend_halved"):
                _close_fraction(ledger, pos, 0.50, price, "WEEKEND_EXTREME_HALF_REDUCE", now)
                pos["weekend_halved"] = True

        # 4. Daily close rule (Section 3): any futures still open at next daily close is reduced/closed unless score moved further in favor
        opened_day = pos.get("opened_utc_day") or (pos.get("opened_at", "")[:10])
        if opened_day and day_key > opened_day and pos.get("daily_close_checked_day") != day_key:
            pos["daily_close_checked_day"] = day_key
            entry_score = float(pos.get("entry_regime_score", score))
            improved = (score > entry_score) if pos["direction"] == "LONG" else (score < entry_score)
            if not improved:
                _close_fraction(ledger, pos, 0.50, price, "DAILY_CLOSE_NO_IMPROVEMENT_REDUCE", now)
                if pos["size_btc"] <= 1e-6:
                    continue

        # 5. Opposing regime threshold exit (<= 32 for Long, >= 68 for Short)
        if pos["direction"] == "LONG" and score <= short_th:
            _close_fraction(ledger, pos, 1.0, price, "REGIME_OPPOSING_SHORT_EXIT", now)
            continue
        if pos["direction"] == "SHORT" and score >= long_th:
            _close_fraction(ledger, pos, 1.0, price, "REGIME_OPPOSING_LONG_EXIT", now)
            continue

        # 6. Time stops (Section 7): 8h reduce 50% if < +1R; 12h full exit if < +1R
        best_r = float(pos.get("max_favorable_r", cur_r))
        if hours_open >= float(tm["time_stop_exit_hours"]) and best_r < 1.0:
            _close_fraction(ledger, pos, 1.0, price, "TIME_STOP_12H_EXIT", now)
            continue
        if (
            hours_open >= float(tm["time_stop_reduce_hours"])
            and best_r < 1.0
            and not pos.get("time_stop_8h_reduced")
        ):
            _close_fraction(ledger, pos, float(tm["time_stop_reduce_pct"]), price, "TIME_STOP_8H_REDUCE", now)
            pos["time_stop_8h_reduced"] = True

        # 7. Move to breakeven at +1R & trail stop thereafter
        if cur_r >= tm["breakeven_trigger_r"] and not pos.get("breakeven_moved"):
            pos["stop_price"] = pos["entry_price"]
            pos["breakeven_moved"] = True
            ledger["audit_log"].append(
                {
                    "ts": _utc_iso(now),
                    "event": "STOP_TO_BREAKEVEN",
                    "detail": f"{pos['direction']} reached +1.0R -> stop moved to {pos['entry_price']:,.1f}",
                }
            )

        if pos.get("breakeven_moved") and trail_ema:
            if pos["direction"] == "LONG" and trail_ema > pos["stop_price"] and trail_ema < price:
                pos["stop_price"] = round(trail_ema, 1)
            elif pos["direction"] == "SHORT" and trail_ema < pos["stop_price"] and trail_ema > price:
                pos["stop_price"] = round(trail_ema, 1)

        # 8. Partial profit 45% at 1.5R
        if cur_r >= tm["partial_tp_r"] and not pos.get("partial_taken"):
            _close_fraction(ledger, pos, tm["partial_tp_pct"], price, "PARTIAL_TP_1.5R", now)
            pos["partial_taken"] = True

    ledger["open_positions"] = [p for p in ledger["open_positions"] if p["size_btc"] > 1e-6]
    _update_equity_and_breakers(ledger, price, cfg, now)
    ledger["audit_log"] = ledger["audit_log"][-100:]
    return ledger


def execute_signal_entry(
    ledger: dict[str, Any],
    signal: dict[str, Any],
    regime: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Open a paper futures trade if signal status is LONG or SHORT."""
    now = now or dt.datetime.now(dt.timezone.utc)
    status = signal.get("status")
    if status not in ("LONG", "SHORT"):
        return ledger
    prop = signal["proposal"]
    if not prop.get("valid") or prop.get("size_btc", 0) <= 0:
        return ledger

    pos = {
        "id": f"V4-{now.strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:4].upper()}",
        "direction": status,
        "entry_price": float(prop["entry_price"]),
        "stop_price": float(prop["stop_price"]),
        "initial_stop_price": float(prop["stop_price"]),
        "initial_stop_dist": abs(float(prop["entry_price"]) - float(prop["stop_price"])),
        "target1_price": float(prop["target1_price"]),
        "size_btc": float(prop["size_btc"]),
        "initial_size_btc": float(prop["size_btc"]),
        "notional_usd": float(prop["notional_usd"]),
        "leverage": float(prop["leverage"]),
        "risk_pct": float(prop["actual_risk_pct"]),
        "opened_at": _utc_iso(now),
        "opened_at_ms": int(now.timestamp() * 1000),
        "opened_utc_day": now.strftime("%Y-%m-%d"),
        "entry_regime_score": float((regime or {}).get("score", 50.0)),
        "weekend_halved": bool(prop.get("weekend_halved", False)),
        "breakeven_moved": False,
        "partial_taken": False,
        "time_stop_8h_reduced": False,
        "current_r": 0.0,
        "max_favorable_r": 0.0,
        "hold_hours": 0.0,
        "unrealized_pnl_usd": 0.0,
        "realized_pnl_usd": 0.0,
    }
    ledger["open_positions"].append(pos)
    ledger["audit_log"].append(
        {
            "ts": _utc_iso(now),
            "event": f"OPEN_{status}",
            "detail": f"{prop['size_btc']:.4f} BTC @ {prop['entry_price']:,.1f} | Stop {prop['stop_price']:,.1f} | Target {prop['target1_price']:,.1f} | Lev {prop['leverage']:.2f}x | Risk {prop['actual_risk_pct']:.2f}%",
        }
    )
    ledger["audit_log"] = ledger["audit_log"][-100:]
    return ledger


def compute_review_metrics(ledger: dict[str, Any]) -> dict[str, Any]:
    trades = ledger.get("closed_trades") or []
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] < 0]
    gross_win = sum(t["pnl_usd"] for t in wins)
    gross_loss = abs(sum(t["pnl_usd"] for t in losses))
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    win_rate = round(len(wins) / len(trades) * 100.0, 1) if trades else 0.0
    exp_r = round(sum(t["r_multiple"] for t in trades) / len(trades), 3) if trades else 0.0
    return {
        "total_closed_legs": len(trades),
        "win_rate_pct": win_rate,
        "profit_factor": pf,
        "expectancy_r": exp_r,
        "total_realized_pnl_usd": round(ledger["realized_equity"] - ledger["initial_equity"], 2),
    }


def reset_review_lock(ledger: dict[str, Any], cfg: dict[str, Any], now: dt.datetime | None = None) -> dict[str, Any]:
    """Manual operator reset after -10% DD lock."""
    now = now or dt.datetime.now(dt.timezone.utc)
    ledger["breakers"]["dd_tier2_locked"] = False
    ledger["breakers"]["dd_tier1_active"] = False
    ledger["high_water_mark"] = ledger["equity"]
    ledger["drawdown_pct"] = 0.0
    ledger["day_start_equity"] = ledger["equity"]
    ledger["intraday_peak_equity"] = ledger["equity"]
    ledger["week_start_equity"] = ledger["equity"]
    ledger["audit_log"].append(
        {
            "ts": _utc_iso(now),
            "event": "MANUAL_REVIEW_UNLOCK",
            "detail": f"Operator unlocked -10% drawdown halt at equity ${ledger['equity']:,.2f}",
        }
    )
    ledger["audit_log"] = ledger["audit_log"][-100:]
    return ledger
