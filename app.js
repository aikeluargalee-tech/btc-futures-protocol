"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const usd = (v, d = 0) =>
  typeof v === "number" && isFinite(v)
    ? "$" + v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })
    : "—";
const num = (v, d = 2) => (typeof v === "number" && isFinite(v) ? v.toFixed(d) : "—");
const pct = (v, d = 2) => (typeof v === "number" && isFinite(v) ? `${v >= 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const kv = (rows) => rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");

let STATE = null;
let LIVE = { price: null, src: null, at: 0 };
let CHART_TF = "h4";

async function fetchJson(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function pollLivePrice() {
  try {
    const r = await fetchJson("https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT");
    LIVE.price = +r.price;
    LIVE.src = "BinanceVision";
    LIVE.at = Date.now();
  } catch {
    try {
      const r2 = await fetchJson("https://api.exchange.coinbase.com/products/BTC-USD/ticker");
      LIVE.price = +r2.price;
      LIVE.src = "Coinbase";
      LIVE.at = Date.now();
    } catch {
      LIVE.src = null;
    }
  }
  renderHeaderLive();
}

function activePrice() {
  return LIVE.price ?? STATE?.ticker?.price ?? null;
}

function renderHeaderLive() {
  const p = activePrice();
  $("livePrice").textContent = p ? usd(p, 1) : "—";
  const chg = STATE?.ticker?.chg24_pct;
  $("liveChg").innerHTML = typeof chg === "number" ? `<span class="${chg >= 0 ? "up" : "dn"}">${pct(chg, 2)} 24h</span>` : "—";
  const age = LIVE.at ? Math.round((Date.now() - LIVE.at) / 1000) : null;
  $("liveDot").className = "dot" + (age !== null && age < 20 ? " live" : "");
  const liveLabel = window.DeskI18n ? window.DeskI18n.t("live_word") : "live";
  const snapLabel = window.DeskI18n ? window.DeskI18n.t("snapshot_price") : "snapshot price";
  $("liveFeed").textContent = LIVE.src ? `${liveLabel} ${LIVE.src} · ${age}s` : snapLabel;
}

function renderSignalTab() {
  const sig = STATE.signal || {};
  const reg = STATE.regime || {};
  const port = STATE.portfolio || {};
  const prop = sig.proposal || {};
  const status = sig.status || "FLAT";

  const banner = $("signalBanner");
  banner.className = "card signal-banner " + status;
  const stBadge = status === "LONG" ? "up" : status === "SHORT" ? "dn" : "warn";
  const biasBadge = reg.bias === "LONG" ? "up" : reg.bias === "SHORT" ? "dn" : "warn";

  $("signalSummary").innerHTML = `
    <div class="signal-head">
      <div class="big-num ${status === "LONG" ? "up" : status === "SHORT" ? "dn" : "warn"}">${esc(status)}</div>
      <span class="badge ${stBadge}">${status === "FLAT" ? "NO FUTURES ENTRY" : esc(prop.entry_method || "FUTURES ACTIVE")}</span>
    </div>
    <p class="mut" style="margin:8px 0 4px;">Dominant 4H drivers: <b>${esc((reg.dominant_factors || []).join(" · ") || "—")}</b></p>
    <p class="mut" style="margin:0;">1D Bias: <b>${esc(reg.daily_bias || "—")}</b> · Open Futures: <b>${(port.open_positions || []).length}/1</b> · Equity: <b>${usd(port.equity_usd, 2)}</b></p>
  `;

  const sc = typeof reg.score === "number" ? reg.score : 50;
  const th = reg.thresholds || { long: 68, short: 32, dd_tier1_active: false, weekend_long: 80, weekend_short: 20 };
  $("regimeGaugeBox").innerHTML = `
    <div class="signal-head">
      <div class="big-num">${num(sc, 1)} <span class="mut">/ 100</span></div>
      <span class="badge ${biasBadge}">${esc(reg.bias || "FLAT")}</span>
    </div>
    <div class="gauge-track"><div class="gauge-marker" style="left:${Math.max(0, Math.min(100, sc))}%"></div></div>
    <div class="mut" style="display:flex;justify-content:space-between;">
      <span>Short ≤ ${th.short}</span>
      <span>Flat ${th.short + 1}–${th.long - 1}</span>
      <span>Long ≥ ${th.long}</span>
    </div>
    <p class="mut" style="margin:6px 0 0;">
      Last 4H Close: ${esc(reg.last_4h_close_utc || "—")} · Weekend: ${reg.is_weekend_utc ? `<b class="warn">YES (${th.weekend_long}/${th.weekend_short} 0.5x)</b>` : "No"}
      ${th.dd_tier1_active ? ' · <b class="dn">-6% DD Tier 1 Active (0.2% risk, 75/25)</b>' : ""}
    </p>
  `;

  const checks = sig.checklist || [];
  $("checklistBox").innerHTML = checks
    .map(
      (c) => `
      <div class="row">
        <div>
          <div class="title">${c.id}. ${esc(c.rule)}</div>
          <div class="mut">${esc(c.detail)}</div>
        </div>
        <span class="badge ${c.passed ? "up" : "dn"}">${c.passed ? "PASS" : "FAIL"}</span>
      </div>`
    )
    .join("");

  const rej = sig.rejection_reasons || [];
  $("rejectionBox").innerHTML = rej.length
    ? `<div class="reject-box"><b class="dn">Futures Setup Rejected (${rej.length})</b><ul>${rej.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>`
    : `<div class="mut" style="margin-top:8px;color:var(--up);">All 9 Version 4.0 futures qualification criteria satisfied.</div>`;

  if (prop && prop.entry_price) {
    $("proposalKv").innerHTML = kv([
      ["Evaluated Direction", `${prop.direction}${prop.weekend_halved ? " (Weekend 0.5x Size)" : ""}`],
      ["Nearest 4H Level", prop.level_label ? `${prop.level_label} @ ${usd(prop.level_price, 1)}` : "—"],
      ["Proposed Entry", `${usd(prop.entry_price, 1)} (${prop.entry_method})`],
      ["Hard Stop", `${usd(prop.stop_price, 1)} (${num(prop.stop_distance_pct, 2)}% ≤ 2.2% max)`],
      ["Target 1 (45% Partial @ 1.5R)", `${usd(prop.target1_price, 1)} (${prop.target1_label})`],
      ["Raw / Funding-Adj R:R", `${num(prop.raw_rr, 2)}:1 / ${num(prop.funding_adjusted_rr, 2)}:1 (min 1.60:1)`],
      ["Calculated Size", `${prop.size_btc ?? "—"} BTC (${usd(prop.notional_usd, 0)})`],
      ["Effective Leverage", `${num(prop.leverage, 2)}x / 2.00x max${prop.leverage_capped ? " (CLAMPED)" : ""}`],
      ["Risk Allocation", `${num(prop.actual_risk_pct, 3)}% (${usd(prop.actual_risk_usd, 2)})`],
    ]);
  } else {
    $("proposalKv").innerHTML = kv([["Proposal", "Unavailable"]]);
  }

  const cb = port.circuit_breakers || {};
  const heatPct = Math.min(100, ((port.open_heat_pct || 0) / (port.max_heat_pct || 1.5)) * 100);
  const activeCBs = [
    cb.intraday_halted && "INTRADAY -1.2% HALT",
    cb.daily_halted && "DAILY -2.0% PAUSE",
    cb.weekly_halted && "WEEKLY -4.0% FLAT",
    cb.dd_tier1_active && "DD -6.0% THROTTLE (0.2%, 75/25)",
    cb.dd_tier2_locked && "DD -10.0% LOCKED",
  ].filter(Boolean);

  $("heatBreakersBox").innerHTML = `
    <div style="margin-bottom:10px;">
      <div style="display:flex;justify-content:space-between;">
        <span>Portfolio Heat</span>
        <b>${num(port.open_heat_pct, 2)}% / ${num(port.max_heat_pct, 2)}% max</b>
      </div>
      <div class="bar-track"><div class="bar-fill" style="width:${heatPct}%;background:${heatPct > 85 ? "var(--dn)" : "var(--acc)"};"></div></div>
    </div>
    <dl class="kv">
      ${kv([
        ["Leverage Used", `${num(port.current_leverage, 2)}x / ${num(port.max_leverage, 2)}x max (${usd(port.open_notional_usd, 0)})`],
        ["Intraday PnL / Limit", `${pct(port.intraday_pnl_pct, 2)} (buf ${num(port.intraday_buffer_pct, 2)}% to -1.20%)`],
        ["Daily PnL / Limit", `${pct(port.daily_pnl_pct, 2)} (buf ${num(port.daily_buffer_pct, 2)}% to -2.00%)`],
        ["Weekly PnL / Limit", `${pct(port.weekly_pnl_pct, 2)} (buf ${num(port.weekly_buffer_pct, 2)}% to -4.00%)`],
        ["HWM Drawdown", `${pct(port.drawdown_pct, 2)} (HWM ${usd(port.high_water_mark_usd, 0)})`],
        ["Dist to -6% / -10% DD", `${num(port.dd_tier1_buffer_pct, 2)}% / ${num(port.dd_tier2_buffer_pct, 2)}%`],
        ["Circuit Breakers", activeCBs.length ? activeCBs.join(", ") : "ALL CLEAR"],
      ])}
    </dl>
  `;
}

function renderRegimeTab() {
  const sr = STATE.state_of_regime || STATE.regime?.state_of_regime || null;
  const kp = STATE.kline_patterns || null;
  const c11 = STATE.cortex_11p || null;

  if ($("stateOfRegimeBox")) {
    if (!sr) {
      $("stateOfRegimeBox").innerHTML = `<h2>BTC State of Regime (5-State Radar)</h2><p class="mut">Unavailable</p>`;
    } else {
      const regCls = sr.bias === "BULLISH" ? "up" : (sr.bias === "BEARISH" || sr.bias === "CAPITULATION") ? "dn" : "warn";
      const pois = c11?.price_and_pois || {};
      const sup = pois.htf_supply_cluster || {};
      const dem = pois.htf_demand_cluster || {};
      const poor = pois.poor_highs_cluster || {};
      const allRegs = (sr.all_regimes || []).map((r) => `
        <div class="row">
          <div>
            <div class="title">[${esc(r.code)}] ${esc(r.name)}</div>
            <div class="mut">${esc(r.criteria)}</div>
          </div>
          <span class="badge ${r.active ? regCls : ""}">${r.active ? "ACTIVE" : "STANDBY"}</span>
        </div>`).join("");
      $("stateOfRegimeBox").innerHTML = `
        <h2>BTC State of Regime &amp; Gate 1 HTF Points of Interest</h2>
        <div class="signal-head" style="margin-bottom:8px;">
          <div class="big-num ${regCls}">[${esc(sr.code)}] ${esc(sr.name)}</div>
          <div>
            <span class="badge ${regCls}">VOL: ${esc(sr.volatility_modifier)}</span>
            <span class="badge ${sr.flow_modifier === "SPOT_LED" ? "up" : sr.flow_modifier === "LEVERAGE_LED" ? "warn" : ""}">FLOW: ${esc(sr.flow_modifier)}</span>
            ${sr.spot_taker_buy_ratio_24h != null ? `<span class="badge">SPOT BUY 24H: ${(sr.spot_taker_buy_ratio_24h * 100).toFixed(1)}%</span>` : ""}
          </div>
        </div>
        <div class="grid-2" style="margin-bottom:8px;">
          <div>${allRegs}</div>
          <dl class="kv">${kv([
            ["Last 1H Close", pois.last_close != null ? usd(pois.last_close, 1) : "UNAVAILABLE"],
            ["Local 1H Range", pois.range_low != null && pois.range_high != null ? `${usd(pois.range_low, 1)} – ${usd(pois.range_high, 1)}` : "UNAVAILABLE"],
            ["HTF Supply Cluster", sup.low != null ? `${usd(sup.low, 1)}–${usd(sup.high, 1)} (${sup.status})` : "UNAVAILABLE"],
            ["HTF Demand Cluster", dem.low != null ? `${usd(dem.low, 1)}–${usd(dem.high, 1)} (${dem.status})` : "UNAVAILABLE"],
            ["1st Test High", pois.first_test_high != null ? usd(pois.first_test_high, 1) : "UNAVAILABLE"],
            ["Poor Highs Cluster", poor.level != null ? `${usd(poor.level, 1)} (${poor.touches ?? 0} touches · swept=${poor.swept})` : "None / Unavailable"],
          ])}</dl>
        </div>
      `;
    }
  }

  if ($("kline10Box")) {
    const cat = kp?.catalog_10 || [];
    $("kline10Box").innerHTML = `
      <h2>Layer 1 · 10 Crypto Kline Primitives (1H · 4H · 1D)</h2>
      <p class="mut" style="margin:0 0 8px;">Active multi-timeframe hits: <b>${kp?.active_count ?? 0}</b></p>
      ${cat.length ? cat.map((p) => {
        const active = (p.active_tfs || []).length > 0;
        const bCls = p.direction === "BULLISH" ? "up" : p.direction === "BEARISH" ? "dn" : active ? "warn" : "";
        return `
          <div class="row">
            <div>
              <div class="title">${esc(p.name)} <span class="mut">(${esc(p.category)})</span></div>
              <div class="mut">${active ? `${esc(p.detail || "")}${p.confluence_level ? ` · ★ ${esc(p.confluence_level)}` : ""}` : "No recent closed-bar trigger"}</div>
            </div>
            <span class="badge ${bCls}">${active ? `${esc(p.active_tfs.join("/"))} · ${esc(p.direction)}` : "INACTIVE"}</span>
          </div>`;
      }).join("") : `<p class="mut">Unavailable</p>`}
    `;
  }

  if ($("playbook11Box")) {
    const plist = c11?.patterns_11_list || [];
    $("playbook11Box").innerHTML = `
      <h2>Layer 2 · Symmetrical 11-Pattern Playbook (P01–P11)</h2>
      <p class="mut" style="margin:0 0 8px;">Long (USDT→BTC) vs Short (BTC→USDT) spot rotation telemetry</p>
      ${plist.length ? plist.map((p) => {
        const bCls = p.status === "ACTIVE" ? (p.direction === "LONG" ? "up" : "dn") : p.status === "FORMING" ? "warn" : "";
        return `
          <div class="row">
            <div>
              <div class="title">P${String(p.num).padStart(2, "0")} · ${esc(p.name)} <span class="mut">(${esc(p.rotation)})</span></div>
              <div class="mut">${esc(p.tier)} · ${esc(p.detail)}</div>
            </div>
            <span class="badge ${bCls}">${esc(p.status)}</span>
          </div>`;
      }).join("") : `<p class="mut">Unavailable</p>`}
    `;
  }

  if ($("rulebook3Box")) {
    const r3 = c11?.microstructure_rulebook_3 || {};
    const fs = c11?.feed_status || {};
    const c = r3.r3_1_cvd || {};
    const oi = r3.r3_2_oi_funding || {};
    const fr = r3.r3_3_p_shape_frvp || {};
    const av = r3.r3_4_avwap || {};
    $("rulebook3Box").innerHTML = `
      <h2>Gate 3 · Microstructure Confirmation Rulebook (R3.1–R3.4)</h2>
      <p class="mut" style="margin:0 0 8px;">Feeds: candles=${esc(fs.candles || "—")} · cvd=${esc(fs.cvd || "—")} · oi_funding=${esc(fs.oi_funding || "—")} · frvp=${esc(fs.frvp || "—")} · avwap=${esc(fs.avwap || "—")}</p>
      <dl class="kv">${kv([
        ["R3.1 Spot vs Perp CVD", c.spot_cvd_last_two_highs ? `Spot [${c.spot_cvd_last_two_highs.join(" → ")}] vs Perp [${(c.perp_cvd_last_two_highs || []).join(" → ")}] · Lag=${c.spot_lag_or_divergence_flag}` : "UNAVAILABLE"],
        ["R3.2 OI + Funding Timing", oi.btc_oi_change_pct_1h != null || oi.funding_rate_current != null ? `OI 1H ${pct(oi.btc_oi_change_pct_1h, 2)} · 4H ${pct(oi.btc_oi_change_pct_4h, 2)} · Fund ${pct(oi.funding_rate_current, 4)} · TrapSweep=${oi.sweep_oi_spike_flag}` : "UNAVAILABLE"],
        ["R3.3 P-Shape FRVP", fr.frvp_poc != null ? `POC ${usd(fr.frvp_poc, 1)} · VAH ${usd(fr.frvp_vah, 1)} · VAL ${usd(fr.frvp_val, 1)} · BelowVAL=${fr.closed_below_upper_val}` : "UNAVAILABLE"],
        ["R3.4 Anchored VWAP", av.avwap_value != null ? `${av.anchor_type} (${usd(av.anchor_price, 1)}) · AVWAP ${usd(av.avwap_value, 1)} · Price ${av.price_vs_avwap} · FailedRetest=${av.failed_retest_flag}` : "UNAVAILABLE"],
      ])}</dl>
    `;
  }

  const groups = STATE.regime?.groups || {};
  const meta = [
    ["trend_structure", "1. Trend Structure (30%)"],
    ["momentum", "2. Momentum 4H (25%)"],
    ["volatility_liquidity", "3. Volatility & Liquidity 4H (25%)"],
    ["session_context", "4. Session / Context (20%)"],
  ];

  $("factorCards").innerHTML = meta
    .map(([k, title]) => {
      const g = groups[k];
      if (!g) return `<div class="card"><h2>${esc(title)}</h2><p class="mut">Unavailable</p></div>`;
      const comps = Object.entries(g.components || {}).map(([ck, cv]) => [ck.replace(/_/g, " "), `${cv}/100`]);
      const extraRows = [];
      if (k === "trend_structure") {
        extraRows.push(["4H / 1D Structure", `${g.h4_structure} / ${g.daily_structure} (${g.daily_bias})`]);
        extraRows.push(["4H EMA20 / EMA50", `${usd(g.ema20_4h, 0)} / ${usd(g.ema50_4h, 0)}`]);
        extraRows.push(["1D EMA50 / EMA200", `${usd(g.ema50_d, 0)} / ${usd(g.ema200_d, 0)}`]);
      } else if (k === "momentum") {
        extraRows.push(["RSI(14) 4H / 1D", `${g.rsi_4h ?? "—"} / ${g.rsi_d ?? "—"}`]);
        extraRows.push(["4H ROC 6 / 12 / 20p", `${pct(g.roc6_4h_pct, 2)} / ${pct(g.roc12_4h_pct, 2)} / ${pct(g.roc20_4h_pct, 2)}`]);
      } else if (k === "volatility_liquidity") {
        extraRows.push(["Quality Score (raw)", `${g.quality_score ?? g.score}/100`]);
        extraRows.push(["4H ATR(14) / Pctile", `${usd(g.atr_4h_usd, 0)} (${g.atr_4h_pct ?? "—"}%, ${g.atr_4h_percentile ?? "—"}th)`]);
        extraRows.push(["Rel 4H Vol / Funding", `${g.rel_volume_4h ?? "—"}x / ${pct(g.funding_rate_pct, 4)}`]);
      } else if (k === "session_context") {
        extraRows.push(["Session / Weekend", `${g.session_name || "—"} (${g.is_weekend_utc ? "Weekend" : "Weekday"})`]);
        extraRows.push(["Next Release", g.next_macro_event ? `${g.next_macro_event} (${Math.round(g.next_macro_minutes)}m)` : "None nearby"]);
        extraRows.push(["VIX / DXY / ETF 5D", `${g.vix ?? "—"} / ${g.dxy ?? "—"} / ${g.etf_5d_usd_m != null ? "$" + g.etf_5d_usd_m + "M" : "—"}`]);
      }
      return `
        <div class="card">
          <h2>${esc(title)}</h2>
          <div class="signal-head" style="margin-bottom:8px;">
            <div class="big-num">${num(g.score, 1)} <span class="mut">/ 100</span></div>
            <span class="badge">${Math.round(g.weight * 100)}% wt</span>
          </div>
          <dl class="kv">${kv([...extraRows, ...comps])}</dl>
        </div>`;
    })
    .join("");

  renderChart();

  const levels = STATE.signal?.structural_levels || [];
  const P = activePrice() || 0;
  $("levelsKv").innerHTML = kv(
    levels
      .slice()
      .sort((a, b) => b.price - a.price)
      .map((l) => {
        const dist = P ? ((l.price - P) / P) * 100 : 0;
        return [`${l.label} (${l.kind})`, `${usd(l.price, 1)} (${pct(dist, 2)})`];
      })
  );

  const cal = STATE.macro_calendar || [];
  $("macroCalBox").innerHTML = cal.length
    ? cal
        .map((e) => {
          const near = e.minutes_away >= 0 && e.minutes_away <= 60;
          return `<div class="row"><div><div class="title">${near ? "⚠️ " : ""}${esc(e.title)}</div><div class="mut">${esc(e.time_utc)}</div></div><span class="badge ${near ? "dn" : ""}">${e.minutes_away >= 0 ? `in ${Math.round(e.minutes_away)}m` : `${Math.round(e.minutes_away)}m ago`}</span></div>`;
        })
        .join("")
    : `<p class="mut">No USD High-Impact events inside the upcoming window.</p>`;
}

function renderSpotTab() {
  const sm = STATE?.spot_magnet;
  if (!$("spotDibseHeroBox")) return;
  if (!sm || sm.data_quality !== "LIVE" || !sm.metrics) {
    $("spotDibseHeroBox").innerHTML = `<h2>Spot Magnet (DIBSE Dual-Sleeve Radar)</h2><p class="mut">Spot telemetry unavailable (${esc(sm?.data_quality || "NO DATA")}).</p>`;
    if ($("spotLsceMagnetBox")) $("spotLsceMagnetBox").innerHTML = `<h2>LSCE Sweep Gate &amp; 6-Factor Magnet</h2><p class="mut">Unavailable</p>`;
    if ($("spotLadderBox")) $("spotLadderBox").innerHTML = `<h2>Modeled 10x–100x Liquidation Ladder</h2><p class="mut">Unavailable</p>`;
    if ($("spotTelemetryFeedsBox")) $("spotTelemetryFeedsBox").innerHTML = "";
    return;
  }

  const m = sm.metrics;
  const diag = sm.regime_diagnosis || {};
  const dibse = sm.dibse || {};
  const lsce = sm.lsce || {};
  const mag = sm.magnets || {};
  const sig = dibse.dibse_signal || "HOLD BOTH SLEEVES";
  const sigCls = sig.startsWith("LOOP A") ? "up" : sig.startsWith("LOOP B") ? "dn" : "warn";

  const candRows = (diag.all_5_candidates || []).map((c) => `
    <div class="row">
      <div>
        <div class="title">${esc(c.name)}</div>
        <div class="mut">${esc((c.matched || []).join(" · ") || "0 criteria met")}</div>
      </div>
      <span class="badge ${c.active ? sigCls : ""}">${c.matches_count}/4 · ${c.active ? "ACTIVE" : "STANDBY"}</span>
    </div>`).join("");

  $("spotDibseHeroBox").innerHTML = `
    <h2>DIBSE Spot Action &amp; Majority-Voting 5-Regime Spot Radar</h2>
    <div class="signal-head" style="margin-bottom:8px;">
      <div>
        <div class="big-num ${sigCls}">${esc(sig)} (${num((dibse.sizing_factor ?? 0), 2)}x)</div>
        <div class="mut">Regime: <b>${esc(diag.name || "—")}</b> (${esc(diag.majority_score || "—")}) · Playbook: <b>${esc(diag.playbook || "—")}</b></div>
      </div>
      <div>
        <span class="badge ${sigCls}">${esc(dibse.rotation || "Hold Both Sleeves")}</span>
        <span class="badge">SANDBOX: 10% USDT + 10% BTC · 80% CORE</span>
      </div>
    </div>
    <p style="margin:6px 0 8px;">${esc(dibse.actionable_trade_instruction || diag.plain_english_verdict || "")}</p>
    <div class="grid-2" style="margin-bottom:8px;">
      <div>${candRows}</div>
      <dl class="kv">${kv([
        ["Target Active Sleeve Mix", `BTC Sleeve ${dibse.target_btc_allocation_pct ?? 10}% | USDT Sleeve ${dibse.target_usdt_reserve_pct ?? 10}% (80% Core)`],
        ["Loop A (Buy -> > P_buy)", dibse.loop_a_zone || "—"],
        ["Loop B (Sell -> < P_sell)", dibse.loop_b_zone || "—"],
        ["Failure / Stop Rule", dibse.stop_rule || "ZERO STOP-LOSSES (Self-Healing Spot Inventory)"],
        ["Failure Protocol", dibse.failure_protocol || "—"],
      ])}</dl>
    </div>
  `;

  const lsceCls = (lsce.status || "").includes("CONFIRMED") ? (lsce.side === "LOWER" ? "up" : "dn") : (lsce.status || "").includes("PROGRESS") ? "warn" : "";
  const mf = mag.magnet_factors || {};
  $("spotLsceMagnetBox").innerHTML = `
    <h2>LSCE Bidirectional Sweep Gate &amp; 6-Factor Dominant Magnet</h2>
    <div class="signal-head" style="margin-bottom:8px;">
      <div class="big-num ${lsceCls}">${esc(lsce.status || "UNTESTED")}</div>
      <span class="badge ${lsceCls}">${esc(mag.dominant_magnet || "—")}</span>
    </div>
    <p class="mut" style="margin:0 0 8px;">${esc(lsce.action_verdict || "")}</p>
    <dl class="kv">${kv([
      ["Sweep Side & Shelf", `${lsce.side || "NONE"} · ${lsce.cluster_tested || "—"}`],
      ["Absorption / Depth", lsce.spot_absorption || "—"],
      ["Dominant Reason", mag.dominant_magnet_reason || "—"],
      ["1. Pool Size (10x–100x)", mf.factor_1_size || "—"],
      ["2. Spot vs Perp Flow", mf.factor_2_spot_leadership || "—"],
      ["3. Crowding Fuel", mf.factor_3_crowding_fuel || "—"],
      ["4. VWAP Structure", mf.factor_4_regime_structure || "—"],
      ["5. Distance Asymmetry", mf.factor_5_asymmetry || "—"],
      ["6. Range / Volatility", mf.factor_6_range_compression || "—"],
    ])}</dl>
  `;

  const ladder = mag.liquidation_ladder || [];
  $("spotLadderBox").innerHTML = `
    <h2>Modeled 10x–100x Liquidation Magnet Ladder (BTC Magnet)</h2>
    <p class="mut" style="margin:0 0 8px;">Immediate Imbalance L/S: <b>${mag.immediate_imbalance_ratio ?? "—"}x</b> · Full Ladder L vs S: <b>$${mag.total_ladder_lower_vol_m ?? 0}M vs $${mag.total_ladder_upper_vol_m ?? 0}M (${mag.total_ladder_imbalance_ratio ?? 1}x)</b></p>
    ${ladder.map((row) => {
      const bCls = row.side === "upper" ? "dn" : "up";
      return `
        <div class="row">
          <div>
            <div class="title">${esc(row.tier)} ${row.is_nearest ? "★ NEAREST" : ""}</div>
            <div class="mut">${esc(row.leverage)} leverage · Modeled ~$${row.estimated_vol_m}M</div>
          </div>
          <span class="badge ${bCls}">${usd(row.price, 0)} (${pct(row.distance_pct, 2)})</span>
        </div>`;
    }).join("")}
  `;

  const feedCards = [
    ["1. Price Anchors & 4H Structural Bounds", [
      ["Spot Execution Price", `${usd(m.price, 2)} (${pct(m.price_change_1h_pct, 2)} 1H · ${pct(m.price_change_24h_pct, 2)} 24H)`],
      ["Daily VWAP (00:00Z)", `${usd(m.daily_vwap, 2)} (${m.price >= m.daily_vwap ? "ABOVE" : "BELOW"})`],
      ["Weekly VWAP (Mon 00Z)", `${usd(m.weekly_vwap, 2)} (${m.price >= m.weekly_vwap ? "ABOVE" : "BELOW"})`],
      ["30D VWAP / Primary VPOC", `${usd(m.vwap_30d, 0)} / ${usd(m.vpoc_30d_primary, 0)}`],
      ["Closed 4H Range", `${usd(m.swing_low_4h, 0)} – ${usd(m.swing_high_4h, 0)}`],
      ["3D Base Floor / Ceiling", `${usd(m.base_floor, 0)} – ${usd(m.base_ceiling, 0)}`],
    ]],
    ["2. Order Flow, Spot CVD & Coinbase Premium", [
      ["24H Spot CVD Ratio", `${num(m.spot_cvd_ratio, 3)} (${m.spot_cvd_ratio >= 1.0 ? "Buyers Active" : "Sellers Dominant"})`],
      ["Spot CVD Slope 7D / 14D", `${num(m.spot_cvd_slope_7d, 0)} / ${num(m.spot_cvd_slope_14d, 0)} BTC`],
      ["Spot 24H Vol / 20D MA", `${num(m.spot_vol_24h, 0)} BTC (${num(m.spot_vol_ratio, 2)}x 20D MA)`],
      ["Perp CVD 24H Trend", `${m.perp_cvd_trend} (Mark Prem ${usd(m.perp_cvd_slope_24h, 2)})`],
      ["Coinbase Spot Premium", m.coinbase_premium_bps != null ? `${usd(m.coinbase_premium_usd, 2)} (${m.coinbase_premium_bps >= 0 ? "+" : ""}${m.coinbase_premium_bps} bps)` : "UNAVAILABLE"],
      ["L2 ±1% Book Depth Ratio", `${m.bids_asks_depth_ratio}x Bids/Asks`],
    ]],
    ["3. Derivatives Crowding & Leverage Basis", [
      ["Open Interest (BTC)", m.open_interest_btc != null ? `${num(m.open_interest_btc, 1)} BTC` : "UNAVAILABLE"],
      ["OI Change 1H / 4H / 24H", `${pct(m.oi_change_1h_pct, 2)} / ${pct(m.oi_change_4h_pct, 2)} / ${pct(m.oi_change_24h_pct, 2)}`],
      ["8H / Annualized Funding", `${pct(m.funding_rate_8h_pct, 4)} (${pct(m.funding_rate_annualized_pct, 2)} ann.)`],
      ["Futures Annualized Basis", `${pct(m.futures_basis_annualized_pct, 2)}`],
      ["Retail L/S Account Ratio", m.ls_ratio_available ? `${m.long_short_account_ratio} (${m.ls_ratio_percentile_72h ?? "—"}th pctile 72h)` : "UNAVAILABLE"],
      ["ETF 1D / 5D Flows", m.etf_sum5_usd_m != null ? `Latest $${m.etf_net_inflow_latest_m ?? "—"}M · 5D $${m.etf_sum5_usd_m}M` : "UNAVAILABLE"],
    ]],
    ["4. Options Variance Premium & Spot Directives", [
      ["30D Realized Volatility", m.realized_vol_30d_pct != null ? `${num(m.realized_vol_30d_pct, 2)}%` : "UNAVAILABLE"],
      ["Deribit Implied DVOL", m.implied_vol_dvol_pct != null ? `${num(m.implied_vol_dvol_pct, 2)}%` : "UNAVAILABLE"],
      ["Variance Premium (IV-RV)", m.variance_premium_pts != null ? `${pct(m.variance_premium_pts, 2)} pts` : "UNAVAILABLE"],
      ["24H Sweep Extremes", `Low ${usd(m.capitulation_wick_low, 0)} · High ${usd(m.euphoria_wick_high, 0)}`],
      ["Spot Leverage Limit", "1.0x UNLEVERAGED ONLY (Zero Margin / Zero Liq Risk)"],
      ["Zero-Stop Invariant", "80% Core Untouched · Dual-Sleeve Self-Healing Inventory"],
    ]],
  ];

  $("spotTelemetryFeedsBox").innerHTML = feedCards.map(([title, rows]) => `
    <div class="card">
      <h2>${esc(title)}</h2>
      <dl class="kv">${kv(rows)}</dl>
    </div>
  `).join("");
}

function renderChart() {
  const bars = (STATE?.charts?.[CHART_TF] || []).slice(-60);
  if (bars.length < 2) {
    $("chartBox").innerHTML = `<p class="mut">Chart unavailable</p>`;
    return;
  }
  const W = 760, H = 300, Lp = 14, Rp = 110, Tp = 14, Bp = 24;
  const closes = bars.map((b) => b[4]);
  const highs = bars.map((b) => b[2]);
  const lows = bars.map((b) => b[3]);
  let lo = Math.min(...lows);
  let hi = Math.max(...highs);
  const pad = (hi - lo) * 0.08 || 200;
  lo -= pad;
  hi += pad;
  const x = (i) => Lp + (i / (bars.length - 1)) * (W - Lp - Rp);
  const y = (p) => Tp + ((hi - p) / (hi - lo)) * (H - Tp - Bp);

  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}">`;
  svg += `<rect x="${Lp}" y="${Tp}" width="${W - Lp - Rp}" height="${H - Tp - Bp}" fill="#ffffff" stroke="var(--line-dark)" stroke-width="1"/>`;
  for (let g = 1; g < 4; g++) {
    const gy = Tp + ((H - Tp - Bp) * g) / 4;
    svg += `<line x1="${Lp}" x2="${W - Rp}" y1="${gy.toFixed(1)}" y2="${gy.toFixed(1)}" stroke="#e0e0da" stroke-width="1"/>`;
  }
  const levels = (STATE.signal?.structural_levels || []).filter((l) => l.price >= lo && l.price <= hi);
  let lastY = -100;
  for (const l of levels.slice().sort((a, b) => b.price - a.price)) {
    const yy = y(l.price);
    if (yy - lastY < 14) continue;
    lastY = yy;
    const col = l.kind === "resistance" ? "var(--dn)" : l.kind === "support" ? "var(--up)" : "var(--muted)";
    svg += `<line x1="${Lp}" x2="${W - Rp}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${col}" stroke-dasharray="4 3" opacity="0.72"/>`;
    svg += `<text x="${W - Rp + 6}" y="${(yy + 4).toFixed(1)}" fill="var(--text)" font-size="9.5">${esc(l.label.slice(0, 14))} ${Math.round(l.price).toLocaleString()}</text>`;
  }

  const path = closes.map((c, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(c).toFixed(1)}`).join(" ");
  svg += `<path d="${path}" fill="none" stroke="var(--acc)" stroke-width="2.2"/>`;

  const prop = STATE.signal?.proposal;
  if (prop && prop.entry_price) {
    for (const [val, lbl, col] of [
      [prop.entry_price, "ENTRY", "var(--warn)"],
      [prop.stop_price, "STOP", "var(--dn)"],
      [prop.target1_price, "TP1", "var(--up)"],
    ]) {
      if (val >= lo && val <= hi) {
        const yy = y(val);
        svg += `<line x1="${Lp}" x2="${W - Rp}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${col}" stroke-width="1.4"/>`;
        svg += `<text x="${Lp + 4}" y="${(yy - 4).toFixed(1)}" fill="${col}" font-size="9.5">${lbl} ${Math.round(val).toLocaleString()}</text>`;
      }
    }
  }
  svg += `</svg>`;
  $("chartBox").innerHTML = svg;
}

function updateCalc() {
  const eq = +$("cEq").value || 0;
  const dir = $("cDir").value;
  const isWk = $("cWeekend").value === "yes";
  const entry = +$("cEntry").value || 0;
  const stop = +$("cStop").value || 0;
  const tp = +$("cTp").value || 0;
  const ddTier1 = STATE?.portfolio?.circuit_breakers?.dd_tier1_active;

  let riskPct = ddTier1 ? 0.002 : 0.004;
  if (isWk) riskPct *= 0.5;
  const stopDist = Math.abs(entry - stop);
  const stopPct = entry > 0 ? (stopDist / entry) * 100 : 0;
  const validStopSide = dir === "LONG" ? stop < entry : stop > entry;
  const validTpSide = dir === "LONG" ? tp > entry : tp < entry;
  const rawRR = stopDist > 0 && validTpSide ? Math.abs(tp - entry) / stopDist : 0;

  const targetRiskUsd = eq * riskPct;
  const rawBtc = stopDist > 0 ? targetRiskUsd / stopDist : 0;
  const maxBtc = entry > 0 ? (eq * 2.0) / entry : 0;
  const clamped = rawBtc > maxBtc;
  const sizeBtc = Math.min(rawBtc, maxBtc);
  const notional = sizeBtc * entry;
  const lev = eq > 0 ? notional / eq : 0;
  const actualRiskUsd = sizeBtc * stopDist;
  const actualRiskPct = eq > 0 ? (actualRiskUsd / eq) * 100 : 0;

  const issues = [];
  if (!validStopSide) issues.push("Stop on wrong side of entry");
  if (stopPct > 2.2) issues.push(`Stop ${stopPct.toFixed(2)}% > 2.20% max`);
  if (rawRR < 1.6) issues.push(`R:R ${rawRR.toFixed(2)}:1 < 1.60:1 min`);

  $("calcOutKv").innerHTML = kv([
    ["Protocol Status", issues.length ? `INVALID (${issues.join("; ")})` : "VALID v4.0 FUTURES SIZING"],
    ["Risk Budget", `${(riskPct * 100).toFixed(2)}% (${usd(targetRiskUsd, 2)} target)`],
    ["Futures Size", `${sizeBtc.toFixed(6)} BTC (${usd(notional, 2)} notional)`],
    ["Effective Leverage", `${lev.toFixed(2)}x / 2.00x max${clamped ? " (2x LEVERAGE CLAMPED)" : ""}`],
    ["Actual Risk", `${actualRiskPct.toFixed(3)}% (${usd(actualRiskUsd, 2)})`],
    ["Stop Distance / R:R", `${stopPct.toFixed(2)}% (≤2.2%) / ${rawRR.toFixed(2)}:1 (≥1.6:1)`],
  ]);
}

function renderLedgerTab() {
  const port = STATE.portfolio || {};
  const open = port.open_positions || [];
  $("openPosBox").innerHTML = open.length
    ? open
        .map(
          (p) => `
      <div class="row">
        <div>
          <div class="title">${esc(p.id)} · <span class="${p.direction === "LONG" ? "up" : "dn"}">${esc(p.direction)}</span>${p.weekend_halved ? " (Weekend 0.5x)" : ""}</div>
          <div class="mut">Entry ${usd(p.entry_price, 1)} · Stop ${usd(p.stop_price, 1)} · TP1 ${usd(p.target1_price, 1)} · Size ${p.size_btc} BTC (${num(p.leverage, 2)}x)</div>
          <div class="mut">Hold ${num(p.hold_hours, 1)}h/24h · BE: ${p.breakeven_moved ? "Yes" : "No"} · 1.5R Partial: ${p.partial_taken ? "Yes" : "No"} · 8h Cut: ${p.time_stop_8h_reduced ? "Yes" : "No"}</div>
        </div>
        <div style="text-align:right;">
          <div class="${p.unrealized_pnl_usd >= 0 ? "up" : "dn"}" style="font-weight:700;">${usd(p.unrealized_pnl_usd, 2)} (${num(p.current_r, 2)}R)</div>
          <div class="mut">Risk ${num(p.risk_pct, 3)}%</div>
        </div>
      </div>`
        )
        .join("")
    : `<p class="mut">No open paper futures positions (Flat).</p>`;

  const rev = port.review || {};
  $("reviewKv").innerHTML = kv([
    ["Completed Closed Legs", `${rev.total_closed_legs ?? 0}`],
    ["Win Rate", `${rev.win_rate_pct ?? 0}%`],
    ["Profit Factor", `${rev.profit_factor ?? 0}`],
    ["Expectancy (R)", `${rev.expectancy_r ?? 0}R`],
    ["Net Realized PnL", usd(rev.total_realized_pnl_usd, 2)],
  ]);

  const drv = STATE.derivatives || {};
  const ext = STATE.extras || {};
  const ven = drv.venues || {};
  const venueStr = Object.keys(ven).length
    ? Object.entries(ven)
        .map(([k, v]) => `${k.replace("_futures", "").toUpperCase()} ${pct(v, 4)}`)
        .join(" · ")
    : pct(drv.current_rate_pct, 5);
  const cmc = drv.cmc_liquidations || {};
  const real = cmc.realized || {};
  const tacL = (cmc.tactical_long_clusters_within_8pct || [])[0];
  const tacS = (cmc.tactical_short_clusters_within_8pct || [])[0];
  const fuel = cmc.cumulative_fuel || {};
  $("derivKv").innerHTML = kv([
    ["Funding 8h (Venues)", venueStr],
    ["Open Interest (OKX / Total)", `${drv.oi_btc != null ? Math.round(drv.oi_btc).toLocaleString() + " BTC" : "—"} / ${drv.total_oi_btc != null ? Math.round(drv.total_oi_btc).toLocaleString() + " BTC" : "—"}`],
    ["Deribit DVOL", ext.dvol ?? "—"],
    ["Fear & Greed", ext.fng_value != null ? `${ext.fng_value} (${ext.fng_label})` : "—"],
    ["ETF Latest / 5D", STATE.etf ? `${STATE.etf.latest_usd_m}M (${STATE.etf.latest_date}) / ${STATE.etf.sum5_usd_m}M` : "—"],
    ["USDT+USDC 7D", STATE.stables ? `${STATE.stables.total_usd_b}B (${pct(STATE.stables.chg7d_pct, 2)})` : "—"],
    ["CMC 4H Realized Liq (L / S)", real.h4_total_usd_m != null ? `L $${real.h4_long_usd_m}M / S $${real.h4_short_usd_m}M (${real.h4_long_flush_pct}% L)` : "—"],
    ["CMC 24H Realized Liq (L / S)", real.h24_total_usd_m != null ? `L $${real.h24_long_usd_m}M / S $${real.h24_short_usd_m}M ($${real.h24_total_usd_m}M)` : "—"],
    ["CMC Top Short Magnet (≤8%)", tacS ? `$${tacS.price.toLocaleString()} ($${tacS.usd_m}M · ${tacS.leverage}x · ${tacS.distance_pct >= 0 ? "+" : ""}${tacS.distance_pct}%)` : "—"],
    ["CMC Top Long Magnet (≤8%)", tacL ? `$${tacL.price.toLocaleString()} ($${tacL.usd_m}M · ${tacL.leverage}x · ${tacL.distance_pct}%)` : "—"],
    ["CMC ±2% Squeeze Fuel (S / L)", fuel.shorts_within_2pct_usd_m != null ? `S $${fuel.shorts_within_2pct_usd_m}M vs L $${fuel.longs_within_2pct_usd_m}M (${fuel.squeeze_bias_2pct})` : "—"],
  ]);

  const closed = port.closed_trades || [];
  $("closedTradesBox").innerHTML = closed.length
    ? `<table><thead><tr><th>ID</th><th>Dir</th><th>Entry</th><th>Exit</th><th>Hold</th><th>R</th><th>PnL</th><th>Reason</th></tr></thead><tbody>${closed
        .slice()
        .reverse()
        .map(
          (t) =>
            `<tr><td>${esc(t.trade_id)}</td><td class="${t.direction === "LONG" ? "up" : "dn"}">${esc(t.direction)}</td><td>${usd(t.entry_price, 1)}</td><td>${usd(t.exit_price, 1)}</td><td>${num(t.hold_hours, 1)}h</td><td class="${t.r_multiple >= 0 ? "up" : "dn"}">${num(t.r_multiple, 2)}R</td><td class="${t.pnl_usd >= 0 ? "up" : "dn"}">${usd(t.pnl_usd, 2)}</td><td>${esc(t.reason)}</td></tr>`
        )
        .join("")}</tbody></table>`
    : `<p class="mut">No closed paper trades yet. Trades are logged automatically when v4.0 signals qualify and resolve.</p>`;
}

function renderAuditTab() {
  const logs = STATE.audit_log_recent || [];
  $("auditLogBox").innerHTML = logs.length
    ? `<table><thead><tr><th>UTC Time</th><th>Event</th><th>Details</th></tr></thead><tbody>${logs
        .map(
          (e) =>
            `<tr><td>${esc(e.ts || e.ts_utc)}</td><td><b>${esc(e.event)}</b></td><td class="mut">${esc(e.detail || JSON.stringify(e))}</td></tr>`
        )
        .join("")}</tbody></table>`
    : `<p class="mut">No audit events recorded yet.</p>`;

  $("configPre").textContent = JSON.stringify(STATE.config || {}, null, 2);
  const errs = STATE.fetch_errors || [];
  $("diagBox").textContent = errs.length ? `Non-fatal fetch notes: ${errs.join(" | ")}` : "All data feeds succeeded with zero errors.";
}

function seedCalcFromState() {
  const prop = STATE?.signal?.proposal;
  if (!$("cEntry").value && prop?.entry_price) {
    $("cEntry").value = prop.entry_price;
    $("cStop").value = prop.stop_price;
    $("cTp").value = prop.target1_price;
    $("cDir").value = prop.direction || "LONG";
    $("cEq").value = Math.round(STATE?.portfolio?.equity_usd || 100000);
    $("cWeekend").value = STATE?.regime?.is_weekend_utc ? "yes" : "no";
  }
  updateCalc();
}

function activateTab(tabId) {
  document.querySelectorAll("#tabNav .tab-btn").forEach((x) => x.classList.toggle("active", x.dataset.tab === tabId));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${tabId}`));
}

const SPOT_MAGNET_AI_PROMPT_TEMPLATE = `### ROLE & OBJECTIVE
Act as an Institutional Quantitative Spot Bitcoin Strategist executing the **BTC Magnet Monitor (DIBSE Dual-Sleeve Protocol)**.
Evaluate the raw unleveraged Spot telemetry packet below (Strict **1.0x Spot-Only**: zero margin, zero perpetual futures, zero forced stop-losses; rotating between a **10% USDT Sleeve** and a **10% BTC Sleeve** with **80% Untouched Core Reserve**).

Answer these 5 audit questions strictly from the JSON telemetry:
1. **Regime & 4-Criteria Majority Audit:** Does price vs. Daily/Weekly VWAP, Spot CVD (Ratio + 7D/14D slopes), Coinbase Premium (bps), Funding/OI, and Book Depth support **Loop A (\`USDT -> BTC\`)**, **Loop B (\`BTC -> USDT\`)**, or **Hold Both Sleeves**?
2. **Bidirectional LSCE & 10x–100x Magnet Pull:** Which liquidity cluster exerts dominant pull (\`Upper Short Pool\` vs. \`Lower Long Pool\` vs. CMC ±8% clusters), and is LSCE confirming absorption or warning of a fakeout?
3. **Futures Trap Check:** Compare Spot CVD against Perp Funding/OI/Basis — is upside Spot-Led or Fragile Leverage?
4. **DIBSE Execution Plan:** State exact Loop A accumulation zone (\`Exit > P_buy\`) or Loop B distribution zone (\`Rebuy < P_sell\`), sizing factor (\`0.0x–1.0x\` of the 10% sleeve), and what invalidates waiting.
5. **Quick Mobile Summary (<= 80 words):** Crisp bullet summary for Spot inventory execution.

### LIVE SPOT MAGNET TELEMETRY (JSON)
\`\`\`json
{{SPOT_JSON_PAYLOAD}}
\`\`\``;

const MASTER_QUANT_PROMPT_TEMPLATE = `### ROLE & OBJECTIVE
Act as an Institutional Quantitative Bitcoin Swing Strategist and Risk Officer. Below is a raw, unopinionated market telemetry packet from the **BTC Short-Term Futures Protocol (v4.1)**. Your job is to analyze the raw data independently from first principles (Auction Market Theory, 4H/1D price structure, 7D/30D Volume Profile, momentum exhaustion vs. impulse, multi-venue derivatives positioning, liquidation magnets, L2 order book imbalance, and institutional ETF/stablecoin flows) and issue an unbiased Long, Short, or Stand-Aside execution verdict.

---

### HARD PROTOCOL RISK CONSTRAINTS (NON-NEGOTIABLE)
Every trade idea you evaluate MUST strictly obey these guardrails:
1. **Evaluation Cadence & Hold Window:** Signals are evaluated on **4H candle closes** with a **maximum hold window of 24 hours** (time-stop reduction at 8h, hard exit at 12–24h if stagnant).
2. **Leverage & Capital Risk:**
   - Maximum Futures Leverage: **1:2 (2.0x Isolated)**.
   - Maximum Risk per Trade: **0.40% of Account Equity** on weekdays; **0.20% (halved)** on weekends (\`is_weekend_utc: true\`).
   - Maximum Portfolio Heat: **<= 1.50%** across all open risk.
   - Maximum Concurrent Futures Positions: **1** (LONG or SHORT only).
3. **Structural Geometry & R:R:**
   - **Minimum Reward-to-Risk (R:R):** **>= 1.6 : 1** to the first major opposing structural level (\`Target 1\`), net of estimated 24h funding and maker/taker fee drag.
   - **Maximum Stop Distance:** **<= 2.20%** from entry (placed beyond structural invalidation + ATR buffer).
4. **Macro Blackout:** **Zero new entries** if a high-impact USD macro release is scheduled within **<= 60 minutes**.
5. **Anti-Chasing & Exhaustion Guardrail (CRITICAL):**
   - **DO NOT** recommend market shorting into extreme oversold capitulation (\`rsi_4h < 25\`, \`rsi_d < 30\`, \`fng_value < 15\`, or price sitting directly on top of a primary 4H/1D support level where R:R to the next support is \`< 1.6:1\`).
   - **DO NOT** recommend market longing into extreme overbought exhaustion (\`rsi_4h > 75\`) or directly beneath a major resistance ceiling.
   - When trend and momentum are aligned in a strong impulse but price is overextended, your verdict MUST be **\`STAND ASIDE / CONDITIONAL LIMIT ORDER\`** at a mean-reversion structural pullback level (e.g., 4H EMA20, \`7D Tactical VPOC\`, or prior broken S/R).
6. **Data Integrity & Live Price-Drift Guardrails (Travel Anti-Chase Rule):**
   - If \`meta.completeness_score\` is \`< 0.80\`, flag degraded data integrity and require higher structural confluence before risking capital.
   - Compare \`ticker.live_spot_price\` against the last 4H close (\`meta.price_drift_from_4h_close_atr\`). If live price has already drifted \`> 0.35 * ATR_4H\` away from the 4H close in the trade direction (or compressed R:R to Target 1 below \`1.6:1\`), downgrade any immediate market execution to **\`PLACE CONDITIONAL LIMIT ORDER\`** at a structural retest level.
7. **Timezone Discipline:** All time-based evaluations MUST reference **UTC only**. Never assume local traveler time.

---

### REQUIRED 5-STEP ANALYTICAL OUTPUT FORMAT

#### 1. EXECUTIVE DIRECTIVE (3-Second Summary)
- **Verdict:** \`[STAND ASIDE — WAIT]\` | \`[PLACE CONDITIONAL LIMIT ORDER]\` | \`[EXECUTE LONG/SHORT ON 4H CLOSE]\`
- **Directional Bias:** \`BULLISH\` | \`BEARISH\` | \`NEUTRAL / RANGE-BOUND\` (State 1D structural bias vs. 4H tactical state).
- **Primary Rationale:** 2 concise sentences explaining *why* with concrete prices, RSI/ATR figures, and R:R math.

#### 2. 5-PILLAR TELEMETRY AUDIT
- **A. Price Structure, Kline Primitives & Volume Profile:** Analyze \`charts_ohlcv_last30\` (\`[ts, O, H, L, C, Vol]\`), EMA alignment (\`ema20_4h\`, \`ema50_4h\`, \`ema50_d\`, \`ema200_d\`), tactical **\`7D Tactical VPOC / VAH / VAL\`**, macro **\`30D VPOC / VAH / VAL\`**, Layer-1 **\`kline_patterns\`** (\`1H/4H/1D\` triggers & structural confluence), Layer-2 **\`cortex_11p.pattern_state_flags\`** (\`P01\`–\`P11\` symmetrical setups & Gate 1 POIs), and nearest swing highs/lows.
- **B. Momentum, State of Regime & Volatility:** Evaluate \`state_of_regime\` (5-state \`R1\`–\`R5\` classification, \`volatility_modifier\`, \`flow_modifier\`, \`spot_taker_buy_ratio_24h\`), \`rsi_4h\`, \`rsi_d\`, \`roc6/12/20_4h_pct\`, \`atr_4h_usd\` (\`atr_4h_percentile\`), and \`dvol\`. Classify as **Compression**, **Early Expansion**, or **Late Climax / Exhaustion**.
- **C. Multi-Venue Derivatives, CMC Liquidation Map & Microstructure:** Evaluate \`funding_rate_pct\` across OKX, Kraken Futures, Deribit, and Hyperliquid, \`oi_btc\` / \`venue_oi_btc\`, **\`derivatives.cmc_liquidations\`** (tactical ±8% dollar-weighted Long & Short liquidation magnet clusters, ±2%/±5% cumulative squeeze fuel, and realized 4H/24H long vs. short liquidation wipeouts in $M), **\`cortex_11p.microstructure_rulebook_3\`** (\`R3.1\` Spot vs Perp CVD divergence, \`R3.2\` 1H/4H BTC OI + funding timing, \`R3.3\` P-Shape FRVP, \`R3.4\` Anchored VWAP), **\`derivatives.liquidation_magnets\`**, and **\`derivatives.orderbook_1pct\`** (±1% bid/ask depth ratio & spread bps). Flag stop-hunt zones and whether a 4H long/short liquidation flush has already exhausted momentum.
- **D. Institutional Flows & Macro Context:** Evaluate 5-day ETF flows (\`etf.sum5_usd_m\`), 7d stablecoin liquidity (\`stables.chg7d_pct\`), \`dxy\`, \`vix\`, Fear & Greed (\`fng_value\`), and session liquidity (\`session_name\`).
- **E. Telemetry Integrity Check:** Verify \`meta.completeness_score\`, inspect \`fetch_errors\`, and check live spot drift (\`meta.price_drift_from_4h_close_atr\`).

#### 3. FUTURES EXECUTION VERDICT (1:2 ISOLATED LONG / SHORT)
State clearly whether an immediate **4H Close Long**, **4H Close Short**, or **Flat / Wait** setup passes all v4.1 rules right now, listing which rules pass or block.

#### 4. CALCULATOR-READY EXECUTION & CONTINGENCY TABLE
*(If \`STAND ASIDE\` at market, provide the exact **Conditional Limit / Alert Setup** that WOULD satisfy >= 1.6:1 R:R and <= 2.2% stop distance on a retest)*:
- **Setup Type:** \`Market on 4H Close\` OR \`Conditional Retest / Limit\`
- **Direction:** \`LONG\` | \`SHORT\`
- **Trigger / Entry Price ($):** \`$XX,XXX\` (Structural level reference)
- **Hard Invalidation Stop ($ & %):** \`$XX,XXX\` (\`X.XX%\` — must be \`<= 2.20%\`)
- **Target 1 ($ & R:R):** \`$XX,XXX\` (\`X.XX : 1\` — must be \`>= 1.60 : 1\`)
- **Target 2 ($ & R:R):** \`$XX,XXX\` (\`X.XX : 1\`)
- **Dynamic Position Sizing (1:2 Capped):** Using \`risk_constraints_reference.account_equity_usd\`, calculate exact size enforcing the 2.0x leverage cap: \`BTC_Size = min((Account_Equity * Risk_Pct) / abs(Entry - Stop), (Account_Equity * 2.0) / Entry)\`. Output **USD Notional**, **BTC Quantity**, and **Effective Leverage**.
- **Contingency / Plan B:** Immediate action required if price bypasses the Conditional Limit and closes a 4H bar beyond the Hard Invalidation Stop.
- **What Invalidates Waiting for This Setup:** Exact price level or candle close that cancels the plan.
- **Spot Positioning Note (1.0x Unleveraged):** Concise DCA/accumulation or hedging zones for Spot holders with zero funding drag.

#### 5. MOBILE EXECUTION TL;DR (Copy-Paste Block)
*(Strictly under 100 words, raw execution parameters for quick mobile reading — no narrative)*:
\`\`\`text
[DIR] | TYPE: [Market/Limit] | ENTRY: $X | STOP: $X (X%) | T1: $X (X:1) | T2: $X | SIZE: $X / X.XXXX BTC (X.XXx) | RISK: X% | PLAN B: [Action if Stop breaks] | INVALID IF: [Condition]
\`\`\`

After issuing your structured output above, remain grounded strictly in the telemetry packet below and answer any follow-up Q&A—whether for **Spot positioning** (1.0x unleveraged accumulation/hedging levels with no funding drag) or **Futures leverage decisions** (1:2 max isolated sizing, invalidation distance, funding/slippage sensitivity, or custom equity sizing)—without inventing external prices.

---

### LIVE RAW TELEMETRY PACKET (JSON)
\`\`\`json
{{RAW_JSON_PAYLOAD}}
\`\`\``;

function buildRawTelemetryPacket(fullState) {
  if (!fullState) return null;
  const g = fullState.regime?.groups || {};
  const ts = g.trend_structure || {};
  const mom = g.momentum || {};
  const vl = g.volatility_liquidity || {};
  const sc = g.session_context || {};
  const refPrice = activePrice() || fullState.ticker?.price || 0;
  const atrUsd = vl.atr_4h_usd || fullState.signal?.atr_4h || 0;

  const h4All = fullState.charts?.h4 || [];
  const d1All = fullState.charts?.d1 || [];
  const lastH4 = h4All.length ? h4All[h4All.length - 1] : null;
  const last4hClose = (Array.isArray(lastH4) && lastH4.length >= 5 && lastH4[4] > 0) ? lastH4[4] : (fullState.ticker?.price || 0);
  const driftUsd = (refPrice > 0 && last4hClose > 0) ? (refPrice - last4hClose) : 0;
  const driftPct = last4hClose > 0 ? +((driftUsd / last4hClose) * 100).toFixed(2) : null;
  const driftAtr = atrUsd > 0 ? +(driftUsd / atrUsd).toFixed(2) : null;

  let pillars = 0;
  if (h4All.length && d1All.length) pillars += 0.2;
  if (fullState.derivatives?.current_rate_pct != null && fullState.derivatives?.oi_btc != null) pillars += 0.2;
  if (sc.vix != null && sc.dxy != null) pillars += 0.2;
  if (fullState.etf != null && fullState.stables != null) pillars += 0.2;
  if (fullState.extras?.fng_value != null) pillars += 0.2;
  const completenessScore = +pillars.toFixed(2);

  const rawLevels = fullState.signal?.structural_levels || [];
  const levels = rawLevels.map((l) => {
    const diff = refPrice > 0 ? l.price - refPrice : 0;
    return {
      label: l.label,
      kind: l.kind,
      price: l.price,
      distance_pct: refPrice > 0 ? +((diff / refPrice) * 100).toFixed(2) : null,
      distance_atr: atrUsd > 0 ? +(diff / atrUsd).toFixed(2) : null,
    };
  });

  const findLv = (lbl) => rawLevels.find((l) => l.label === lbl)?.price ?? null;
  const swLow = findLv("4H Swing Low #3") ?? findLv("Prior 4H Low");
  const swHigh = findLv("4H Swing High #3") ?? findLv("Prior 4H High");
  const vpoc7 = findLv("7D Tactical VPOC");
  const anchorLo = swLow ?? vpoc7 ?? refPrice;
  const anchorHi = swHigh ?? vpoc7 ?? refPrice;
  const liqMagnets = fullState.signal?.liquidation_magnets || {
    basis: "Deterministic 25x/50x isolated liquidation bands anchored to 7D VPOC & recent 4H swing pivots",
    long_liq_50x_est: +(anchorLo * 0.984).toFixed(1),
    long_liq_25x_est: +(anchorLo * 0.964).toFixed(1),
    short_liq_50x_est: +(anchorHi * 1.016).toFixed(1),
    short_liq_25x_est: +(anchorHi * 1.036).toFixed(1),
    recent_4h_swing_low_pool: swLow,
    recent_4h_swing_high_pool: swHigh,
  };

  const eqVal = +$("cEq")?.value;
  const accountEquityUsd = Number.isFinite(eqVal) && eqVal > 0 ? +eqVal.toFixed(2) : +(fullState.portfolio?.equity_usd ?? 100000).toFixed(2);

  const lr = fullState.config?.leverage_and_risk || {};
  const th = fullState.config?.timeframe_and_hold || {};

  return {
    meta: {
      protocol_version: fullState.protocol_version || "4.0",
      updated_at_utc: fullState.updated_at_utc,
      updated_at_ms: fullState.updated_at_ms,
      last_4h_close_utc: fullState.last_4h_close_utc,
      session_name: sc.session_name ?? null,
      is_weekend_utc: fullState.regime?.is_weekend_utc ?? null,
      completeness_score: completenessScore,
      price_drift_from_4h_close_pct: driftPct,
      price_drift_from_4h_close_atr: driftAtr,
    },
    ticker: {
      ...(fullState.ticker || {}),
      live_spot_price: LIVE.price ?? null,
      live_spot_source: LIVE.src ?? null,
    },
    indicators: {
      trend: {
        ema20_4h: ts.ema20_4h ?? null,
        ema50_4h: ts.ema50_4h ?? null,
        ema50_d: ts.ema50_d ?? null,
        ema200_d: ts.ema200_d ?? null,
        h4_structure: ts.h4_structure ?? null,
        daily_structure: ts.daily_structure ?? null,
      },
      momentum: {
        rsi_4h: mom.rsi_4h ?? null,
        rsi_d: mom.rsi_d ?? null,
        roc6_4h_pct: mom.roc6_4h_pct ?? null,
        roc12_4h_pct: mom.roc12_4h_pct ?? null,
        roc20_4h_pct: mom.roc20_4h_pct ?? null,
      },
      volatility_volume: {
        atr_4h_usd: atrUsd || null,
        atr_4h_pct: vl.atr_4h_pct ?? null,
        atr_4h_percentile: vl.atr_4h_percentile ?? null,
        rel_volume_4h: vl.rel_volume_4h ?? null,
        dvol: fullState.extras?.dvol ?? null,
      },
    },
    structural_levels: levels,
    derivatives: {
      ...(fullState.derivatives || {}),
      orderbook_1pct: fullState.derivatives?.orderbook_1pct ?? null,
      cmc_liquidations: fullState.derivatives?.cmc_liquidations ?? null,
      liquidation_magnets: liqMagnets,
      funding_30d_percentile: vl.funding_30d_percentile ?? null,
    },
    macro_and_flows: {
      vix: sc.vix ?? null,
      dxy: sc.dxy ?? null,
      fng_value: fullState.extras?.fng_value ?? null,
      fng_label: fullState.extras?.fng_label ?? null,
      etf: fullState.etf ?? null,
      stables: fullState.stables ?? null,
      macro_calendar: fullState.macro_calendar || [],
      next_macro_event: sc.next_macro_event ?? null,
      next_macro_minutes: sc.next_macro_minutes ?? null,
    },
    charts_ohlcv_last30: {
      schema: "[timestamp_ms, open, high, low, close, volume]",
      h4: h4All.slice(-30),
      d1: d1All.slice(-30),
    },
    state_of_regime: fullState.state_of_regime ?? null,
    kline_patterns: fullState.kline_patterns ? {
      active_count: fullState.kline_patterns.active_count,
      by_timeframe: fullState.kline_patterns.by_timeframe,
    } : null,
    cortex_11p: fullState.cortex_11p ? {
      schema: fullState.cortex_11p.schema,
      feed_status: fullState.cortex_11p.feed_status,
      price_and_pois: fullState.cortex_11p.price_and_pois,
      pattern_state_flags: fullState.cortex_11p.pattern_state_flags,
      microstructure_rulebook_3: fullState.cortex_11p.microstructure_rulebook_3,
    } : null,
    spot_magnet: fullState.spot_magnet ?? null,
    risk_constraints_reference: {
      account_equity_usd: accountEquityUsd,
      max_leverage: lr.max_leverage ?? 2.0,
      risk_per_trade_pct: lr.risk_per_trade_pct ?? 0.004,
      weekend_size_mult: th.weekend_size_mult ?? 0.5,
      max_portfolio_heat_pct: lr.max_portfolio_heat_pct ?? 0.015,
      max_concurrent_futures: lr.max_concurrent_futures ?? 1,
      min_rr: lr.min_rr ?? 1.6,
      max_stop_distance_pct: lr.max_stop_distance_pct ?? 0.022,
      max_hold_hours: th.max_hold_hours ?? 24,
      macro_blackout_minutes: lr.macro_blackout_minutes ?? 60,
    },
    fetch_errors: fullState.fetch_errors || [],
  };
}

function serializeTelemetryCompact(raw) {
  return JSON.stringify(raw, null, 2).replace(
    /\[\s*(-?\d+(?:\.\d+)?(?:\s*,\s*-?\d+(?:\.\d+)?){4,5})\s*\]/g,
    (_, inner) => `[${inner.replace(/\s+/g, " ")}]`
  );
}

async function copyTextWithFeedback(text, label, msgId = "actionMsg") {
  const msgEl = $(msgId);
  const prev = msgEl.textContent;
  let copied = false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      copied = true;
    }
  } catch {}
  if (!copied) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      copied = document.execCommand("copy");
      document.body.removeChild(ta);
    } catch {}
  }
  msgEl.textContent = copied ? label : "Clipboard blocked — open F4 Audit tab to Download .JSON.";
  msgEl.style.color = copied ? "var(--up)" : "var(--dn)";
  setTimeout(() => {
    msgEl.textContent = prev;
    msgEl.style.color = "";
  }, 3200);
}

function bindEvents() {
  $("tabNav").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (b) activateTab(b.dataset.tab);
  });
  document.addEventListener("keydown", (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName || "")) return;
    const map = { "1": "signal", "2": "regime", "3": "spot", "4": "ledger", "5": "audit" };
    if (map[e.key]) activateTab(map[e.key]);
  });
  $("chartSeg").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tf]");
    if (!b) return;
    CHART_TF = b.dataset.tf;
    document.querySelectorAll("#chartSeg .tab-btn").forEach((x) => x.classList.toggle("active", x === b));
    renderChart();
  });
  ["cEq", "cDir", "cWeekend", "cEntry", "cStop", "cTp"].forEach((id) => $(id).addEventListener("input", updateCalc));
  $("btnCopyRaw").onclick = () => {
    const raw = buildRawTelemetryPacket(STATE);
    if (!raw) return;
    const msg = window.DeskI18n ? window.DeskI18n.t("raw_copied") : "Copied compact Raw JSON (no pre-computed verdicts).";
    copyTextWithFeedback(serializeTelemetryCompact(raw), msg, "auditExportMsg");
  };
  $("btnCopyAi").onclick = () => {
    const raw = buildRawTelemetryPacket(STATE);
    if (!raw) return;
    let promptText = MASTER_QUANT_PROMPT_TEMPLATE.replace("{{RAW_JSON_PAYLOAD}}", serializeTelemetryCompact(raw));
    const meta = window.DeskI18n?.getMeta();
    if (meta && meta.code !== "en") {
      promptText = promptText.replace(
        "### LIVE RAW TELEMETRY PACKET (JSON)",
        `**Response Language:** Respond strictly in ${meta.aiName} while keeping all BTC prices, levels, and JSON field values exact.\n\n### LIVE RAW TELEMETRY PACKET (JSON)`
      );
    }
    const msg = window.DeskI18n ? window.DeskI18n.t("ai_copied") : "Copied! Paste into ChatGPT, Gemini, Claude, Grok, DeepSeek, or Kimi.";
    copyTextWithFeedback(promptText, msg);
  };
  if ($("btnCopySpotAi")) {
    $("btnCopySpotAi").onclick = () => {
      if (!STATE?.spot_magnet) return;
      const payload = {
        updated_at_utc: STATE.updated_at_utc,
        live_spot_price: activePrice(),
        spot_magnet: STATE.spot_magnet,
        cmc_liquidations: STATE.derivatives?.cmc_liquidations ?? null,
      };
      let promptText = SPOT_MAGNET_AI_PROMPT_TEMPLATE.replace("{{SPOT_JSON_PAYLOAD}}", JSON.stringify(payload, null, 2));
      const meta = window.DeskI18n?.getMeta();
      if (meta && meta.code !== "en") {
        promptText = promptText.replace(
          "### LIVE SPOT MAGNET TELEMETRY (JSON)",
          `**Response Language:** Respond strictly in ${meta.aiName} while keeping all BTC prices and JSON values exact.\n\n### LIVE SPOT MAGNET TELEMETRY (JSON)`
        );
      }
      copyTextWithFeedback(promptText, "Copied Spot Magnet DIBSE Prompt + JSON!", "spotActionMsg");
    };
  }
  window.onDeskLangChanged = () => {
    renderHeaderLive();
  };
  $("btnDlJson").onclick = () => {
    const u = URL.createObjectURL(new Blob([JSON.stringify(STATE, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = u;
    a.download = `btc-protocol-v4-state-${Date.now()}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(u), 2000);
  };
}

async function init() {
  window.DeskI18n?.init();
  bindEvents();
  STATE = await fetchJson("data/state.json?t=" + Date.now());
  $("snapMeta").textContent = `v${STATE.protocol_version || "4.0"} · Updated ${STATE.updated_at_utc} · 4H Close ${STATE.last_4h_close_utc || "—"} · Source ${STATE.ticker?.source || "—"}`;
  renderHeaderLive();
  renderSignalTab();
  renderRegimeTab();
  renderSpotTab();
  renderLedgerTab();
  renderAuditTab();
  seedCalcFromState();
  pollLivePrice();
  setInterval(pollLivePrice, 5000);
}

init().catch((err) => {
  $("snapMeta").textContent = `Failed to load data/state.json: ${err.message}`;
});
