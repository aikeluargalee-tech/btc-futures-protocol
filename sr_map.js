"use strict";

(function () {
  const PLAN_KEY = "btc_desk_f10_plan_v1";
  const LOG_KEY = "btc_desk_f10_log_v1";

  let LAST_STATE = null;
  let INIT_OPTS = {};
  let INTRADAY_OPEN = false;
  let INTRADAY_LOADING = false;
  let INTRADAY_DATA = null;
  let MATRIX_OPEN = false;
  let PLAN_OPEN = false;
  let GUIDE_OPEN = false;
  let REGIME_DEFS_OPEN = false;

  const DEFAULT_PLAN = {
    btcPct: 30,
    maxTranchePct: 15,
    cashTargetPct: 70,
    parking: "USDT Spot Sleeve",
    disruptionVeto: false,
    extraNote: "",
  };

  function loadPlan() {
    try {
      const raw = localStorage.getItem(PLAN_KEY);
      if (!raw) return { ...DEFAULT_PLAN };
      return { ...DEFAULT_PLAN, ...JSON.parse(raw) };
    } catch {
      return { ...DEFAULT_PLAN };
    }
  }

  function savePlan(plan) {
    try {
      localStorage.setItem(PLAN_KEY, JSON.stringify(plan));
    } catch {}
  }

  function loadLog() {
    try {
      const raw = localStorage.getItem(LOG_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  function saveLog(rows) {
    try {
      localStorage.setItem(LOG_KEY, JSON.stringify((rows || []).slice(0, 50)));
    } catch {}
  }

  let USER_PLAN = loadPlan();
  let RUN_LOG = loadLog();

  function escHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  function fmtUsd(v, d = 0) {
    return typeof v === "number" && isFinite(v)
      ? "$" + v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })
      : "—";
  }

  function fmtPct(v, d = 2) {
    return typeof v === "number" && isFinite(v) ? `${v >= 0 ? "+" : ""}${v.toFixed(d)}%` : "—";
  }

  function fmtNum(v, d = 1) {
    return typeof v === "number" && isFinite(v) ? v.toFixed(d) : "—";
  }

  function _toUtcSgtParts(ms) {
    const u = new Date(ms);
    const s = new Date(ms + 8 * 3600 * 1000);
    const pad2 = (n) => String(n).padStart(2, "0");
    const fmtD = (d) => `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`;
    const fmtT = (d) => `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}:${pad2(d.getUTCSeconds())}`;
    return {
      utc: `${fmtD(u)} ${fmtT(u)} UTC`,
      sgt: `${fmtD(s)} ${fmtT(s)} SGT`,
      shortPair: `${fmtT(u).slice(0, 5)} UTC / ${fmtT(s).slice(0, 5)} SGT`,
      dateShortPair: `${fmtD(u).slice(5)} ${fmtT(u).slice(0, 5)} UTC / ${fmtT(s).slice(0, 5)} SGT`,
    };
  }

  function fmtUtcSgt(isoOrMs, addMinutes = 0) {
    if (!isoOrMs) return { utc: "MISSING", sgt: "MISSING", shortPair: "MISSING", dateShortPair: "MISSING" };
    const ms = typeof isoOrMs === "number" ? isoOrMs : Date.parse(isoOrMs);
    if (!isFinite(ms)) return { utc: String(isoOrMs), sgt: "MISSING", shortPair: String(isoOrMs), dateShortPair: String(isoOrMs) };
    return _toUtcSgtParts(ms + addMinutes * 60 * 1000);
  }

  function getRefPrice(state) {
    const live = INIT_OPTS.getLivePrice ? INIT_OPTS.getLivePrice() : null;
    if (typeof live === "number" && isFinite(live) && live > 0) return live;
    const snap = state?.sr_bands?.ref_price ?? state?.ticker?.price;
    return typeof snap === "number" && isFinite(snap) && snap > 0 ? snap : null;
  }

  function liveDistPct(targetPrice, refPrice) {
    if (!(typeof targetPrice === "number" && isFinite(targetPrice) && typeof refPrice === "number" && refPrice > 0)) {
      return null;
    }
    return ((targetPrice - refPrice) / refPrice) * 100.0;
  }

  function computePullScore(usdM, distPct) {
    if (!(typeof usdM === "number" && isFinite(usdM) && typeof distPct === "number" && isFinite(distPct))) {
      return null;
    }
    const denom = Math.max(Math.abs(distPct), 0.15);
    return usdM / denom;
  }

  function get24hWickRange(state) {
    const h4 = (state?.charts?.h4 || []).slice(-6);
    const highs = h4.map((c) => c?.[2]).filter((v) => typeof v === "number" && isFinite(v));
    const lows = h4.map((c) => c?.[3]).filter((v) => typeof v === "number" && isFinite(v));
    const m = state?.spot_magnet?.metrics || {};
    const tk = state?.ticker || {};
    for (const v of [m.recent_3h_wick_high, tk.high24]) {
      if (typeof v === "number" && isFinite(v)) highs.push(v);
    }
    for (const v of [m.recent_3h_wick_low, tk.low24]) {
      if (typeof v === "number" && isFinite(v)) lows.push(v);
    }
    return {
      high24: highs.length ? Math.max(...highs) : null,
      low24: lows.length ? Math.min(...lows) : null,
    };
  }

  function classifyClusterFreshness(price, side, wick24) {
    if (!wick24 || !(typeof price === "number" && isFinite(price))) return "UNKNOWN";
    if (side === "upper" && wick24.high24 != null) {
      return wick24.high24 >= price * 0.999 ? "TESTED_24H" : "FRESH";
    }
    if (side === "lower" && wick24.low24 != null) {
      return wick24.low24 <= price * 1.001 ? "TESTED_24H" : "FRESH";
    }
    return "UNKNOWN";
  }

  function extractCrossDeskEvidence(state) {
    const v = (x) => (x === null || x === undefined || x === "" ? "MISSING" : x);
    const ts = state?.regime?.groups?.trend_structure || {};
    const sor = state?.state_of_regime || {};
    const sh = state?.spot_shield || {};
    const shInd = sh.sleeve1?.indicators || {};
    const smM = state?.spot_magnet?.metrics || {};
    const ov = state?.context_overlays || {};
    const etfReg = ov.etf_flow_regime || {};
    const mtL = ov.market_time_l || {};
    const etf = state?.etf || {};
    const cr = state?.cortex_rhyme || {};
    const crDiag = cr.diagnostics || {};
    const cr24 = cr.after_similar_setups?.["24h"] || {};
    const crEdge24 = cr.edge_vs_baseline?.["24h"] || {};
    const pmG = state?.positioning_matrix_g || {};

    const dBias = ts.daily_bias || state?.regime?.daily_bias || null;
    const h4Struct = ts.h4_structure || null;
    const d1Struct = ts.daily_structure || null;
    const score = state?.regime?.score ?? null;

    let trendCue = "Range / balanced chop — respect outer 4H/1D bands.";
    if (dBias === "BEAR" && h4Struct === "BULLISH_HH_HL") {
      trendCue = "1D downtrend vs 4H bounce — wait for 4H close before trusting upside.";
    } else if (dBias === "BEAR") {
      trendCue = "Downtrend bias — don't catch falling floors before sweep + reclaim close.";
    } else if (dBias === "BULL" && h4Struct === "BULLISH_HH_HL") {
      trendCue = "Aligned uptrend — don't fade trend just because a near ceiling appears.";
    } else if (dBias === "BULL") {
      trendCue = "Constructive 1D bias — look for clean higher-low sweeps on 4H.";
    }

    const oi24 = smM.oi_change_24h_pct;
    const etf5d = etf.sum5_usd_m;
    const spotCvd = smM.spot_cvd_ratio;
    let driverCue = "Mixed spot & derivatives flow — check closed candle confirmation.";
    if (etfReg.regime === "NEW SHORTS" || (typeof etf5d === "number" && etf5d <= -500 && typeof oi24 === "number" && oi24 > 1)) {
      driverCue = "ETF outflows + rising Perp OI — short leverage building; caution on bounces.";
    } else if (typeof spotCvd === "number" && spotCvd >= 1.05 && typeof etf5d === "number" && etf5d > 0) {
      driverCue = "Spot demand + ETF inflows supporting floors.";
    } else if (typeof oi24 === "number" && oi24 > 2.0 && typeof spotCvd === "number" && spotCvd < 1.0) {
      driverCue = "Leverage leading spot — higher wick/sweep risk around magnets.";
    }

    const nextEvt = (state?.macro_calendar || [])
      .map((ev) => {
        const minsLive = typeof ev.ts_ms === "number" ? (ev.ts_ms - Date.now()) / 60000 : ev.minutes_away;
        return { ...ev, live_minutes_away: typeof minsLive === "number" ? +minsLive.toFixed(1) : null };
      })
      .find((ev) => ev.live_minutes_away == null || ev.live_minutes_away >= -60) || null;

    return {
      trendCue,
      driverCue,
      regime: {
        code: v(sor.code),
        name: v(sor.name),
        bias: v(sor.bias),
        regime_4h_score: v(score),
        daily_bias: v(dBias),
        daily_structure: v(d1Struct),
        h4_structure: v(h4Struct),
        vol_modifier: v(sor.volatility_modifier),
        flow_modifier: v(sor.flow_modifier),
        all_regimes: Array.isArray(sor.all_regimes) ? sor.all_regimes : [],
        shield_120d_ema: v(shInd.macro_120d_ema),
        dist_to_120d_ema_pct: v(shInd.dist_to_macro_ema_pct),
        shield_btc_pct: v(sh.portfolio?.target_btc_pct),
      },
      flow: {
        etf_latest_settled_date: v(etf.latest_date),
        etf_1d_usd_m: v(etf.latest_usd_m),
        etf_5d_usd_m: v(etf5d),
        etf_flow_regime: v(etfReg.regime),
        coinbase_premium_bps: v(smM.coinbase_premium_bps),
        coinbase_premium_usd: v(smM.coinbase_premium_usd),
        long_short_account_ratio: v(smM.long_short_account_ratio),
        ls_ratio_percentile_72h: v(smM.ls_ratio_percentile_72h),
        spot_cvd_ratio: v(spotCvd),
        spot_cvd_slope_7d: v(smM.spot_cvd_slope_7d),
        perp_cvd_slope_24h: v(smM.perp_cvd_slope_24h),
        perp_cvd_trend: v(smM.perp_cvd_trend),
        spot_vol_ratio_vs_ma20: v(smM.spot_vol_ratio),
        oi_change_4h_pct: v(smM.oi_change_4h_pct),
        oi_change_24h_pct: v(oi24),
        funding_rate_8h_pct: v(smM.funding_rate_8h_pct ?? state?.derivatives?.current_rate_pct),
      },
      session_macro: {
        next_high_impact_event: nextEvt,
        day_of_week: v(mtL.day_of_week),
        awake_state: v(mtL.awake_state),
        expected_day_range_pct: v(mtL.expected_day_range_pct),
        expected_hour_range_pct: v(mtL.expected_hour_range_pct),
        is_weekend_utc: mtL.is_weekend_utc ?? state?.regime?.is_weekend_utc ?? "MISSING",
      },
      historical_odds: {
        project_g_summary: v(pmG.summary_line),
        project_g_n_weeks: v(pmG.active_cell?.n),
        rhyme_posture: v(crDiag.posture_verdict),
        rhyme_24h_median_pct: v(cr24.median_pct),
        rhyme_24h_up_share_pct: v(cr24.up_share),
        rhyme_24h_lift_se_pts: v(crEdge24.lift_se_pts),
      },
    };
  }

  function evaluateDecisionGate(state, refPrice, ev, staircase, plan) {
    const sr = state?.sr_bands;
    const ageMin = typeof state?.updated_at_ms === "number" ? (Date.now() - state.updated_at_ms) / 60000 : null;
    const isStale = ageMin != null && ageMin > 65;
    const missingCore = !sr || sr.status !== "LIVE" || !(typeof refPrice === "number" && refPrice > 0);
    const nextEvt = ev.session_macro.next_high_impact_event;
    const macroBlackout =
      nextEvt &&
      typeof nextEvt.live_minutes_away === "number" &&
      nextEvt.live_minutes_away >= -15 &&
      nextEvt.live_minutes_away <= 60;
    const disruptionVeto = Boolean(plan?.disruptionVeto);

    const vetos = [];
    if (isStale) vetos.push(`Packet is ${Math.round(ageMin)}m old (>65m stale cutoff)`);
    if (missingCore) vetos.push("Core S/R bands or live BTC reference price missing");
    if (macroBlackout) vetos.push(`USD Event Blackout (${nextEvt.title} in ${Math.round(nextEvt.live_minutes_away)}m)`);
    if (disruptionVeto) vetos.push("Manual Disruption Veto active (exchange/macro shock toggle)");

    // Exact Trigger & Invalidation Prices from Staircase (fallback to core timeframes)
    const nearestCeil = staircase.ceilings.length ? staircase.ceilings[staircase.ceilings.length - 1] : null;
    const secondCeil = staircase.ceilings.length >= 2 ? staircase.ceilings[staircase.ceilings.length - 2] : null;
    const nearestFloor = staircase.floors[0] || null;
    const nextFloor = staircase.floors[1] || null;

    const near4hFloor = sr?.timeframes?.["4H"]?.support?.[0] || nearestFloor;
    const near1dFloor = sr?.timeframes?.["1D"]?.support?.[0] || nextFloor;

    const ceilingTop = nearestCeil?.high ?? null;
    const floorTopReclaim = near4hFloor?.high ?? nearestFloor?.high ?? null;
    const floorBottomBreak = nearestFloor?.low ?? null;
    const deepFloorBand = nextFloor ? `${fmtUsd(nextFloor.low)}–${fmtUsd(nextFloor.high)}` : (near1dFloor ? `${fmtUsd(near1dFloor.low)}–${fmtUsd(near1dFloor.high)}` : "next lower shelf");
    const nextCeilBand = secondCeil ? `${fmtUsd(secondCeil.low)}–${fmtUsd(secondCeil.high)}` : "next overhead resistance";

    const rCode = ev.regime.code;
    const dBias = ev.regime.daily_bias;
    const etf5d = ev.flow.etf_5d_usd_m;
    const dist120d = ev.regime.dist_to_120d_ema_pct;

    let macroPermission = "AMBER";
    if (
      (typeof etf5d === "number" && etf5d <= -500) ||
      rCode === "R4" ||
      rCode === "R5" ||
      (dBias === "BEAR" && typeof dist120d === "number" && dist120d < -3)
    ) {
      macroPermission = "RED";
    } else if (
      typeof etf5d === "number" &&
      etf5d >= 250 &&
      dBias === "BULL" &&
      rCode === "R1" &&
      (typeof dist120d !== "number" || dist120d > 0)
    ) {
      macroPermission = "GREEN";
    }

    const pressingCeiling = Boolean(nearestCeil && (nearestCeil.inZone || (typeof nearestCeil.distPct === "number" && nearestCeil.distPct <= 1.0)));
    const lowerOverlaps = (sr?.magnet_overlaps || []).filter((o) => o.side === "LOWER_BELOW_SUPPORT");
    const hasLowerMagnetRisk = lowerOverlaps.length > 0;
    const shieldClosed = typeof dist120d === "number" && dist120d < 0;

    let posture = "REDUCED SIZE / WAIT";
    let postureCls = "warn";
    let why = "Mixed signals between regime and structure — wait for a clean completed 4H close before staging tactical USDT.";

    if (vetos.length > 0) {
      posture = "STAND ASIDE (VETO)";
      postureCls = "dn";
      why = `Data/event veto triggered: ${vetos.join("; ")}.`;
    } else if (macroPermission === "RED" && (pressingCeiling || hasLowerMagnetRisk || shieldClosed)) {
      posture = "STAND ASIDE";
      postureCls = "dn";
      const parts = [];
      parts.push(`${rCode !== "MISSING" ? rCode : "Bear"} regime / RED ETF backdrop`);
      if (pressingCeiling) parts.push("price pressing overhead resistance (Trap #01)");
      if (hasLowerMagnetRisk) parts.push("unswept lower long magnets beneath thin support (Trap #05)");
      if (shieldClosed) parts.push("below 120D EMA Bear Shield");
      why = `${parts.join(", ")} — keep tactical USDT protected until structure or flows flip.`;
    } else if (macroPermission === "GREEN" && !pressingCeiling && !hasLowerMagnetRisk) {
      posture = "CONDITIONS ALIGNED (STAGED)";
      postureCls = "up";
      why = `Constructive ${rCode} trend + positive ETF flows with room below next resistance — eligible for staged 1.0x spot execution.`;
    } else {
      posture = "REDUCED SIZE / WAIT";
      postureCls = "warn";
      why = hasLowerMagnetRisk
        ? "Lower liquidation magnets sit just below nearby support — let the sweep & 4H reclaim print first, and size smaller."
        : "No clean asymmetric window yet — wait for completed 4H close above ceiling or sweep-and-reclaim off floor.";
    }

    const triggerLine = ceilingTop && floorTopReclaim
      ? `Bull flip: 4H close above ${fmtUsd(ceilingTop, 0)} (opens ${nextCeilBand}) | Sweep-reclaim: dip below floor then 4H close back above ${fmtUsd(floorTopReclaim, 0)}.`
      : "Wait for a completed 4H candle close cleanly above the nearest ceiling or reclaiming swept support.";

    const invalidationLine = floorBottomBreak
      ? `4H close below ${fmtUsd(floorBottomBreak, 0)} breaks near floor → protect cash toward ${plan.cashTargetPct}% (${plan.parking}); next floor ${deepFloorBand}.`
      : `Daily / 4H close below primary support shifts posture to full USDT defense (${plan.cashTargetPct}% target).`;

    return {
      posture,
      postureCls,
      vetoActive: vetos.length > 0,
      vetos,
      isStale,
      ageMinutes: ageMin != null ? Math.round(ageMin) : null,
      macroPermission,
      pressingCeiling,
      hasLowerMagnetRisk,
      priorityRule: "1. Bad Data/Disruption = Veto → 2. Regime Filter → 3. S/R + Magnets Timing → 4. 4H/1D Falsification Close Wins",
      why,
      triggerLine,
      invalidationLine,
      levels: { ceilingTop, floorTopReclaim, floorBottomBreak, deepFloorBand, nextCeilBand },
    };
  }

  function calcAtr14Client(bars) {
    if (!Array.isArray(bars) || bars.length < 2) return null;
    const trs = [];
    for (let i = 1; i < bars.length; i += 1) {
      const cur = bars[i];
      const prevClose = bars[i - 1].close;
      trs.push(Math.max(cur.high - cur.low, Math.abs(cur.high - prevClose), Math.abs(cur.low - prevClose)));
    }
    const win = trs.slice(-14);
    return win.length ? win.reduce((a, b) => a + b, 0) / win.length : null;
  }

  function computeClientTfBands(bars, refPrice, tfLabel, role) {
    if (!Array.isArray(bars) || !bars.length || !(refPrice > 0)) {
      return { tf: tfLabel, label: tfLabel, role, bars: 0, atr14_usd: null, atr14_pct: null, resistance: [], support: [] };
    }
    const win = bars.slice(-120);
    const atr14 = calcAtr14Client(win) || refPrice * 0.006;
    const atr14Pct = (atr14 / refPrice) * 100.0;
    const pad = Math.max(refPrice * 0.001, Math.min(refPrice * 0.0085, 0.18 * atr14));
    const clusterTol = Math.max(refPrice * 0.0035, Math.min(refPrice * 0.015, 0.55 * atr14));
    const span = 2;

    const points = [];
    for (let i = span; i < win.length - span; i += 1) {
      const curH = win[i].high;
      const curL = win[i].low;
      let isPivotH = true;
      let isPivotL = true;
      for (let j = i - span; j <= i + span; j += 1) {
        if (win[j].high > curH) isPivotH = false;
        if (win[j].low < curL) isPivotL = false;
      }
      if (isPivotH) points.push({ price: curH, ts: win[i].ts, kind: "H" });
      if (isPivotL) points.push({ price: curL, ts: win[i].ts, kind: "L" });
    }
    const lastBar = win[win.length - 1];
    points.push({ price: lastBar.high, ts: lastBar.ts, kind: "H" });
    points.push({ price: lastBar.low, ts: lastBar.ts, kind: "L" });

    points.sort((a, b) => a.price - b.price);
    const groups = [[points[0]]];
    for (let i = 1; i < points.length; i += 1) {
      const anchor = groups[groups.length - 1][0].price;
      if (Math.abs(points[i].price - anchor) <= clusterTol) groups[groups.length - 1].push(points[i]);
      else groups.push([points[i]]);
    }

    const res = [];
    const sup = [];
    for (const grp of groups) {
      const loRaw = Math.min(...grp.map((p) => p.price));
      const hiRaw = Math.max(...grp.map((p) => p.price));
      const mid = +(grp.reduce((s, p) => s + p.price, 0) / grp.length).toFixed(1);
      const halfSpan = Math.min(Math.max((hiRaw - loRaw) * 0.5 + pad * 0.5, pad * 0.65), refPrice * 0.011);
      const lowB = +(mid - halfSpan).toFixed(1);
      const highB = +(mid + halfSpan).toFixed(1);
      const kinds = new Set(grp.map((p) => p.kind));
      const pivotKind = kinds.size === 2 ? "S/R FLIP" : (kinds.has("H") ? "HIGH" : "LOW");
      const touches = grp.length;
      const zone = {
        tf: tfLabel,
        side: mid >= refPrice ? "resistance" : "support",
        low: lowB,
        mid,
        high: highB,
        touches,
        distance_pct: +(((mid - refPrice) / refPrice) * 100.0).toFixed(2),
        in_zone: lowB <= refPrice && refPrice <= highB,
        pivot_kind: pivotKind,
        strength: touches >= 3 ? "STRONG" : (touches === 2 ? "TESTED" : "SINGLE"),
      };
      if (mid >= refPrice) res.push(zone);
      else sup.push(zone);
    }

    res.sort((a, b) => a.mid - b.mid);
    sup.sort((a, b) => b.mid - a.mid);
    return {
      tf: tfLabel,
      label: tfLabel,
      role,
      bars: win.length,
      atr14_usd: +atr14.toFixed(1),
      atr14_pct: +atr14Pct.toFixed(2),
      resistance: res.slice(0, 3),
      support: sup.slice(0, 3),
    };
  }

  async function fetchLiveIntradayBands(state) {
    if (INTRADAY_LOADING) return;
    INTRADAY_LOADING = true;
    render(state);

    const refPrice = getRefPrice(state) || state?.ticker?.price || 0;
    const specs = [
      { key: "12H", interval: "12h", role: "Session Half-Day Bridge (Live BinanceVision)" },
      { key: "30m", interval: "30m", role: "Intraday Scalp Noise (Live BinanceVision)" },
      { key: "15m", interval: "15m", role: "Micro Execution Noise (Live BinanceVision)" },
    ];
    try {
      const nowMs = Date.now();
      const results = await Promise.all(
        specs.map(async (sp) => {
          const url = `https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=${sp.interval}&limit=120`;
          const r = await fetch(url, { cache: "no-store" });
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          const raw = await r.json();
          const closed = (Array.isArray(raw) ? raw : [])
            .filter((row) => row.length >= 7 && Number(row[6]) <= nowMs)
            .map((row) => ({
              ts: Number(row[0]),
              open: Number(row[1]),
              high: Number(row[2]),
              low: Number(row[3]),
              close: Number(row[4]),
              volume: Number(row[5]),
            }));
          return [sp.key, computeClientTfBands(closed, refPrice, sp.key, sp.role)];
        })
      );
      const tfMap = {};
      for (const [k, val] of results) tfMap[k] = val;
      const tsNow = _toUtcSgtParts(Date.now());
      INTRADAY_DATA = {
        source: `Live Closed Bars @ ${tsNow.shortPair} (BinanceVision)`,
        error: null,
        timeframes: tfMap,
      };
    } catch (err) {
      INTRADAY_DATA = {
        source: "Hourly Snapshot Fallback (live browser fetch blocked/offline)",
        error: String(err?.message || err),
        timeframes: state?.sr_bands?.intraday_snapshot || null,
      };
    } finally {
      INTRADAY_LOADING = false;
      render(LAST_STATE);
    }
  }

  function buildUnifiedStaircase(sr, refPrice, overlaps) {
    if (!sr?.timeframes) return { ceilings: [], floors: [] };

    const overlapByKey = new Map();
    for (const ov of overlaps || []) {
      const k = `${ov.side === "LOWER_BELOW_SUPPORT" ? "support" : "resistance"}|${ov.support_tf}|${ov.support_mid}`;
      overlapByKey.set(k, ov);
    }

    const confs = sr.confluence_zones || { resistance: [], support: [] };
    const collectSide = (side) => {
      const usedZones = new Set();
      const rows = [];

      for (const c of confs[side] || []) {
        rows.push({
          isConfluence: true,
          tfs: c.timeframes || [],
          low: c.low,
          mid: c.mid,
          high: c.high,
          touches: c.total_touches,
          strength: `${c.tf_count}x CONFLUENCE`,
          pivotKind: "MULTI-TF",
          overlap: null,
        });
        for (const tfKey of sr.core_order || ["1W", "1D", "4H", "1H"]) {
          for (const z of sr.timeframes?.[tfKey]?.[side] || []) {
            if (z.mid >= c.low && z.mid <= c.high) usedZones.add(`${tfKey}|${z.mid}`);
          }
        }
      }

      for (const tfKey of sr.core_order || ["1W", "1D", "4H", "1H"]) {
        for (const z of sr.timeframes?.[tfKey]?.[side] || []) {
          const zKey = `${tfKey}|${z.mid}`;
          const ov = overlapByKey.get(`${side}|${tfKey}|${z.mid}`) || null;
          if (usedZones.has(zKey)) {
            if (ov) {
              const targetRow = rows.find((r) => z.mid >= r.low && z.mid <= r.high);
              if (targetRow && !targetRow.overlap) targetRow.overlap = ov;
            }
            continue;
          }
          rows.push({
            isConfluence: false,
            tfs: [z.tf],
            low: z.low,
            mid: z.mid,
            high: z.high,
            touches: z.touches,
            strength: z.strength,
            pivotKind: z.pivot_kind || "SWING",
            overlap: ov,
          });
        }
      }

      for (const r of rows) {
        r.distPct = refPrice ? liveDistPct(r.mid, refPrice) : null;
        r.inZone = typeof refPrice === "number" && r.low <= refPrice && refPrice <= r.high;
      }

      if (side === "resistance") {
        return rows
          .filter((r) => !refPrice || r.mid >= refPrice || r.inZone)
          .sort((a, b) => a.mid - b.mid)
          .slice(0, 4)
          .sort((a, b) => b.mid - a.mid);
      }
      return rows
        .filter((r) => !refPrice || r.mid < refPrice)
        .sort((a, b) => b.mid - a.mid)
        .slice(0, 4);
    };

    return {
      ceilings: collectSide("resistance"),
      floors: collectSide("support"),
    };
  }

  function renderBandRow(z, refPrice, side) {
    const dist = liveDistPct(z.mid, refPrice);
    const inZone = typeof refPrice === "number" && z.low <= refPrice && refPrice <= z.high;
    const distCls = side === "resistance" ? "dn" : "up";
    return `
      <div class="srmap-band-row ${inZone ? "in-zone" : ""}">
        <div class="srmap-band-left">
          <span class="srmap-band-px">${fmtUsd(z.low, 0)} &ndash; ${fmtUsd(z.high, 0)}</span>
          <span class="mut">mid ${fmtUsd(z.mid, 0)} · ${z.touches || 1} touch${z.touches === 1 ? "" : "es"}${z.pivot_kind === "S/R FLIP" ? " · S/R FLIP" : ""}</span>
        </div>
        <div class="srmap-band-right">
          ${inZone ? `<span class="badge warn">IN ZONE</span>` : ""}
          <span class="badge ${distCls}">${fmtPct(dist, 2)}</span>
        </div>
      </div>
    `;
  }

  function renderTfCard(tfData, refPrice) {
    if (!tfData) return "";
    const res = tfData.resistance || [];
    const sup = tfData.support || [];
    return `
      <div class="srmap-tf-card">
        <div class="srmap-tf-head">
          <div>
            <span class="srmap-tf-pill">${escHtml(tfData.tf)}</span>
            <span class="srmap-tf-role">${escHtml(tfData.role || "")}</span>
          </div>
          <span class="mut">${tfData.bars || 0} bars · ATR14 ${tfData.atr14_usd != null ? fmtUsd(tfData.atr14_usd, 0) + " (" + fmtNum(tfData.atr14_pct, 2) + "%)" : "—"}</span>
        </div>
        <div class="srmap-tf-sub">&#9650; Overhead Resistance (Ceilings)</div>
        ${res.length ? res.map((z) => renderBandRow(z, refPrice, "resistance")).join("") : `<div class="mut" style="padding:4px 0;">No closed resistance zones found in lookback.</div>`}
        <div class="srmap-tf-sub" style="margin-top:8px;">&#9660; Underlying Support (Floors)</div>
        ${sup.length ? sup.map((z) => renderBandRow(z, refPrice, "support")).join("") : `<div class="mut" style="padding:4px 0;">No closed support zones found in lookback.</div>`}
      </div>
    `;
  }

  function renderStaircaseRow(r, side) {
    const isRes = side === "resistance";
    return `
      <div class="srmap-stair-row ${isRes ? "ceil" : "floor"} ${r.isConfluence ? "conf" : ""} ${r.inZone ? "in-zone" : ""}">
        <div class="srmap-stair-tfs">
          ${r.tfs.map((tf) => `<span class="srmap-tf-pill">${escHtml(tf)}</span>`).join("")}
          ${r.isConfluence ? `<span class="badge up">CONFLUENCE</span>` : ""}
          ${r.pivotKind === "S/R FLIP" ? `<span class="badge">S/R FLIP</span>` : ""}
          ${r.overlap ? `<span class="badge dn">${r.overlap.side === "LOWER_BELOW_SUPPORT" ? "MAGNET BELOW" : "MAGNET ABOVE"}</span>` : ""}
        </div>
        <div class="srmap-stair-mid">
          <strong>${fmtUsd(r.low, 0)} &ndash; ${fmtUsd(r.high, 0)}</strong>
          <span class="mut">mid ${fmtUsd(r.mid, 0)} · ${r.touches} touch${r.touches === 1 ? "" : "es"}</span>
        </div>
        <div class="srmap-stair-dist">
          ${r.inZone ? `<span class="badge warn">PRICE INSIDE</span>` : ""}
          <span class="badge ${isRes ? "dn" : "up"}">${fmtPct(r.distPct, 2)}</span>
        </div>
      </div>
    `;
  }

  function renderClusterBarList(rows, maxUsdM, refPrice, side, isModeled, wick24) {
    if (!rows.length) return `<p class="mut" style="margin:6px 0 0;">No clusters reported on this side.</p>`;
    return rows
      .map((c) => {
        const usdM = c.usd_m;
        const pctWidth = maxUsdM > 0 && typeof usdM === "number" ? Math.max(6, Math.min(100, (usdM / maxUsdM) * 100)) : 8;
        const dist = liveDistPct(c.price, refPrice);
        const pull = computePullScore(usdM, dist);
        const farTag = typeof dist === "number" && Math.abs(dist) >= 6.0;
        const fresh = classifyClusterFreshness(c.price, side, wick24);
        const barCls = side === "upper" ? "upper" : "lower";
        return `
          <div class="srmap-liq-item">
            <div class="srmap-liq-top">
              <div>
                <strong>${escHtml(c.label)}</strong>
                <span class="mut"> · ${fmtUsd(c.price, 0)}${c.range ? ` (${fmtUsd(c.range[0], 0)}–${fmtUsd(c.range[1], 0)})` : ""}</span>
              </div>
              <div class="srmap-liq-badges">
                ${isModeled ? `<span class="badge">MODELED</span>` : `<span class="badge">EXACT</span>`}
                ${fresh === "FRESH" ? `<span class="badge fresh">FRESH</span>` : fresh === "TESTED_24H" ? `<span class="badge tested">TESTED 24H</span>` : ""}
                ${farTag ? `<span class="badge warn">FAR &ge;6%</span>` : ""}
                <span class="badge ${side === "upper" ? "dn" : "up"}">${fmtPct(dist, 2)}</span>
              </div>
            </div>
            <div class="srmap-liq-bar-row">
              <div class="srmap-liq-track">
                <div class="srmap-liq-fill ${barCls}" style="width:${pctWidth.toFixed(1)}%;"></div>
              </div>
              <div class="srmap-liq-metrics">
                <b>$${fmtNum(usdM, 1)}M</b> · Pull ${pull != null ? pull.toFixed(1) : "—"}
              </div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function renderLiquidationSection(state, refPrice, wick24) {
    const cmc = state?.derivatives?.cmc_liquidations || null;
    const cf = cmc?.cumulative_fuel || {};
    const rl = cmc?.realized || {};
    const sm = state?.spot_magnet || {};
    const mag = sm.magnets || {};
    const ladder = mag.liquidation_ladder || [];

    const cmcShorts = (cmc?.tactical_short_clusters_within_8pct || [])
      .map((c) => ({ label: `Hyperliquid ${c.leverage || "?"}x Shorts`, price: c.price, range: c.range, usd_m: c.usd_m }))
      .sort((a, b) => a.price - b.price);
    const cmcLongs = (cmc?.tactical_long_clusters_within_8pct || [])
      .map((c) => ({ label: `Hyperliquid ${c.leverage || "?"}x Longs`, price: c.price, range: c.range, usd_m: c.usd_m }))
      .sort((a, b) => b.price - a.price);
    const cmcMax = Math.max(1, ...[...cmcShorts, ...cmcLongs].map((x) => Number(x.usd_m) || 0));

    const modUpper = ladder
      .filter((x) => x.side === "upper")
      .map((x) => ({ label: `Modelled ${x.tier || x.leverage}`, price: x.price, usd_m: x.estimated_vol_m }))
      .sort((a, b) => a.price - b.price);
    const modLower = ladder
      .filter((x) => x.side === "lower")
      .map((x) => ({ label: `Modelled ${x.tier || x.leverage}`, price: x.price, usd_m: x.estimated_vol_m }))
      .sort((a, b) => b.price - a.price);
    const modMax = Math.max(1, ...[...modUpper, ...modLower].map((x) => Number(x.usd_m) || 0));

    const imb = mag.immediate_imbalance_ratio;
    const ladImb = mag.total_ladder_imbalance_ratio;
    const biasTag = cf.squeeze_bias_2pct || "BALANCED";

    return `
      <div class="grid-2">
        <div class="card">
          <div class="srmap-sec-head">
            <div>
              <h2>CMC Exact Liquidation Map (Hyperliquid + Realized)</h2>
              <div class="mut">Real open-position clusters within ±8% of spot · Source: ${escHtml(cmc?.source || "CoinMarketCap")}</div>
            </div>
            <span class="badge ${String(biasTag).includes("LONG_FLUSH") ? "dn" : "warn"}">${escHtml(biasTag)}</span>
          </div>
          <div class="srmap-fuel-strip">
            <div><span class="mut">Shorts &le;2% / &le;5%:</span> <b>$${fmtNum(cf.shorts_within_2pct_usd_m, 1)}M / $${fmtNum(cf.shorts_within_5pct_usd_m, 1)}M</b></div>
            <div><span class="mut">Longs &le;2% / &le;5%:</span> <b>$${fmtNum(cf.longs_within_2pct_usd_m, 1)}M / $${fmtNum(cf.longs_within_5pct_usd_m, 1)}M</b></div>
            <div><span class="mut">24h Realized Flush:</span> <b>$${fmtNum(rl.h24_total_usd_m, 1)}M (${fmtNum(rl.h24_long_flush_pct, 0)}% Longs)</b></div>
          </div>
          <div class="srmap-tf-sub" style="margin-top:8px;">&#9650; Upper Short Clusters (Short Liquidations Above)</div>
          ${renderClusterBarList(cmcShorts, cmcMax, refPrice, "upper", false, wick24)}
          <div class="srmap-tf-sub" style="margin-top:10px;">&#9660; Lower Long Clusters (Long Liquidations Below)</div>
          ${renderClusterBarList(cmcLongs, cmcMax, refPrice, "lower", false, wick24)}
          ${
            cmc?.largest_macro_long_cluster || cmc?.largest_macro_short_cluster
              ? `<div class="mut" style="margin-top:8px;padding-top:6px;border-top:1px dashed var(--line);">
                  Macro Peaks — Short: <b>${fmtUsd(cmc?.largest_macro_short_cluster?.price, 0)} ($${fmtNum(cmc?.largest_macro_short_cluster?.usd_m, 1)}M)</b>
                  · Long: <b>${fmtUsd(cmc?.largest_macro_long_cluster?.price, 0)} ($${fmtNum(cmc?.largest_macro_long_cluster?.usd_m, 1)}M)</b>
                </div>`
              : ""
          }
        </div>

        <div class="card">
          <div class="srmap-sec-head">
            <div>
              <h2>Modeled 10x–100x Liquidation Ladder (F3 Estimates)</h2>
              <div class="mut">Estimated leverage buckets anchored to swing pivots · Labelled MODELED (never added to CMC Exact)</div>
            </div>
            <span class="badge">${typeof imb === "number" ? imb.toFixed(1) + "x Immed Skew" : "MODELED"}</span>
          </div>
          <div class="srmap-fuel-strip">
            <div><span class="mut">Upper 10x–100x Sum:</span> <b>$${fmtNum(mag.total_ladder_upper_vol_m, 1)}M</b></div>
            <div><span class="mut">Lower 10x–100x Sum:</span> <b>$${fmtNum(mag.total_ladder_lower_vol_m, 1)}M</b></div>
            <div><span class="mut">Ladder Skew:</span> <b>${typeof ladImb === "number" ? ladImb.toFixed(2) + "x" : "—"} (${escHtml(mag.dominant_magnet || "Balanced")})</b></div>
          </div>
          <div class="srmap-tf-sub" style="margin-top:8px;">&#9650; Modeled Short Tiers Above Spot</div>
          ${renderClusterBarList(modUpper, modMax, refPrice, "upper", true, wick24)}
          <div class="srmap-tf-sub" style="margin-top:10px;">&#9660; Modeled Long Tiers Below Spot</div>
          ${renderClusterBarList(modLower, modMax, refPrice, "lower", true, wick24)}
          <div class="mut" style="margin-top:8px;padding-top:6px;border-top:1px dashed var(--line);">
            Pull Score = <code>Size ($M) / max(|Dist %|, 0.15)</code>. Magnets show fuel, not a must-visit — <b>FRESH</b> pools pull harder than <b>TESTED 24H</b> pools.
          </div>
        </div>
      </div>
    `;
  }

  function renderDecisionHero(gate, plan) {
    return `
      <div class="card srmap-decision-hero ${gate.postureCls}">
        <div class="srmap-sec-head">
          <div>
            <div class="srmap-ctx-kicker">BLOCK 1 · FINAL 1.0X SPOT DECISION GATE (SMR PRIORITY)</div>
            <div class="srmap-decision-title">
              <span class="badge ${gate.postureCls}" style="font-size:12px;padding:4px 9px;">${escHtml(gate.posture)}</span>
              <span class="badge">${escHtml(gate.macroPermission)} BACKDROP</span>
              <span class="mut">${escHtml(gate.priorityRule)}</span>
            </div>
          </div>
          <div class="srmap-decision-actions">
            <label class="srmap-veto-chk ${plan.disruptionVeto ? "on" : ""}">
              <input type="checkbox" id="chkDisruptionVeto" ${plan.disruptionVeto ? "checked" : ""}>
              <span>Disruption Veto (Outage / Shock)</span>
            </label>
            <button type="button" class="btn btn-primary" id="btnLogSrRun">[Log This Run]</button>
          </div>
        </div>

        <div class="srmap-decision-grid">
          <div class="srmap-dec-cell">
            <div class="srmap-dec-lbl">WHY NOW (1-SENTENCE VERDICT)</div>
            <div class="srmap-dec-txt">${escHtml(gate.why)}</div>
          </div>
          <div class="srmap-dec-cell">
            <div class="srmap-dec-lbl">EXACT TRIGGER CLOSE (TO ACT / UPGRADE)</div>
            <div class="srmap-dec-txt">${escHtml(gate.triggerLine)}</div>
          </div>
          <div class="srmap-dec-cell">
            <div class="srmap-dec-lbl">EXACT INVALIDATION &amp; CASH DEFENSE</div>
            <div class="srmap-dec-txt">${escHtml(gate.invalidationLine)}</div>
          </div>
        </div>
      </div>
    `;
  }

  function renderEvidenceGrid(ev, gate) {
    const r = ev.regime;
    const f = ev.flow;
    const sm = ev.session_macro;
    const ho = ev.historical_odds;

    const rCls = r.daily_bias === "BEAR" ? "dn" : r.daily_bias === "BULL" ? "up" : "warn";
    const shieldStr =
      typeof r.dist_to_120d_ema_pct === "number"
        ? `120D EMA ${fmtPct(r.dist_to_120d_ema_pct)} (${r.shield_btc_pct === 0 ? "HOLD USDT" : "BTC " + r.shield_btc_pct + "%"})`
        : "120D EMA MISSING";

    const nextEvt = sm.next_high_impact_event;
    const evtTs = nextEvt ? fmtUtcSgt(nextEvt.time_utc) : null;
    let evtHtml = `<span>No USD High-Impact release in 7d queue</span>`;
    let evtBlackout = false;
    if (nextEvt) {
      const m = nextEvt.live_minutes_away;
      if (typeof m === "number" && m >= -15 && m <= 60) {
        evtBlackout = true;
        evtHtml = `<span class="badge dn">BLACKOUT ACTIVE</span> <b>${escHtml(nextEvt.title)}</b> in ${Math.round(m)}m (${escHtml(evtTs.shortPair)})`;
      } else {
        const hrsStr = typeof m === "number" ? (m >= 120 ? `${(m / 60).toFixed(1)}h away` : `${Math.round(m)}m away`) : "";
        evtHtml = `<b>${escHtml(nextEvt.title)}</b> · ${hrsStr} (${escHtml(evtTs.shortPair)})`;
      }
    }

    const allRegimes = r.all_regimes || [];
    return `
      <div class="card">
        <div class="srmap-sec-head" style="margin-bottom:8px;">
          <div>
            <h2>Block 2 · Selective Cross-Desk Evidence (Best of F1–F6)</h2>
            <div class="mut">1.0x Spot 1H–4H timing layer only — combines Trend, Flows/Premium, Events &amp; Historical Odds without clutter.</div>
          </div>
          <span class="badge">SCOPE: 1H–4H TIMING ONLY</span>
        </div>

        <div class="srmap-evidence-grid">
          <div class="srmap-ev-card">
            <div class="srmap-ctx-kicker">REGIME &amp; 120D MACRO SHIELD (F2 + F6)</div>
            <div class="srmap-ctx-val">
              <span class="badge ${rCls}">${escHtml(r.code)}: ${escHtml(r.name)}</span>
              <span class="badge">1D ${escHtml(r.daily_structure)}</span>
              <span class="badge">4H ${escHtml(r.h4_structure)}</span>
            </div>
            <div class="srmap-ctx-sub"><b>${escHtml(shieldStr)}</b> · ${escHtml(ev.trendCue)}</div>
            ${
              allRegimes.length
                ? `<details class="srmap-rdefs-details" ${REGIME_DEFS_OPEN ? "open" : ""}>
                    <summary>R1–R5 Plain-English Definitions</summary>
                    <div class="srmap-rdefs-list">
                      ${allRegimes.map((x) => `<div><b>${escHtml(x.code)} (${escHtml(x.name)}):</b> ${escHtml(x.criteria)}</div>`).join("")}
                    </div>
                  </details>`
                : ""
            }
          </div>

          <div class="srmap-ev-card">
            <div class="srmap-ctx-kicker">FLOW, COINBASE PREMIUM &amp; CROWDING (F3 + F5)</div>
            <div class="srmap-ctx-val">
              <b>${escHtml(f.etf_flow_regime)}</b> · 5D ETF ${typeof f.etf_5d_usd_m === "number" ? "$" + f.etf_5d_usd_m.toFixed(1) + "M" : "MISSING"} · OI 24h ${fmtPct(f.oi_change_24h_pct)}
            </div>
            <div class="srmap-ctx-sub">
              Coinbase Prem: <b>${typeof f.coinbase_premium_bps === "number" ? fmtNum(f.coinbase_premium_bps, 1) + " bps (" + fmtUsd(f.coinbase_premium_usd, 0) + ")" : "MISSING"}</b> ·
              L/S Ratio: <b>${typeof f.long_short_account_ratio === "number" ? fmtNum(f.long_short_account_ratio, 2) + " (" + fmtNum(f.ls_ratio_percentile_72h, 0) + "% pct)" : "MISSING"}</b><br>
              Spot CVD ${typeof f.spot_cvd_ratio === "number" ? f.spot_cvd_ratio.toFixed(3) : "MISSING"} · Vol ${typeof f.spot_vol_ratio_vs_ma20 === "number" ? f.spot_vol_ratio_vs_ma20.toFixed(2) + "x" : "MISSING"} · Fund ${typeof f.funding_rate_8h_pct === "number" ? fmtPct(f.funding_rate_8h_pct, 4) : "MISSING"}<br>
              ${escHtml(ev.driverCue)}
            </div>
          </div>

          <div class="srmap-ev-card ${evtBlackout ? "alert" : ""}">
            <div class="srmap-ctx-kicker">MACRO EVENT &amp; SESSION LIQUIDITY (F5 + F1)</div>
            <div class="srmap-ctx-val">${evtHtml}</div>
            <div class="srmap-ctx-sub">
              Market Time (L): <b>${escHtml(sm.day_of_week)} · ${escHtml(sm.awake_state)}</b> · Exp Day Swing ~${fmtNum(sm.expected_day_range_pct, 2)}% (1H ~${fmtNum(sm.expected_hour_range_pct, 2)}%) · Weekend: ${String(sm.is_weekend_utc)}
            </div>
          </div>

          <div class="srmap-ev-card">
            <div class="srmap-ctx-kicker">HISTORICAL ODDS SANITY CHECK (F4)</div>
            <div class="srmap-ctx-val"><b>${escHtml(ho.project_g_summary)}</b></div>
            <div class="srmap-ctx-sub">
              Cortex-Rhyme: <b>${escHtml(ho.rhyme_posture)}</b> · 24h Med ${fmtPct(ho.rhyme_24h_median_pct)} · ±${fmtNum(ho.rhyme_24h_lift_se_pts, 1)} pts SE.<br>
              Packet Age: ${gate.ageMinutes != null ? `${gate.ageMinutes}m old` : "UNKNOWN"} (${gate.isStale ? "STALE >65m" : "Fresh <=65m"}).
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function renderPlanAndLogSection(plan, logRows) {
    const usdtPct = Math.max(0, Math.min(100, 100 - (Number(plan.btcPct) || 0)));
    return `
      <details class="card srmap-plan-drawer" id="srPlanDetails" ${PLAN_OPEN ? "open" : ""}>
        <summary class="srmap-guide-summary">
          <span>Block 5 · My 1.0x Spot Plan &amp; Persistent Run Journal (${logRows.length} Saved Run${logRows.length === 1 ? "" : "s"})</span>
          <span class="badge">BTC ${plan.btcPct}% / USDT ${usdtPct}%</span>
        </summary>
        <div class="srmap-plan-body">
          <div class="srmap-plan-grid">
            <label class="field"><span>Current BTC Sleeve (%)</span><input type="number" id="planBtcPct" min="0" max="100" step="5" value="${escHtml(plan.btcPct)}"></label>
            <label class="field"><span>Max Single Tranche (%)</span><input type="number" id="planMaxTranche" min="5" max="100" step="5" value="${escHtml(plan.maxTranchePct)}"></label>
            <label class="field"><span>Cash Target on Floor Break (%)</span><input type="number" id="planCashTarget" min="0" max="100" step="5" value="${escHtml(plan.cashTargetPct)}"></label>
            <label class="field"><span>Cash Parking Venue</span><input type="text" id="planParking" value="${escHtml(plan.parking)}"></label>
          </div>
          <label class="field" style="margin-top:8px;">
            <span>Optional Extra Chart Note (e.g. TradingView 1D AVWAP Z-score or 1W Heatmap peak)</span>
            <input type="text" id="planExtraNote" placeholder="Optional: e.g. 1D AVWAP Z = -1.4σ, CMC 1W peak $59,725" value="${escHtml(plan.extraNote)}">
          </label>

          <div class="actions" style="margin-top:10px;justify-content:space-between;flex-wrap:wrap;gap:6px;">
            <span class="mut" id="srLogMsg">Runs are saved locally in your browser (1.0x Spot accountability &amp; 4H/1D outcome tracking).</span>
            <div class="actions">
              <button type="button" class="btn btn-primary" id="btnLogSrRun2">[+ Log Current Run]</button>
              <button type="button" class="btn" id="btnExportSrLog">[Export Log .JSON]</button>
              <button type="button" class="btn" id="btnClearSrLog">[Clear Log]</button>
            </div>
          </div>

          ${
            logRows.length
              ? `<div class="srmap-log-wrap">
                  <table class="srmap-log-table">
                    <thead>
                      <tr>
                        <th>Timestamp (UTC / SGT)</th>
                        <th>BTC Spot</th>
                        <th>Regime</th>
                        <th>Posture</th>
                        <th>Cash Tgt</th>
                        <th>Trigger / 4H–1D Outcome &amp; Lesson</th>
                      </tr>
                    </thead>
                    <tbody>
                      ${logRows
                        .map(
                          (row) => `
                        <tr>
                          <td>${escHtml(row.utc)}<br><span class="mut">${escHtml(row.sgt)}</span></td>
                          <td><b>${fmtUsd(row.price, 0)}</b></td>
                          <td>${escHtml(row.regime)}</td>
                          <td><span class="badge">${escHtml(row.posture)}</span></td>
                          <td>${escHtml(row.cashTargetPct)}%</td>
                          <td>
                            <div class="mut">${escHtml(row.trigger)}</div>
                            <input type="text" class="srmap-lesson-input" data-log-lesson="${escHtml(row.id)}" placeholder="Add 4H/1D outcome & lesson…" value="${escHtml(row.lesson || "")}">
                          </td>
                        </tr>`
                        )
                        .join("")}
                    </tbody>
                  </table>
                </div>`
              : `<p class="mut" style="margin:8px 0 0;">No runs logged yet — click <b>[Log This Run]</b> above whenever you take a snapshot.</p>`
          }
        </div>
      </details>
    `;
  }

  function buildAiPrompt(state, refPrice) {
    const meta = window.DeskI18n?.getMeta();
    const prefix =
      meta && meta.code !== "en"
        ? `**Response Language:** Respond strictly in ${meta.aiName} while keeping all BTC prices, levels, and JSON values exact.\n\n`
        : "";

    const sr = state?.sr_bands || null;
    const overlaps = sr?.magnet_overlaps || [];
    const staircase = buildUnifiedStaircase(sr, refPrice, overlaps);
    const cmc = state?.derivatives?.cmc_liquidations || null;
    const ladder = state?.spot_magnet?.magnets?.liquidation_ladder || [];
    const wick24 = get24hWickRange(state);
    const ev = extractCrossDeskEvidence(state);
    const gate = evaluateDecisionGate(state, refPrice, ev, staircase, USER_PLAN);
    const tsPair = fmtUtcSgt(state?.updated_at_utc);
    const stalePair = fmtUtcSgt(state?.updated_at_utc, 65);

    const annotateCluster = (price, usdM, side, extra = {}) => {
      const dist = liveDistPct(price, refPrice);
      const pull = computePullScore(usdM, dist);
      return {
        ...extra,
        price,
        usd_m: usdM,
        live_distance_pct: dist != null ? +dist.toFixed(2) : null,
        pull_score: pull != null ? +pull.toFixed(1) : null,
        freshness: classifyClusterFreshness(price, side, wick24),
      };
    };

    const payload = {
      protocol: "FINAL SPOT DECISION DESK (1.0x Spot Only · SMR-Powered)",
      scope: "1.0x Spot Only (zero leverage, zero futures, zero shorting) · 1H-4H short-term timing layer only",
      updated_at_utc: tsPair.utc,
      updated_at_sgt: tsPair.sgt,
      stale_after_utc: stalePair.utc,
      stale_after_sgt: stalePair.sgt,
      live_spot_price: refPrice,
      decision_gate_precheck: {
        computed_posture: gate.posture,
        veto_active: gate.vetoActive,
        vetos: gate.vetos,
        macro_permission: gate.macroPermission,
        why: gate.why,
        trigger_close: gate.triggerLine,
        invalidation_close: gate.invalidationLine,
      },
      cross_desk_evidence: {
        regime_and_shield: { ...ev.regime, all_regimes: undefined },
        flow_coinbase_and_crowding: ev.flow,
        macro_event_and_session: ev.session_macro,
        historical_odds_f4: ev.historical_odds,
      },
      wick_range_24h: wick24,
      sr_bands: sr,
      liquidation_clusters: {
        strict_rule: "NEVER mix or sum CMC Exact Hyperliquid with Modeled F3 Ladder.",
        cmc_exact_hyperliquid: cmc
          ? {
              source: cmc.source,
              mark_price: cmc.mark_price,
              cumulative_fuel: cmc.cumulative_fuel,
              realized: cmc.realized,
              short_clusters_above: (cmc.tactical_short_clusters_within_8pct || []).map((c) =>
                annotateCluster(c.price, c.usd_m, "upper", { leverage: c.leverage, range: c.range })
              ),
              long_clusters_below: (cmc.tactical_long_clusters_within_8pct || []).map((c) =>
                annotateCluster(c.price, c.usd_m, "lower", { leverage: c.leverage, range: c.range })
              ),
              largest_macro_short_cluster: cmc.largest_macro_short_cluster ?? "MISSING",
              largest_macro_long_cluster: cmc.largest_macro_long_cluster ?? "MISSING",
            }
          : "MISSING",
        modeled_f3_ladder: ladder.length
          ? ladder.map((r) => annotateCluster(r.price, r.estimated_vol_m, r.side, { tier: r.tier, side: r.side }))
          : "MISSING",
      },
      user_spot_plan: {
        current_btc_pct: USER_PLAN.btcPct,
        current_usdt_pct: 100 - (Number(USER_PLAN.btcPct) || 0),
        max_single_tranche_pct: USER_PLAN.maxTranchePct,
        cash_target_on_floor_break_pct: USER_PLAN.cashTargetPct,
        parking_venue: USER_PLAN.parking,
        manual_disruption_veto: USER_PLAN.disruptionVeto,
        extra_chart_note: USER_PLAN.extraNote || "NONE",
      },
    };

    return (
      prefix +
      `### ROLE & OBJECTIVE
Act as a 1.0x Spot Bitcoin Decision Auditor evaluating telemetry from **FINAL SPOT DECISION DESK (1.0x Spot Only · SMR-Powered)**.
Zero leverage, zero futures, zero shorting. Use this packet as a **1H–4H timing & risk filter**, never a long-term valuation tool.

STRICT AUDIT & OUTPUT RULES:
1. **Timestamps (\`UTC\` + \`SGT\` ONLY):** Report packet time and stale cutoff (\`+65m\`) strictly in **UTC and SGT (UTC+8)** using \`updated_at_utc\` / \`updated_at_sgt\` and \`stale_after_utc\` / \`stale_after_sgt\`. Mark stale & recommend \`STAND ASIDE\` if >65m old.
2. **Never Invent Missing Feeds:** Inspect \`cross_desk_evidence\`; report any field marked \`"MISSING"\` explicitly without guessing. Challenge \`decision_gate_precheck\` independently from raw numbers.
3. **Never Mix Liquidations:** Keep **CMC Exact Hyperliquid** and **Modeled F3 Ladder** strictly separate. State clearly that magnets represent leverage fuel (not a must-visit) and modeled pools are estimates.
4. **Deliver a Crisp 5-Part Decision Brief:**
   - **1. Decision Verdict & Freshness (\`UTC + SGT\`):** State \`STAND ASIDE\`, \`REDUCED SIZE / WAIT\`, or \`CONDITIONS ALIGNED (STAGED)\`, respecting conflict priority (\`Veto -> Regime -> S/R+Magnets -> 4H/1D Close Wins\`).
   - **2. Cross-Desk Evidence:** Audit \`R1–R5\` + \`120D EMA\`, ETF/CVD/Coinbase Premium/OI/L:S Ratio, USD Macro Blackout & Session, and Project G / Cortex-Rhyme odds.
   - **3. Key S/R Staircase Ceilings & Floors (\`1W / 1D / 4H / 1H\`)**
   - **4. Separate Dual Magnets (\`FRESH\` vs \`TESTED_24H\`) & Trap \`#05\` / \`#01\` Risks**
   - **5. 1.0x Spot Risk Filter ("If-Then"):** State (a) exact **4H/1D invalidation close**, (b) next deeper floor & cash protection plan (\`cash_target_on_floor_break_pct\`), and (c) exact **reclaim/breakout close** required before acting.

### LIVE FINAL SPOT DECISION TELEMETRY (JSON)
\`\`\`json
${JSON.stringify(payload, null, 2)}
\`\`\``
    );
  }

  function render(state) {
    LAST_STATE = state ?? LAST_STATE;
    const host = document.getElementById("srMapRoot");
    if (!host) return;
    const sr = LAST_STATE?.sr_bands;
    const refPrice = getRefPrice(LAST_STATE);

    if (!LAST_STATE || !sr) {
      host.innerHTML = `<div class="card"><p class="mut" style="margin:0;">Waiting for Final Spot Decision telemetry…</p></div>`;
      return;
    }

    const overlaps = sr.magnet_overlaps || [];
    const staircase = buildUnifiedStaircase(sr, refPrice, overlaps);
    const coreOrder = sr.core_order || ["1W", "1D", "4H", "1H"];
    const confR = sr.confluence_zones?.resistance || [];
    const confS = sr.confluence_zones?.support || [];
    const intradayMap = INTRADAY_DATA?.timeframes || sr.intraday_snapshot || {};
    const intradaySource = INTRADAY_DATA?.source || "Hourly Snapshot Fallback (click Refresh Intraday for live 15m/30m/12H bars)";
    const wick24 = get24hWickRange(LAST_STATE);
    const ev = extractCrossDeskEvidence(LAST_STATE);
    const gate = evaluateDecisionGate(LAST_STATE, refPrice, ev, staircase, USER_PLAN);
    const tsPair = fmtUtcSgt(LAST_STATE.updated_at_utc);

    host.innerHTML = `
      <div class="actions" style="margin-bottom:10px;justify-content:space-between;flex-wrap:wrap;gap:8px;">
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
          <button type="button" class="btn btn-primary" id="btnCopySrAi">[Copy Final Decision AI Prompt + JSON]</button>
          <span class="mut" id="srAiMsg">FINAL SPOT DECISION DESK · 1.0x Spot Only · Selective Cross-Desk + S/R + Dual Magnets.</span>
        </div>
        <span class="badge ${gate.isStale ? "dn" : (sr.status === "LIVE" ? "up" : "warn")}">
          ${escHtml(tsPair.shortPair)}${gate.isStale ? " (STALE >65m)" : ""} · Spot ${fmtUsd(refPrice, 1)}
        </span>
      </div>

      ${renderDecisionHero(gate, USER_PLAN)}

      ${renderEvidenceGrid(ev, gate)}

      <details class="card srmap-guide-card" id="srGuideDetails" ${GUIDE_OPEN ? "open" : ""}>
        <summary class="srmap-guide-summary">
          <span>30-Second Beginner Guide: How to Read This Final Decision Page</span>
          <span class="badge">TAP TO EXPAND</span>
        </summary>
        <div class="srmap-guide-body">
          <div><b>1. Read Block 1 First:</b> Look at the Decision Gate (<code>STAND ASIDE</code> / <code>REDUCED SIZE</code> / <code>ALIGNED</code>), why it says that, and the exact 4H candle closes needed.</div>
          <div><b>2. Check Block 2 Filters:</b> Don't fight a Bear/RED ETF flow regime blindly; watch Coinbase Premium &amp; USD Macro Blackouts.</div>
          <div><b>3. Block 3 Staircase + Magnets:</b> Ceilings sit above blue live BTC; Floors below. Avoid buying floors tagged <code>MAGNET BELOW</code> until they sweep &amp; reclaim (Trap #05).</div>
          <div><b>4. Block 4–5 Plan &amp; Journal:</b> Keep <b>CMC Exact</b> separate from <b>Modeled</b> estimates, prefer <b>FRESH</b> pools, and log your 4H/1D outcomes below.</div>
        </div>
      </details>

      ${
        overlaps.length
          ? `<div class="card srmap-overlap-card">
              <div class="srmap-sec-head">
                <div>
                  <h2>Magnet Overlap Alert (${overlaps.length} Nearby)</h2>
                  <div class="mut">A large liquidation cluster sits just behind a short-term S/R band — watch for wick sweeps before acting.</div>
                </div>
                <button type="button" class="btn" id="btnSrOpenTrap05">[Open Trap #05 Guide in F9 &rarr;]</button>
              </div>
              <ul class="srmap-overlap-list">
                ${overlaps.map((o) => `<li>${escHtml(o.message)}</li>`).join("")}
              </ul>
            </div>`
          : ""
      }

      <div class="card">
        <div class="srmap-sec-head" style="margin-bottom:8px;">
          <div>
            <h2>Block 3 · Unified Structural Price Staircase (1W · 1D · 4H · 1H)</h2>
            <div class="mut">Top ceilings above live BTC and top floors below live BTC · Automatically merges Multi-TF Confluence zones.</div>
          </div>
          <div style="display:flex;gap:5px;flex-wrap:wrap;">
            <span class="badge dn">${confR.length} Ceiling Confluence</span>
            <span class="badge up">${confS.length} Floor Confluence</span>
          </div>
        </div>
        <div class="srmap-staircase">
          <div class="srmap-stair-hdr ceil">&#9650; RESISTANCE (CEILINGS ABOVE LIVE PRICE)</div>
          ${staircase.ceilings.length ? staircase.ceilings.map((r) => renderStaircaseRow(r, "resistance")).join("") : `<div class="mut" style="padding:6px;">No overhead resistance zones mapped above live price.</div>`}
          <div class="srmap-live-divider">
            <span>&#9658; LIVE BTC REFERENCE PRICE</span>
            <strong>${fmtUsd(refPrice, 1)}</strong>
          </div>
          <div class="srmap-stair-hdr floor">&#9660; SUPPORT (FLOORS BELOW LIVE PRICE)</div>
          ${staircase.floors.length ? staircase.floors.map((r) => renderStaircaseRow(r, "support")).join("") : `<div class="mut" style="padding:6px;">No underlying support zones mapped below live price.</div>`}
        </div>
      </div>

      <details class="card srmap-matrix-drawer" id="srMatrixDetails" ${MATRIX_OPEN ? "open" : ""}>
        <summary class="srmap-guide-summary">
          <span>Detailed Multi-Timeframe Bands (1W / 1D / 4H / 1H) + Optional 15m / 30m / 12H Noise Drawer</span>
          <span class="badge">TAP TO EXPAND</span>
        </summary>
        <div style="margin-top:10px;">
          <div class="srmap-sec-head" style="margin-bottom:10px;">
            <div class="mut">Bands padded with 0.18 × ATR(14) around closed-candle fractal swing highs, lows &amp; S/R flips.</div>
            <button type="button" class="btn ${INTRADAY_OPEN ? "btn-primary" : ""}" id="btnToggleIntraday">
              ${INTRADAY_OPEN ? "[- Hide Intraday 15m / 30m / 12H]" : "[+ Show Intraday 15m / 30m / 12H (High Noise — Live Fetch)]"}
            </button>
          </div>
          <div class="srmap-tf-grid">
            ${coreOrder.map((k) => renderTfCard(sr.timeframes?.[k], refPrice)).join("")}
          </div>
          ${
            INTRADAY_OPEN
              ? `<div class="srmap-intraday-drawer">
                  <div class="srmap-sec-head" style="margin-bottom:8px;">
                    <div>
                      <div class="srmap-noise-title">HIGH NOISE INTRADAY ZONE (12H / 30m / 15m) — NEVER OVERRIDES 4H / 1D STRUCTURE</div>
                      <div class="mut">${INTRADAY_LOADING ? "Fetching closed 15m / 30m / 12h candles from BinanceVision…" : escHtml(intradaySource)}</div>
                    </div>
                    <button type="button" class="btn" id="btnRefreshIntraday" ${INTRADAY_LOADING ? "disabled" : ""}>[${INTRADAY_LOADING ? "Loading…" : "Refresh Live Intraday"}]</button>
                  </div>
                  <div class="srmap-tf-grid srmap-tf-grid-3">
                    ${["12H", "30m", "15m"].map((k) => renderTfCard(intradayMap[k], refPrice)).join("")}
                  </div>
                </div>`
              : ""
          }
        </div>
      </details>

      ${renderLiquidationSection(LAST_STATE, refPrice, wick24)}

      ${renderPlanAndLogSection(USER_PLAN, RUN_LOG)}
    `;
  }

  function logCurrentRun() {
    if (!LAST_STATE?.sr_bands) return;
    const refPrice = getRefPrice(LAST_STATE);
    const ev = extractCrossDeskEvidence(LAST_STATE);
    const staircase = buildUnifiedStaircase(LAST_STATE.sr_bands, refPrice, LAST_STATE.sr_bands.magnet_overlaps || []);
    const gate = evaluateDecisionGate(LAST_STATE, refPrice, ev, staircase, USER_PLAN);
    const nowTs = _toUtcSgtParts(Date.now());
    const entry = {
      id: "run_" + Date.now(),
      utc: nowTs.utc,
      sgt: nowTs.sgt,
      price: refPrice,
      regime: `${ev.regime.code} (${ev.regime.daily_bias})`,
      posture: gate.posture,
      trigger: gate.triggerLine,
      invalidation: gate.invalidationLine,
      cashTargetPct: USER_PLAN.cashTargetPct,
      lesson: "",
    };
    RUN_LOG = [entry, ...RUN_LOG].slice(0, 50);
    saveLog(RUN_LOG);
    PLAN_OPEN = true;
    render(LAST_STATE);
    const msgEl = document.getElementById("srLogMsg");
    if (msgEl) {
      msgEl.textContent = `Logged run @ ${nowTs.shortPair} (${gate.posture})!`;
      msgEl.style.color = "var(--up)";
    }
  }

  function bindEvents() {
    const host = document.getElementById("srMapRoot");
    if (!host || host.dataset.srBound === "1") return;
    host.dataset.srBound = "1";

    host.addEventListener("toggle", (e) => {
      const det = e.target;
      if (det.id === "srMatrixDetails") MATRIX_OPEN = det.open;
      else if (det.id === "srPlanDetails") PLAN_OPEN = det.open;
      else if (det.id === "srGuideDetails") GUIDE_OPEN = det.open;
      else if (det.classList?.contains("srmap-rdefs-details")) REGIME_DEFS_OPEN = det.open;
    }, true);

    host.addEventListener("click", (e) => {
      if (e.target.closest("#btnToggleIntraday")) {
        MATRIX_OPEN = true;
        INTRADAY_OPEN = !INTRADAY_OPEN;
        if (INTRADAY_OPEN && !INTRADAY_DATA && LAST_STATE) {
          fetchLiveIntradayBands(LAST_STATE);
        } else {
          render(LAST_STATE);
        }
        return;
      }

      if (e.target.closest("#btnRefreshIntraday")) {
        MATRIX_OPEN = true;
        if (LAST_STATE) fetchLiveIntradayBands(LAST_STATE);
        return;
      }

      if (e.target.closest("#btnSrOpenTrap05")) {
        INIT_OPTS.openTrapGuide?.("trap_05");
        return;
      }

      if (e.target.closest("#btnCopySrAi")) {
        const refPrice = getRefPrice(LAST_STATE);
        const promptText = buildAiPrompt(LAST_STATE, refPrice);
        INIT_OPTS.copyWithFeedback?.(promptText, "Copied Final Spot Decision AI Prompt + JSON!", "srAiMsg");
        return;
      }

      if (e.target.closest("#btnLogSrRun") || e.target.closest("#btnLogSrRun2")) {
        logCurrentRun();
        return;
      }

      if (e.target.closest("#btnExportSrLog")) {
        const u = URL.createObjectURL(new Blob([JSON.stringify(RUN_LOG, null, 2)], { type: "application/json" }));
        const a = document.createElement("a");
        a.href = u;
        a.download = `btc-spot-decision-log-${Date.now()}.json`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(u), 2000);
        return;
      }

      if (e.target.closest("#btnClearSrLog")) {
        RUN_LOG = [];
        saveLog(RUN_LOG);
        render(LAST_STATE);
      }
    });

    host.addEventListener("change", (e) => {
      if (e.target.id === "chkDisruptionVeto") {
        USER_PLAN.disruptionVeto = Boolean(e.target.checked);
        savePlan(USER_PLAN);
        render(LAST_STATE);
      }
    });

    host.addEventListener("input", (e) => {
      const t = e.target;
      if (t.id === "planBtcPct") {
        USER_PLAN.btcPct = Math.max(0, Math.min(100, Number(t.value) || 0));
        savePlan(USER_PLAN);
      } else if (t.id === "planMaxTranche") {
        USER_PLAN.maxTranchePct = Math.max(0, Math.min(100, Number(t.value) || 0));
        savePlan(USER_PLAN);
      } else if (t.id === "planCashTarget") {
        USER_PLAN.cashTargetPct = Math.max(0, Math.min(100, Number(t.value) || 0));
        savePlan(USER_PLAN);
      } else if (t.id === "planParking") {
        USER_PLAN.parking = t.value;
        savePlan(USER_PLAN);
      } else if (t.id === "planExtraNote") {
        USER_PLAN.extraNote = t.value;
        savePlan(USER_PLAN);
      } else if (t.dataset?.logLesson) {
        const id = t.dataset.logLesson;
        const row = RUN_LOG.find((r) => r.id === id);
        if (row) {
          row.lesson = t.value;
          saveLog(RUN_LOG);
        }
      }
    });
  }

  window.SrMapModule = {
    init(opts = {}) {
      INIT_OPTS = opts;
      bindEvents();
    },
    getHubInfo(state) {
      const sr = state?.sr_bands;
      if (!sr) return { badge: "FINAL DESK", badgeCls: "warn", status: "1.0x Spot Final Decision Desk Ready" };
      const refPrice = getRefPrice(state);
      const ev = extractCrossDeskEvidence(state);
      const staircase = buildUnifiedStaircase(sr, refPrice, sr.magnet_overlaps || []);
      const gate = evaluateDecisionGate(state, refPrice, ev, staircase, USER_PLAN);
      const ovCount = (sr.magnet_overlaps || []).length;
      return {
        badge: gate.posture,
        badgeCls: gate.postureCls,
        status: `${ev.regime.code} (${gate.macroPermission}) · ${sr.summary_line}${ovCount ? " · " + ovCount + " Magnet Alert" : ""}`,
      };
    },
    getHubSummary(state) {
      return this.getHubInfo(state).status;
    },
    render,
  };
})();
