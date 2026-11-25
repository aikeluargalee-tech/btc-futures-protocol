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
let ACTIVE_VIEW = "hub";
let CHART_TF = "h4";
let RHYME_LENS = "AUTO";
let RHYME_COND = "ALL";
let NEWS_CAT = "ALL";

async function fetchJson(url, retries = 2) {
  let lastErr = null;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (r.ok) return await r.json();
      const err = new Error(`HTTP ${r.status}`);
      err.noRetry = r.status >= 400 && r.status < 500 && r.status !== 408 && r.status !== 429;
      throw err;
    } catch (err) {
      lastErr = err;
      if (err?.noRetry || attempt >= retries) throw err;
    }
    await new Promise((res) => setTimeout(res, 500 * (attempt + 1)));
  }
  throw lastErr || new Error("Fetch failed");
}

async function pollLivePrice() {
  try {
    const r = await fetchJson("https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT", 0);
    LIVE.price = +r.price;
    LIVE.src = "BinanceVision";
    LIVE.at = Date.now();
  } catch {
    try {
      const r2 = await fetchJson("https://api.exchange.coinbase.com/products/BTC-USD/ticker", 0);
      LIVE.price = +r2.price;
      LIVE.src = "Coinbase";
      LIVE.at = Date.now();
    } catch {
      try {
        const r3 = await fetchJson("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", 0);
        const kRes = r3?.result || {};
        const kKey = Object.keys(kRes).find((k) => k !== "last");
        const px = kKey ? +kRes[kKey]?.c?.[0] : NaN;
        if (Number.isFinite(px) && px > 0) {
          LIVE.price = px;
          LIVE.src = "Kraken";
          LIVE.at = Date.now();
        } else {
          LIVE.src = null;
        }
      } catch {
        LIVE.src = null;
      }
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

  const pmG = STATE.positioning_matrix_g;
  const gRow = pmG?.status === "LIVE" ? pmG.active_cell : null;
  const gCls = gRow?.reading === "directional colour only" ? "warn" : "";
  const mtL = STATE.context_overlays?.market_time_l;
  const mtCls = (mtL?.vol_cluster_active || mtL?.awake_state === "MON_GAP_RISK") ? "dn" : (mtL?.awake_state === "QUIET_THIN" ? "warn" : (mtL?.awake_state === "QUIET_EXEC" ? "up" : ""));

  $("signalSummary").innerHTML = `
    <div class="signal-head">
      <div class="big-num ${status === "LONG" ? "up" : status === "SHORT" ? "dn" : "warn"}">${esc(status)}</div>
      <span class="badge ${stBadge}">${status === "FLAT" ? "NO FUTURES ENTRY" : esc(prop.entry_method || "FUTURES ACTIVE")}</span>
    </div>
    <p class="mut" style="margin:8px 0 4px;">Dominant 4H drivers: <b>${esc((reg.dominant_factors || []).join(" · ") || "—")}</b></p>
    <p class="mut" style="margin:0 0 6px;">1D Bias: <b>${esc(reg.daily_bias || "—")}</b> · Open Futures: <b>${(port.open_positions || []).length}/1</b> · Equity: <b>${usd(port.equity_usd, 2)}</b></p>
    <div style="display:flex;gap:6px;flex-wrap:wrap;">
      ${pmG?.status === "LIVE" ? `<span class="badge ${gCls}">Project G: ${esc(pmG.summary_line)}</span>` : ""}
      ${mtL?.status === "LIVE" ? `<span class="badge ${mtCls}">Market Time (L): ${esc(mtL.summary_line)}</span>` : ""}
    </div>
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
      ["Stop vs Day Range (L)", mtL?.expected_day_range_pct != null && prop.stop_distance_pct != null ? `${(prop.stop_distance_pct / mtL.expected_day_range_pct).toFixed(2)}x (${mtL.day_of_week} ~${num(mtL.expected_day_range_pct, 2)}%${mtL.stop_noise_warning ? " · TIGHT VS NOISE" : ""})` : "—"],
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
    ${STATE.context_overlays?.etf_flow_regime?.status === "LIVE" ? `<div style="margin-bottom:8px;"><span class="badge ${STATE.context_overlays.etf_flow_regime.regime === "ABSORPTION" || STATE.context_overlays.etf_flow_regime.regime === "SPOT-LED INFLOWS" ? "up" : STATE.context_overlays.etf_flow_regime.regime === "NEW SHORTS" ? "dn" : "warn"}">${esc(STATE.context_overlays.etf_flow_regime.summary_line)}</span></div>` : ""}
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

  const lsceCls = ((lsce.status || "").includes("OBSERVED") || (lsce.status || "").includes("CONFIRMED")) ? (lsce.side === "LOWER" ? "up" : "dn") : (lsce.status || "").includes("PROGRESS") ? "warn" : "";
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

function renderRhymeTab() {
  const cr = STATE?.cortex_rhyme;
  if (!$("rhymeHeroBox")) return;
  if (!cr || cr.meta?.status === "unavailable" || !cr.diagnostics) {
    $("rhymeHeroBox").innerHTML = `<h2>S2 CORTEX-RHYME · Historical State-Space Conditioning</h2><p class="mut">Historical archive unavailable.</p>`;
    if ($("rhymeDistBox")) $("rhymeDistBox").innerHTML = "";
    if ($("rhymeAnaloguesBox")) $("rhymeAnaloguesBox").innerHTML = "";
    if ($("rhymeMatrixGBox")) renderProjectGMatrixCard();
    return;
  }

  const lenses = cr.lenses || {};
  const chosenLens = (RHYME_LENS !== "AUTO" && lenses[RHYME_LENS]) ? lenses[RHYME_LENS] : null;
  const diag = chosenLens ? chosenLens.diagnostics : cr.diagnostics;
  const activeLensName = chosenLens ? chosenLens.lens_id : (cr.meta?.active_lens || diag.active_lens || "5D_MICROSTRUCTURE");
  const isRegime = RHYME_COND === "REGIME";

  const qRaw = isRegime ? (diag.regime_sample_quality || "thin") : (diag.sample_quality || "thin");
  const nAnalogs = isRegime ? (diag.regime_analogues_found ?? 0) : (diag.analogues_found ?? 0);
  const avgDist = isRegime ? diag.regime_avg_distance : diag.avg_vector_distance;
  const qCls = qRaw === "solid" ? "up" : qRaw === "moderate" ? "warn" : "dn";
  const posture = diag.posture_verdict || "NEUTRAL_CHOP";
  const pCls = posture.includes("POSITIVE") ? "up" : posture.includes("NEGATIVE") ? "dn" : "warn";

  const cur = cr.current_state || {};
  const rawM = cur.raw_metrics || {};
  const zVec = cur.z_vector || {};
  const regCtx = cur.regime_context || {};

  const afterMap = isRegime
    ? (chosenLens ? chosenLens.regime_matched_setups : cr.regime_matched_setups)
    : (chosenLens ? chosenLens.after_similar_setups : cr.after_similar_setups);
  const baseMap = isRegime
    ? (chosenLens ? chosenLens.regime_baseline_hours : cr.regime_baseline_hours)
    : (chosenLens ? chosenLens.baseline_all_hours : cr.baseline_all_hours);
  const edgeMap = isRegime
    ? (chosenLens ? chosenLens.regime_edge_vs_baseline : cr.regime_edge_vs_baseline)
    : (chosenLens ? chosenLens.edge_vs_baseline : cr.edge_vs_baseline);
  const analogs = chosenLens ? (chosenLens.top_analogues || []) : (cr.top_analogues || []);

  const thinWarn = qRaw === "thin"
    ? `<div class="reject-box"><b class="dn">THIN SAMPLE WARNING (n=${nAnalogs})</b> — Historical precedent under current conditioning is scarce; treat distributions as indicative only.</div>`
    : "";
  const fbNote = (RHYME_LENS === "AUTO" && diag.fallback_triggered && diag.fallback_reason)
    ? `<p class="mut" style="color:var(--warn);margin:4px 0 0;">Auto-Arbitration: ${esc(diag.fallback_reason)}</p>`
    : "";

  $("rhymeHeroBox").innerHTML = `
    <h2>S2 CORTEX-RHYME v${esc(cr.meta?.version || "1.2.0")} · Current State Vector &amp; Sample Quality</h2>
    <div class="signal-head" style="margin-bottom:8px;">
      <div>
        <div class="big-num ${qCls}">QUALITY: ${esc(qRaw.toUpperCase())} (n=${nAnalogs} · ${diag.history_days ?? "—"}d · dist ${num(avgDist, 3)})</div>
        <div class="mut">As of ${esc(cr.meta?.as_of_utc || "—")} · Lens: <b>${esc(activeLensName)}</b> · 200D SMA Context: <b>${esc(regCtx.trend_regime || "—")}</b> (${usd(regCtx.sma_200d, 0)}, ${pct(regCtx.distance_from_sma_200d_pct, 2)})</div>
      </div>
      <div>
        <span class="badge ${pCls}">${esc(posture)}</span>
        <span class="badge">24H EV: ${pct(diag.conditional_ev_24h_pct, 3)}</span>
      </div>
    </div>
    ${fbNote}
    ${thinWarn}
    <div class="grid-2" style="margin-top:8px;">
      <dl class="kv">${kv([
        ["1. Carry Funding (Z)", `${pct(rawM.funding_rate_pct, 4)} (z = ${num(zVec.funding_rate, 3)})`],
        ["2. Term Basis (Z)", `${num(rawM.basis_bps, 2)} bps (z = ${num(zVec.basis_bps, 3)})`],
        ["3. OI 24H Delta (Z)", `${pct(rawM.oi_delta_24h_pct, 2)} (z = ${num(zVec.oi_delta_24h, 3)})`],
        ["4. GK Vol 24H Ann (Z)", `${num(rawM.gk_vol_24h_ann_pct, 2)}% (z = ${num(zVec.gk_vol_24h, 3)})`],
        ["5. Taker Buy Ratio (Z)", `${num(rawM.taker_buy_ratio, 4)} (z = ${num(zVec.taker_buy_ratio, 3)})`],
        ["6. Live L2 Book Skew", rawM.live_l2_imbalance != null ? `${num(rawM.live_l2_imbalance, 4)}` : "UNAVAILABLE"],
      ])}</dl>
      <dl class="kv">${kv([
        ["Distance Metric", "Regularized Mahalanobis (ridge λ=0.05)"],
        ["Causal Z-Window", "168h trailing (zero future leakage)"],
        ["De-Clustering / Embargo", `${diag.declustering_hours ?? 24}h min spacing · ${diag.embargo_hours ?? 72}h forward embargo`],
        ["Funding–Basis Corr", `${num(diag.funding_basis_correlation, 3)}`],
        ["Baseline Pool", `${diag.baseline_hours_evaluated ?? "—"} historical hours (${cr.meta?.status || "live"})`],
        ["Mandate", "Distributional Prior Only · Zero Trade Permission"],
      ])}</dl>
    </div>
  `;

  const rowsHtml = ["4h", "24h", "72h"].map((h) => {
    const a = afterMap?.[h] || {};
    const b = baseMap?.[h] || {};
    const e = edgeMap?.[h] || {};
    const liftCls = (e.up_share_lift_pts ?? 0) >= 5 ? "up" : (e.up_share_lift_pts ?? 0) <= -5 ? "dn" : "warn";
    return `
      <tr>
        <td><b>+${esc(h.toUpperCase())}</b></td>
        <td><b>${pct(a.median_pct, 2)}</b></td>
        <td>${num(a.up_share, 1)}%</td>
        <td>${pct(a.median_up_pct, 2)} / ${pct(a.median_down_pct, 2)}</td>
        <td><b>${num(a.tail_skew_ratio, 2)}x</b></td>
        <td>${pct(b.median_pct, 2)} (${num(b.up_share, 1)}% up)</td>
        <td class="${liftCls}"><b>${(e.up_share_lift_pts ?? 0) >= 0 ? "+" : ""}${num(e.up_share_lift_pts, 1)} pts</b>${e.lift_se_pts != null ? ` <span class="mut">(±${num(e.lift_se_pts, 1)} SE)</span>` : ""} (${pct(e.median_lift_pct, 2)})</td>
      </tr>`;
  }).join("");

  $("rhymeDistBox").innerHTML = `
    <h2>Empirical Forward Distributions (${isRegime ? "Matched 200D SMA Regime" : "Full Historical Archive"}) vs. Base Rate</h2>
    <div style="overflow-x:auto;">
      <table>
        <thead>
          <tr>
            <th>Horizon</th>
            <th>Similar Median</th>
            <th>% Rose</th>
            <th>Up-Tail / Down-Tail</th>
            <th>Tail Skew</th>
            <th>Unconditional Base</th>
            <th>Edge Lift vs. Base</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    </div>
  `;

  const analogRows = analogs.map((a) => `
    <tr>
      <td>${esc(a.timestamp_utc)}</td>
      <td>${usd(a.btc_price, 1)}</td>
      <td>${num(a.distance, 3)}</td>
      <td>${esc(a.trend_regime || "—")}</td>
      <td class="${(a.ret_4h_pct ?? 0) >= 0 ? "up" : "dn"}">${pct(a.ret_4h_pct, 2)}</td>
      <td class="${(a.ret_24h_pct ?? 0) >= 0 ? "up" : "dn"}">${pct(a.ret_24h_pct, 2)}</td>
      <td class="${(a.ret_72h_pct ?? 0) >= 0 ? "up" : "dn"}">${pct(a.ret_72h_pct, 2)}</td>
    </tr>`).join("");

  $("rhymeAnaloguesBox").innerHTML = `
    <h2>Top Historical Analogues (${analogs.length} Shown · De-Clustered ≥ 24h)</h2>
    ${analogs.length ? `
      <div style="overflow-x:auto;">
        <table>
          <thead>
            <tr><th>Timestamp (UTC)</th><th>BTC Price</th><th>Dist (σ)</th><th>200D Regime</th><th>+4H</th><th>+24H</th><th>+72H</th></tr>
          </thead>
          <tbody>${analogRows}</tbody>
        </table>
      </div>` : `<p class="mut">No historical analogues within cutoff threshold.</p>`}
  `;

  renderProjectGMatrixCard();
}

function renderProjectGMatrixCard() {
  const box = $("rhymeMatrixGBox");
  if (!box) return;
  const pm = STATE.positioning_matrix_g;
  if (!pm) {
    box.innerHTML = "";
    return;
  }
  const active = pm.active_cell || {};
  const rows = pm.matrix_rows || [];
  const band = pm.daily_funding_band || {};
  const headerMeta = pm.status === "LIVE"
    ? `Live Funding: <b>${pct(pm.funding_8h_pct, 5)}</b>/8h (<b>${pct(pm.funding_daily_pct, 4)}</b>/day · Band <b>${esc(band.band || "—")}</b>) · OI Δ (${esc(pm.oi_window || "3d")}): <b>${pct(pm.oi_delta_pct, 2)}</b> · 200D SMA: ${usd(pm.sma_200d, 0)}`
    : `Status: ${esc(pm.reason || "unavailable")}`;

  const tableRows = rows.map((r) => {
    const isAct = pm.status === "LIVE" && r.id === active.id;
    const bg = isAct ? (r.reading === "directional colour only" ? "background:var(--warn-bg);font-weight:700;" : "background:var(--acc-soft);font-weight:700;") : "";
    const rdCls = r.reading === "directional colour only" ? "warn" : (r.reading === "never occurred in 299 weeks" ? "dn" : "mut");
    return `
      <tr style="${bg}">
        <td>${isAct ? "▶ " : ""}${esc(r.regime_label)}</td>
        <td>${esc(r.state_label)} (${esc(r.funding_sign)} / ${esc(r.oi_sign)})</td>
        <td>${r.n}</td>
        <td>${r.mean_7d_pct != null ? pct(r.mean_7d_pct, 2) : "—"}</td>
        <td>${r.median_7d_pct != null ? pct(r.median_7d_pct, 2) : "—"}</td>
        <td>${r.hit_rate_pct != null ? `${r.hit_rate_pct}%` : "—"}</td>
        <td>${r.mean_14d_pct != null ? pct(r.mean_14d_pct, 2) : "—"}</td>
        <td class="${rdCls}">${esc(r.reading)}</td>
      </tr>`;
  }).join("");

  const pmH = STATE.context_overlays?.patient_money_h;
  const cApr = pmH?.carry_apr_pct;
  const cCls = typeof cApr === "number" ? (cApr >= 10 ? "up" : cApr < 2 ? "warn" : "") : "";
  const cBadge = pmH?.carry_summary ? ` · <span class="badge ${cCls}">${esc(pmH.carry_summary)}</span>` : "";
  const hLine = pmH?.status === "LIVE"
    ? `<div style="margin-bottom:6px;font-size:11px;color:var(--muted);"><b>Patient Money (H):</b> Dollar Funding <b>${pmH.funding_8h_usd != null ? (pmH.funding_8h_usd >= 0 ? "+" : "-") + "$" + Math.round(Math.abs(pmH.funding_8h_usd)).toLocaleString("en-US") : "—"}/8h</b> (${esc(pmH.crowd_payer || "—")}) · Aggression × OI: <span class="badge">${esc(pmH.aggression_oi_state || "—")}</span>${cBadge}</div>`
    : "";

  box.innerHTML = `
    <h2>Project G · 8-Cell Positioning Decision Matrix (299 Non-Overlapping Weeks · Context Only)</h2>
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:6px;">
      <div class="mut">${headerMeta}</div>
      ${pm.status === "LIVE" ? `<span class="badge ${active.reading === "directional colour only" ? "warn" : ""}">${esc(pm.summary_line)}</span>` : ""}
    </div>
    ${hLine}
    <div style="overflow-x:auto;">
      <table>
        <thead>
          <tr><th>Regime</th><th>Leverage State (Fund / OI)</th><th>n</th><th>Mean 7d</th><th>Med 7d</th><th>Hit</th><th>Mean 14d</th><th>Reading</th></tr>
        </thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
    <p class="mut" style="margin:6px 0 0;font-size:10px;">
      <b>${esc(pm.guardrail || "Context only — no cell authorizes a trade.")}</b> Signal lives strictly in tail (&lt;-0.01%/day + rising OI below 200D SMA, n=18 [50–87% CI]); 7 of 8 cells carry no standalone edge.
    </p>
  `;
}

function fmtUsdCompact(v) {
  if (typeof v !== "number" || !isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e12) return "$" + (v / 1e12).toFixed(2) + "T";
  if (abs >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
  if (abs >= 1e6) return "$" + (v / 1e6).toFixed(1) + "M";
  return usd(v, 0);
}

function fmtAgeMin(m) {
  if (typeof m !== "number" || !isFinite(m)) return "—";
  if (m < 0) {
    const a = Math.abs(Math.round(m));
    if (a < 60) return `T-${a}m`;
    const h = Math.floor(a / 60);
    const rem = a % 60;
    return h < 48 ? `T-${h}h ${rem}m` : `T-${Math.round(h / 24)}d`;
  }
  const r = Math.round(m);
  if (r < 60) return `${r}m ago`;
  const h = Math.floor(r / 60);
  if (h < 48) return `${h}h ${r % 60}m ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function renderNewsTab() {
  const nm = STATE.news_macro;
  if (!nm) {
    $("newsMacroHeroBox").innerHTML = `<h2>News &amp; Macro Desk</h2><p class="mut">News &amp; Macro telemetry not yet generated in this snapshot.</p>`;
    $("newsCryptoPulseBox").innerHTML = "";
    $("newsCalendarBox").innerHTML = "";
    $("newsWireBox").innerHTML = "";
    return;
  }

  const mb = nm.macro_bias || {};
  const status = mb.status || "MIXED";
  const stCls = status === "RISK_ON" ? "up" : status === "RISK_OFF" ? "dn" : "warn";
  const nextHigh = mb.next_high_impact;
  const xa = nm.cross_asset || {};

  const tileMeta = [
    ["DXY", xa.dxy, 2, false],
    ["US10Y", xa.us10y, 2, true],
    ["VIX", xa.vix, 2, false],
    ["SPX", xa.spx, 1, false],
    ["NDX", xa.ndx, 1, false],
  ];
  const tilesHtml = tileMeta.map(([label, obj, dec, isPct]) => {
    const valStr = obj?.value != null ? `${num(obj.value, dec)}${isPct ? "%" : ""}` : "—";
    const c1 = obj?.chg1d_pct;
    const r10 = obj?.roc10_pct;
    const chgCls = typeof c1 === "number" ? (label === "DXY" || label === "US10Y" || label === "VIX" ? (c1 <= -0.25 ? "up" : c1 >= 0.25 ? "dn" : "mut") : (c1 >= 0.25 ? "up" : c1 <= -0.25 ? "dn" : "mut")) : "mut";
    return `
      <div class="macro-tile">
        <div class="lbl">${esc(label)}</div>
        <div class="val">${esc(valStr)}</div>
        <div class="mut"><span class="${chgCls}">${pct(c1, 2)} 1D</span> · ROC10 ${pct(r10, 1)}</div>
      </div>`;
  }).join("");

  const drvPills = (mb.drivers || []).map((d) => {
    const cls = d.tone === "bull" ? "up" : d.tone === "bear" ? "dn" : "";
    return `<span class="badge ${cls}">${esc(d.label)}: ${esc(d.value)}</span>`;
  }).join(" ");

  const evText = nextHigh
    ? `${esc(nextHigh.title)} · ${esc(nextHigh.time_utc)} (${nextHigh.minutes_away > 0 ? "in " + Math.round(nextHigh.minutes_away) + "m" : Math.round(nextHigh.minutes_away) + "m"})`
    : "No USD High-Impact release scheduled in next 7d";

  $("newsMacroHeroBox").innerHTML = `
    <h2>Macro Risk Backdrop &amp; Cross-Asset Tape</h2>
    <div class="signal-head" style="margin-bottom:6px;">
      <div>
        <div class="big-num ${stCls}">${esc(status.replace("_", "-"))} (${mb.score >= 0 ? "+" : ""}${mb.score ?? 0} / ±${mb.max_abs_score ?? 6})</div>
        <div class="mut">Next USD High-Impact: <b>${evText}</b></div>
      </div>
      <div>
        <span class="badge ${mb.blackout_active ? "dn" : "up"}">${mb.blackout_active ? "≤60M MACRO BLACKOUT" : "NO 60M BLACKOUT"}</span>
        <span class="badge">UTC ${esc(nm.updated_at_utc || STATE.updated_at_utc || "—")}</span>
      </div>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:4px;">${drvPills || '<span class="mut">No macro drivers available</span>'}</div>
    <div class="macro-tile-grid">${tilesHtml}</div>
  `;

  const cp = nm.crypto_pulse || {};
  const cg = cp.cmc_global || {};
  const fg = cp.cmc_fear_greed || {};
  const alt = cp.cmc_altseason || {};
  const ce = cp.cmc_etf || {};
  const fe = cp.farside_etf || {};
  const st = cp.stables || {};
  $("newsCryptoPulseBox").innerHTML = `
    <h2>CoinMarketCap Market Pulse &amp; Institutional Flows</h2>
    <dl class="kv">${kv([
      ["Total Crypto MCap", cg.total_market_cap_usd != null ? `${fmtUsdCompact(cg.total_market_cap_usd)} (${pct(cg.total_market_cap_24h_pct, 2)} 24h)` : "—"],
      ["BTC / ETH Dominance", cg.btc_dominance_pct != null ? `${num(cg.btc_dominance_pct, 2)}% BTC · ${num(cg.eth_dominance_pct, 2)}% ETH` : "—"],
      ["24H Global Spot Vol", cg.total_volume_24h_usd != null ? fmtUsdCompact(cg.total_volume_24h_usd) : "—"],
      ["CMC Fear & Greed", fg.score != null ? `${fg.score}/100 (${fg.label}) · 7D ago ${fg.last_week_score ?? "—"}` : (cp.alt_fng_value != null ? `${cp.alt_fng_value} (${cp.alt_fng_label})` : "—")],
      ["CMC Altcoin Season", alt.index != null ? `${alt.index}/100 (${alt.label})` : "—"],
      ["CMC BTC ETF (1D / 5D)", ce.btc_latest_usd_m != null ? `$${num(ce.btc_latest_usd_m, 1)}M (${ce.latest_date}) · 5D $${num(ce.btc_5d_sum_usd_m, 1)}M` : "—"],
      ["CMC ETH ETF (1D / 5D)", ce.eth_latest_usd_m != null ? `$${num(ce.eth_latest_usd_m, 1)}M · 5D $${num(ce.eth_5d_sum_usd_m, 1)}M` : "—"],
      ["Farside BTC ETF (1D / 5D)", fe.latest_usd_m != null ? `$${num(fe.latest_usd_m, 1)}M (${fe.latest_date}) · 5D $${num(fe.sum5_usd_m, 1)}M` : "—"],
      ["USDT+USDC Liquidity 7D", st.total_usd_b != null ? `$${num(st.total_usd_b, 2)}B (${pct(st.chg7d_pct, 2)})` : "—"],
      ["ETF Flow Regime (Project ETF)", STATE.context_overlays?.etf_flow_regime?.status === "LIVE" ? `${STATE.context_overlays.etf_flow_regime.regime} (5D $${num(STATE.context_overlays.etf_flow_regime.inputs?.etf_5d_usd_m, 1)}M · OI ${pct(STATE.context_overlays.etf_flow_regime.inputs?.oi_delta_pct, 2)})` : "—"],
      ["Deribit DVOL (30D IV)", cp.dvol != null ? `${num(cp.dvol, 2)}` : "—"],
    ])}</dl>
  `;

  const cal = nm.calendar_usd || [];
  $("newsCalendarBox").innerHTML = `
    <h2>USD High &amp; Medium Economic Calendar (ForexFactory)</h2>
    ${cal.length ? `
      <div style="overflow-x:auto;">
        <table>
          <thead><tr><th>Impact</th><th>Event</th><th>UTC / Countdown</th><th>Forecast / Prev</th></tr></thead>
          <tbody>${cal.map((ev) => {
            const impCls = ev.impact === "HIGH" ? (ev.blackout_60m ? "dn" : "warn") : "";
            const cd = ev.minutes_away >= 0 ? `in ${Math.round(ev.minutes_away)}m` : `${Math.round(ev.minutes_away)}m`;
            return `
              <tr>
                <td><span class="badge ${impCls}">${esc(ev.impact)}</span></td>
                <td><b>${esc(ev.title)}</b></td>
                <td>${esc(ev.time_utc)}<div class="mut">${esc(cd)}${ev.blackout_60m ? ' · <b class="dn">BLACKOUT</b>' : ""}</div></td>
                <td>${esc(ev.forecast || "—")} / ${esc(ev.previous || "—")}</td>
              </tr>`;
          }).join("")}</tbody>
        </table>
      </div>` : `<p class="mut">No USD High or Medium macro releases within the next 7 days.</p>`}
  `;

  const allHeadlines = nm.headlines || [];
  const filtered = NEWS_CAT === "ALL" ? allHeadlines : allHeadlines.filter((h) => h.category === NEWS_CAT);
  const catCls = (c) => (c === "FED_MACRO" ? "warn" : c === "BTC_ETF" ? "up" : c === "DERIVS_LIQ" || c === "REGULATION" ? "dn" : "");
  const catLbl = (c) => ({ BTC_ETF: "BTC / ETF", FED_MACRO: "FED / MACRO", DERIVS_LIQ: "DERIVS / LIQ", REGULATION: "REGULATION", MARKET_WIRE: "BTC WIRE" }[c] || c);

  $("newsWireBox").innerHTML = `
    <h2>Live Crypto &amp; Macro Wire (${filtered.length} Shown / ${allHeadlines.length} Total)</h2>
    ${filtered.length ? filtered.map((h) => `
      <div class="news-row">
        <div>
          <div class="news-title"><a href="${esc(h.url)}" target="_blank" rel="noopener noreferrer">${esc(h.title)}</a></div>
          ${h.summary ? `<div class="mut" style="margin-top:2px;">${esc(h.summary)}</div>` : ""}
          <div class="news-meta"><b>${esc(h.source)}</b> · ${esc(fmtAgeMin(h.age_minutes))} · ${esc(h.published_utc)}</div>
        </div>
        <span class="badge ${catCls(h.category)}">${esc(catLbl(h.category))}</span>
      </div>`).join("") : `<p class="mut">No headlines match category ${esc(NEWS_CAT)}.</p>`}
    <p class="mut" style="margin:8px 0 0;font-size:10px;">
      Active keyless feeds (${(nm.sources_ok || []).length}): ${esc((nm.sources_ok || []).join(", ") || "—")}
      ${(nm.sources_failed || []).length ? ` · Soft failures: ${esc(nm.sources_failed.join(" | "))}` : ""}
    </p>
  `;
}

function renderShieldTab() {
  const sh = STATE.spot_shield;
  if (!sh || sh.status === "unavailable" || !sh.sleeve1 || !sh.sleeve2) {
    $("shieldHeroBox").innerHTML = `<h2>Spot Shield (80/20 Dual-Sleeve Compass)</h2><p class="mut">Spot Shield telemetry unavailable (${esc((sh?.errors || []).join(", ") || "waiting for cycle")}).</p>`;
    $("shieldS1Box").innerHTML = "";
    $("shieldS2Box").innerHTML = "";
    $("shieldAuditBox").innerHTML = "";
    $("shieldGuideBox").innerHTML = "";
    return;
  }

  const pf = sh.portfolio || {};
  const qr = pf.quarterly_rebalance || {};
  const s1 = sh.sleeve1 || {};
  const s2 = sh.sleeve2 || {};
  const s1i = s1.indicators || {};
  const s2i = s2.indicators || {};
  const s1c = s1.conditions || {};
  const s2c = s2.conditions || {};
  const btcPct = pf.target_btc_pct ?? 0;
  const usdtPct = pf.target_usdt_pct ?? (100 - btcPct);
  const actCls = (a) => (a === "BUY BTC" || a === "HOLD BTC" ? "up" : a === "SELL BTC" ? "dn" : "warn");
  const posCls = (p) => (p === "LONG" ? "up" : "warn");
  const rowCond = (lbl, ok, detail) => `
    <div class="row">
      <div><div class="title">${esc(lbl)}</div><div class="mut">${esc(detail)}</div></div>
      <span class="badge ${ok ? "up" : "dn"}">${ok ? "PASS" : "FAIL"}</span>
    </div>`;

  const pmH = STATE.context_overlays?.patient_money_h;
  const cApr = pmH?.carry_apr_pct;
  const cCls = typeof cApr === "number" ? (cApr >= 10 ? "up" : cApr < 2 ? "warn" : "") : "";

  $("shieldHeroBox").innerHTML = `
    <h2>Spot Shield (80/20) · Pure Closed-Bar BTCUSDT Portfolio Posture</h2>
    <div class="signal-head" style="margin-bottom:6px;">
      <div>
        <div class="big-num ${btcPct > 0 ? "up" : "warn"}">${esc(pf.posture_label || "100% USDT")}</div>
        <div class="mut">${esc(pf.split_label || "80% 4H VWAP Shield / 20% 1D TTM Squeeze")} · Updated ${esc(sh.updated_at_utc || "—")}</div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;">
        <span class="badge ${actCls(s1.action)}">S1 (80%): ${esc(s1.action)}</span>
        <span class="badge ${actCls(s2.action)}">S2 (20%): ${esc(s2.action)}</span>
        ${pmH?.carry_summary ? `<span class="badge ${cCls}">${esc(pmH.carry_summary)}</span>` : ""}
      </div>
    </div>
    <div class="shield-split-bar">
      ${btcPct > 0 ? `<div class="shield-seg" style="width:${btcPct}%;background:var(--up-bg);color:var(--up);border-right:${usdtPct > 0 ? "1px solid var(--line-dark)" : "none"};">BTC ${btcPct}%</div>` : ""}
      ${usdtPct > 0 ? `<div class="shield-seg" style="width:${usdtPct}%;background:var(--warn-bg);color:var(--warn);">USDT CASH ${usdtPct}%</div>` : ""}
    </div>
    <div class="reject-box" style="margin-top:8px;">
      <b>Operational Boundary:</b> Slow mechanical <b>Spot-Only</b> rotation compass. Keep strictly in a separate capital bucket from <b>F3 Spot Magnet (DIBSE)</b> tactical sweep inventory. Next Quarterly Rebalance (±3% band): <b>${esc(qr.next_rebalance_utc || "—")}</b> (in ${num(qr.days_remaining, 1)}d).
    </div>
  `;

  $("shieldS1Box").innerHTML = `
    <h2>Sleeve #1 · 80% Weight · 4H Rolling VWAP Shield (tier1_5_vwap_shield)</h2>
    <div class="signal-head" style="margin-bottom:8px;">
      <div class="big-num ${posCls(s1.position_state)}">${esc(s1.action)}</div>
      <span class="badge ${posCls(s1.position_state)}">${esc(s1.position_state)} · ${num(s1.days_in_state, 1)}d</span>
    </div>
    ${rowCond("1. Macro Shield (Close > 120D EMA)", s1c.above_120d_ema, `Close ${usd(s1i.close, 1)} vs 120D EMA ${usd(s1i.macro_120d_ema, 1)} (${pct(s1i.dist_to_macro_ema_pct, 2)})`)}
    ${rowCond("2. Upper Band (Close > RVWAP90 + 0.5×ATR)", s1c.above_upper_band, `Upper ${usd(s1i.upper_band, 1)} (${pct(s1i.dist_to_upper_band_pct, 2)}) · Lower Exit ${usd(s1i.lower_band, 1)}`)}
    ${rowCond("3. 12-Bar RVWAP Slope > 0 (48H Trend)", s1c.vwap_slope_rising, `Slope ${usd(s1i.vwap_slope_12, 1)} · RVWAP(90) ${usd(s1i.rolling_vwap_90, 1)}`)}
    <dl class="kv" style="margin-top:8px;">${kv([
      ["Closed 4H Bar UTC", s1.last_bar_utc || "—"],
      ["ATR(14) 4H / ±0.50 Buffer", `${usd(s1i.atr_14, 1)} (±${usd((s1i.atr_14 || 0) * 0.5, 1)})`],
      ["3.0×ATR Active Stop", s1.active_stop_loss != null ? usd(s1.active_stop_loss, 1) : "FLAT (None latched)"],
      ["Last State Flip UTC", s1.last_flip_utc || "—"],
    ])}</dl>
  `;

  $("shieldS2Box").innerHTML = `
    <h2>Sleeve #2 · 20% Weight · 1D TTM Squeeze (Experimental Cap)</h2>
    <div class="signal-head" style="margin-bottom:8px;">
      <div class="big-num ${posCls(s2.position_state)}">${esc(s2.action)}</div>
      <span class="badge ${posCls(s2.position_state)}">${esc(s2.position_state)} · ${num(s2.days_in_state, 1)}d</span>
    </div>
    ${rowCond("1. BB(20,2) Inside KC(20,1.5) Squeeze", s2i.squeeze_on, `Active Streak: ${s2i.squeeze_streak_days ?? 0}d / 3d min · BB/KC Ratio ${num(s2i.bb_kc_width_ratio, 2)}x`)}
    ${rowCond("2. Squeeze Release Trigger Today", s2c.squeeze_release, s2c.squeeze_release ? "Fired today after >= 3d coil" : "No release on latest 1D close")}
    ${rowCond("3. Causal OLS Momentum > 0 & Rising", s2c.mom_positive && s2c.mom_rising, `Mom ${num(s2i.mom_ols, 1)} vs Prev ${num(s2i.prev_mom_ols, 1)}`)}
    ${rowCond("4. Above KC Mid & SMA(21) Trail", s2c.above_kc_mid && s2c.above_sma_21, `Close ${usd(s2i.close, 1)} vs KC Mid ${usd(s2i.kc_mid_ema20, 1)} / SMA21 ${usd(s2i.sma_21_exit, 1)}`)}
    <dl class="kv" style="margin-top:8px;">${kv([
      ["Closed 1D Bar UTC", s2.last_bar_utc || "—"],
      ["ATR(14) 1D / 2.0×ATR Stop", `${usd(s2i.atr_14, 1)} / ${s2.active_stop_loss != null ? usd(s2.active_stop_loss, 1) : "FLAT"}`],
      ["Last State Flip UTC", s2.last_flip_utc || "—"],
    ])}</dl>
  `;

  const w = sh.audit_warnings || {};
  $("shieldAuditBox").innerHTML = `
    <h2>Independent Risk Audit &amp; Psychology Reality Check</h2>
    <div style="overflow-x:auto;">
      <table>
        <thead><tr><th>Sleeve / Metric</th><th>Full Sample</th><th>OOS / Stress</th><th>Audit Caveat &amp; Live Expectation</th></tr></thead>
        <tbody>
          <tr><td><b>Sleeve #1 (80%)</b> · 4H VWAP Shield</td><td>+395.3% · 1.07 Sharpe · -22.8% DD</td><td><b>27/27</b> beat B&amp;H · +15.1% OOS</td><td class="mut">${esc(w.sleeve1_realistic_expectation || "")}</td></tr>
          <tr><td><b>Sleeve #2 (20%)</b> · 1D TTM Squeeze</td><td>+93.9% · 2.31x Payoff · 18 Trades</td><td>+42.3% OOS · 8/27 blend gate</td><td class="mut">${esc(w.sleeve2_sample_warning || "")}</td></tr>
          <tr><td><b>Execution &amp; Friction</b></td><td>Closed 4H/1D OHLCV only</td><td>0.30% RT backtest (0.075% BNB)</td><td class="mut">${esc(w.fee_schedule_note || "")}</td></tr>
        </tbody>
      </table>
    </div>
  `;

  $("shieldGuideBox").innerHTML = `
    <h2>How Sleeve #1 &amp; Sleeve #2 Work (Plain-English Cheat Sheet)</h2>
    <div class="grid-2">
      <div>
        <p style="margin:0 0 6px;"><b>Sleeve #1 — Core Trend Engine (80% · Closed 4H Bars)</b></p>
        <ul class="mut" style="margin:0;padding-left:16px;line-height:1.5;">
          <li><b>Job:</b> Rides sustained multi-week Bitcoin uptrends and automatically steps into 100% USDT during macro bear markets (~65% time in cash historically).</li>
          <li><b>Buys BTC only when all 3 agree:</b> Close is above the shifted <b>120D EMA</b> macro shield, above the 15-day Rolling VWAP + <b>0.50×ATR(14)</b> noise buffer, and the 12-bar VWAP slope is rising.</li>
          <li><b>Exits to USDT when:</b> Closed 4H price falls below 120D EMA, breaks below RVWAP − 0.50×ATR, or hits the <b>3.0×ATR</b> hard stop.</li>
        </ul>
      </div>
      <div>
        <p style="margin:0 0 6px;"><b>Sleeve #2 — Volatility Breakout Sidekick (20% Cap · Closed 1D Bars)</b></p>
        <ul class="mut" style="margin:0;padding-left:16px;line-height:1.5;">
          <li><b>Job:</b> Catches sharp coiled breakouts — including violent bottom rebounds while price is still below the 120D EMA (<b>no macro off-switch</b>).</li>
          <li><b>Buys BTC when:</b> Daily Bollinger Bands stay compressed inside Keltner Channels for <b>&gt;= 3 consecutive days</b>, then release with rising positive 20-bar OLS momentum and Close &gt; KC Mid.</li>
          <li><b>Exits to USDT when:</b> Daily close drops below <b>SMA(21)</b>, OLS momentum turns negative (&lt; 0), or the <b>2.0×ATR</b> catastrophe stop hits.</li>
        </ul>
      </div>
    </div>
    <p class="mut" style="margin:8px 0 0;border-top:1px solid var(--line);padding-top:6px;">
      <b>80/20 Portfolio Rule:</b> Both sleeves track completely segregated BTC/USDT ledgers (one sleeve never sells the other's BTC) using pure closed Binance Spot OHLCV only. Rebalance back to 80/20 quarterly (Jan 1, Apr 1, Jul 1, Oct 1 · 00:00 UTC) only if drift exceeds <b>±3%</b> ([77%, 83%]).
    </p>
  `;
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
    ["Session Range Check (L)", (() => {
      const mt = STATE?.context_overlays?.market_time_l;
      if (!mt || !mt.expected_day_range_pct || stopPct <= 0) return "—";
      const ratio = stopPct / mt.expected_day_range_pct;
      return `${mt.day_of_week} ~${mt.expected_day_range_pct}% day · Stop ${ratio.toFixed(2)}x${ratio < 0.55 ? " (TIGHT VS NOISE)" : ""}${mt.vol_cluster_active ? " · >2% 1H VOL" : ""}`;
    })()],
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

function renderEntryHub() {
  const host = $("entryHubView");
  if (!host || !STATE) return;
  const tr = (k, fb) => (window.DeskI18n ? window.DeskI18n.t(k) : fb) || fb;
  const sig = STATE.signal || {};
  const reg = STATE.regime || {};
  const sor = STATE.state_of_regime || {};
  const kp = STATE.kline_patterns || {};
  const sm = STATE.spot_magnet || {};
  const smReg = sm.regime_diagnosis || {};
  const dibse = sm.dibse || {};
  const cr = STATE.cortex_rhyme || {};
  const crDiag = cr.diagnostics || {};
  const cr24Med = cr.after_similar_setups?.["24h"]?.median_pct;
  const nm = STATE.news_macro || {};
  const mb = nm.macro_bias || {};
  const sh = STATE.spot_shield || {};
  const pf = sh.portfolio || {};
  const port = STATE.portfolio || {};
  const ov = STATE.context_overlays || {};
  const mtL = ov.market_time_l;
  const etfReg = ov.etf_flow_regime;
  const pmH = ov.patient_money_h;
  const pmG = STATE.positioning_matrix_g;

  const sigSt = sig.status || "FLAT";
  const sigCls = sigSt === "LONG" ? "up" : sigSt === "SHORT" ? "dn" : "warn";
  const crTier = String(crDiag.sample_quality || "—").toUpperCase();
  const crN = crDiag.analogues_found ?? 0;
  const crCls = crDiag.sample_quality === "solid" ? "up" : crDiag.sample_quality === "moderate" ? "warn" : "dn";
  const nmStatus = mb.status || "MIXED";
  const nmCls = nmStatus === "RISK_ON" ? "up" : nmStatus === "RISK_OFF" ? "dn" : "warn";
  const btcPct = pf.target_btc_pct ?? 0;
  const usdtPct = pf.target_usdt_pct ?? (100 - btcPct);
  const carryShort = pmH?.carry_apr_pct != null ? ` · Carry ${pct(pmH.carry_apr_pct, 2)} APR` : "";
  const nextEvt = mb.next_high_impact?.title || "No High-Impact 7d";

  const cards = [
    {
      tab: "signal",
      num: "01",
      title: tr("tab_f1", "Signal Tab"),
      badge: sigSt,
      badgeCls: sigCls,
      status: `Regime ${num(reg.score, 1)}/100 (${reg.bias || "—"}) · ${mtL?.summary_line || "4H Cycle"}`,
      desc: "4H futures qualification, order sizing, Market Time (L) & AI prompt",
    },
    {
      tab: "regime",
      num: "02",
      title: tr("tab_f2", "Regime & Kline Patterns"),
      badge: sor.code || "REGIME",
      badgeCls: sor.bias === "BULL" ? "up" : sor.bias === "BEAR" ? "dn" : "warn",
      status: `${sor.name || "—"} · ${kp.active_count ?? 0} Active Kline Pattern(s)`,
      desc: "5-State Regime Radar, 10 Kline Patterns, 11-Playbook & 4H/1D chart",
    },
    {
      tab: "spot",
      num: "03",
      title: tr("tab_spot", "Spot Magnet (DIBSE)"),
      badge: dibse.rotation || "SPOT",
      badgeCls: String(dibse.rotation || "").startsWith("USDT") ? "up" : "warn",
      status: `${smReg.name || "—"} · ${etfReg?.regime ? "ETF " + etfReg.regime : "VWAP Radar"}`,
      desc: "5-Regime Spot Radar, LSCE sweep gate, liquidation ladder & DIBSE",
    },
    {
      tab: "rhyme",
      num: "04",
      title: tr("tab_rhyme", "S2 Cortex-Rhyme"),
      badge: `${crTier} N=${crN}`,
      badgeCls: crCls,
      status: `+24h Med ${pct(cr24Med, 2)} · Project G: ${pmG?.active_cell?.reading || pmG?.status || "—"}`,
      desc: "6D microstructure analogues, 8-Cell Project G matrix & Patient Money (H)",
    },
    {
      tab: "news",
      num: "05",
      title: tr("tab_news", "News & Macro"),
      badge: nmStatus,
      badgeCls: nmCls,
      status: `${(nm.headlines || []).length} Headlines · Next USD: ${nextEvt}`,
      desc: "Curated BTC/macro feed, cross-asset pulse, ETF flow regime & USD calendar",
    },
    {
      tab: "shield",
      num: "06",
      title: tr("tab_shield", "Spot Shield (80/20)"),
      badge: `BTC ${btcPct}% / USDT ${usdtPct}%`,
      badgeCls: btcPct > 0 ? "up" : "warn",
      status: `S1 ${sh.sleeve1?.action || "—"} · S2 ${sh.sleeve2?.action || "—"}${carryShort}`,
      desc: "Pure closed-bar 80/20 BTC↔USDT dual-sleeve bear shield & Carry APR check",
    },
    {
      tab: "ledger",
      num: "07",
      title: tr("tab_f3", "Paper Ledger & Risk Calc"),
      badge: "MAX 2.0x",
      badgeCls: "",
      status: `Open ${(port.open_positions || []).length}/1 · Eq ${usd(port.equity_usd, 0)} · ${mtL ? mtL.day_of_week + " ~" + num(mtL.expected_day_range_pct, 2) + "% day" : "0.40% Risk"}`,
      desc: "Interactive v4.0 position sizing calculator, paper ledger & session check",
    },
    {
      tab: "audit",
      num: "08",
      title: tr("tab_f4", "Audit Log & Config"),
      badge: `v${STATE.protocol_version || "4.0"}`,
      badgeCls: "",
      status: `Updated ${STATE.updated_at_utc || "—"} · Raw JSON Export`,
      desc: "Historical cycle audit log, frozen risk rules & raw telemetry download",
    },
  ];

  const trapSum = window.SpotTrapsModule?.getHubSummary ? window.SpotTrapsModule.getHubSummary(STATE) : null;
  const trapBadge = trapSum
    ? `START HERE · ${trapSum.activeCount} ACTIVE${trapSum.watchCount ? " / " + trapSum.watchCount + " WATCH" : ""}`
    : "START HERE · 16+1";
  const trapBadgeCls = trapSum?.activeCount > 0 ? "dn" : trapSum?.watchCount > 0 ? "warn" : "up";
  const trapStatus = trapSum
    ? `Phase 1: ${trapSum.trafficLight.color}${trapSum.topTitles.length ? " · Active: " + trapSum.topTitles.join(", ") : " · 16 Spot Traps + Bonus B1 Ready"}`
    : "16 Spot Traps + Bonus B1 ('If-Then' Chart Hygiene) + Pre-Trade Decision Scanner";

  const srInfo = window.SrMapModule?.getHubInfo
    ? window.SrMapModule.getHubInfo(STATE)
    : { badge: "FINAL DESK", badgeCls: "warn", status: "1.0x Spot Final Decision Desk" };

  host.innerHTML = `
    <div class="hub-header">
      <span>// SELECT WORKSTATION MODULE</span>
      <span>CLICK CARD OR PRESS KEYS [1–9, M] &#9658;</span>
    </div>
    <button type="button" class="hub-featured-card" data-open-tab="traps">
      <div class="hub-card-top">
        <div class="hub-card-left">
          <span class="hub-num">[09]</span>
          <span class="hub-title">${esc(tr("tab_traps", "Spot Trap Radar & Field Guide"))}</span>
        </div>
        <span class="badge ${esc(trapBadgeCls)}">${esc(trapBadge)}</span>
      </div>
      <div class="hub-status">&#9658; ${esc(trapStatus)}</div>
      <div class="hub-desc">New to BTC? Check today's active market traps, scan your trade idea or chart call before clicking, or read the 16+1 Spot Field Guide.</div>
    </button>
    <div class="hub-grid">
      ${cards.map((c) => `
        <button type="button" class="hub-card" data-open-tab="${esc(c.tab)}">
          <div class="hub-card-top">
            <div class="hub-card-left">
              <span class="hub-num">[${esc(c.num)}]</span>
              <span class="hub-title">${esc(c.title)}</span>
            </div>
            <span class="badge ${esc(c.badgeCls)}">${esc(c.badge)}</span>
          </div>
          <div class="hub-status">&#9658; ${esc(c.status)}</div>
          <div class="hub-desc">${esc(c.desc)}</div>
        </button>
      `).join("")}
      <button type="button" class="hub-card wide" data-open-tab="srmap">
        <div class="hub-card-top">
          <div class="hub-card-left">
            <span class="hub-num">[10]</span>
            <span class="hub-title">${esc(tr("tab_srmap", "Final Decision Desk"))}</span>
          </div>
          <span class="badge ${esc(srInfo.badgeCls)}">${esc(srInfo.badge)}</span>
        </div>
        <div class="hub-status">&#9658; ${esc(srInfo.status)}</div>
        <div class="hub-desc">Final 1.0x Spot Decision Gate: Conflict Priority Veto + Regime &amp; Flow Filters + S/R Staircase + Dual Magnets + Run Log.</div>
      </button>
    </div>
    <div class="hub-footer">
      <span>COMMAND HUB · 10 MODULES</span>
      <span>KEYS [1–9, M] OPEN · [0/ESC] HUB · NO LOGIN</span>
    </div>
  `;
}

function showHub() {
  ACTIVE_VIEW = "hub";
  $("entryHubView")?.classList.add("active");
  $("moduleChrome")?.classList.add("hidden");
  $("btnBackHub")?.classList.add("hidden");
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
  window.scrollTo(0, 0);
}

function activateTab(tabId) {
  ACTIVE_VIEW = tabId;
  $("entryHubView")?.classList.remove("active");
  $("moduleChrome")?.classList.remove("hidden");
  $("btnBackHub")?.classList.remove("hidden");
  document.querySelectorAll("#tabNav .tab-btn[data-tab]").forEach((x) => x.classList.toggle("active", x.dataset.tab === tabId));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${tabId}`));
  if (tabId === "regime") renderChart();
  if (tabId === "traps") window.SpotTrapsModule?.render(STATE);
  if (tabId === "srmap") window.SrMapModule?.render(STATE);
  window.scrollTo(0, 0);
}

const SPOT_SHIELD_AI_PROMPT_TEMPLATE = `### ROLE & OBJECTIVE
Act as a Systematic Quantitative Spot Portfolio Manager auditing telemetry from **Project F · Spot Shield (80/20 Dual-Sleeve BTCUSDT)**.
STRICT GUARDRAIL: This is a **strictly causal, closed-bar, unleveraged Spot-Only (BTC <-> USDT)** system using Binance OHLCV candles exclusively (zero leverage, zero shorting, separate capital bucket from DIBSE). Pre-computed posture/action verdict labels are stripped — derive your assessment strictly from raw indicators and conditions, and note that \`insufficient data\` is a valid conclusion.

Provide a crisp 5-part review strictly from the JSON payload:
1. **Freshness & Null Audit:** Check \`updated_at_utc\` age (flag stale if \`> 65m\`) and list every \`null\` / \`unavailable\` field and what it prevents concluding.
2. **Portfolio Allocation & Bear Shield Audit:** Verify from raw \`sleeve1.indicators\` and \`sleeve2.indicators\` whether \`120D EMA\` macro shield is open or holding USDT, and audit \`target_btc_pct\` / \`target_usdt_pct\`.
3. **Sleeve #1 (80% · 4H Rolling VWAP Shield):** Audit distance to \`macro_120d_ema\` and \`upper_band\` (\`RVWAP90 + 0.5×ATR14\`), \`vwap_slope_12\`, and how much rallies must clear before entry criteria align.
4. **Sleeve #2 (20% · 1D TTM Squeeze Experimental):** Audit \`squeeze_on\`, \`squeeze_streak_days\`, \`bb_kc_width_ratio\`, \`mom_ols\` vs \`prev_mom_ols\`, and distance to \`kc_mid_ema20\` / \`sma_21_exit\`.
5. **Discipline & Falsification Condition:** Note \`days_in_state\`, next Quarterly Rebalance date, realistic stats (\`~27% WR\` / up to 9 consecutive losses on Sleeve #1; \`18-trade\` cap on Sleeve #2), and state the exact price/close condition that falsifies the current regime.

### LIVE SPOT SHIELD (80/20) TELEMETRY (JSON)
\`\`\`json
{{SHIELD_JSON_PAYLOAD}}
\`\`\``;

const NEWS_MACRO_AI_PROMPT_TEMPLATE = `### ROLE & OBJECTIVE
Act as an Institutional Cross-Asset Macro & Bitcoin Catalyst Strategist auditing the live **News & Macro Packet**.
STRICT GUARDRAIL: Separate hard macro/flow catalysts from media noise using ONLY the telemetry provided below. Never invent prices, economic prints, or headlines. Audit and independently verify any summary status labels (\`macro_bias.status\`, driver tones) directly from raw \`cross_asset\` and \`crypto_pulse\` values — explicitly state where you disagree, and conclude \`insufficient data\` if feeds are stale or sparse.

Deliver a concise 6-part briefing:
1. **Freshness & Null Audit:** Check \`updated_at_utc\` age (warn if \`> 65m\`) and list any \`null\` / missing fields and what they prevent concluding.
2. **Macro Risk Backdrop (\`cross_asset\` vs \`macro_bias\`):** Independently assess \`DXY\`, \`US10Y\`, \`VIX\`, \`SPX\`, and \`NDX\` 1D/ROC10 moves and state whether you agree or disagree with \`macro_bias.status\`.
3. **Event Risk & Blackout Audit (\`calendar_usd\`):** Highlight the next HIGH-impact USD release (forecast vs. previous, countdown), whether \`blackout_active\` is triggered, and expected volatility timing.
4. **Crypto Capital Flows (\`crypto_pulse\`):** Audit CMC Global Metrics (\`btc_dominance_pct\`, \`total_market_cap_24h_pct\`), CMC Fear & Greed, Altcoin Season Index, CMC/Farside BTC & ETH Spot ETF flows, \`etf_flow_regime\`, 7D stablecoin liquidity, and Deribit DVOL.
5. **Headline Catalyst Synthesis (\`headlines\`):** Group the top price-moving catalysts (ETF flows, Fed/rates, derivatives liquidations, regulation) and flag conflicting narratives.
6. **Tactical Desk Takeaway & Falsification (<= 90 words):** Summarize whether macro catalysts argue for continuation, mean-reversion, waiting through USD releases, or \`insufficient data\`, and state what macro print or cross-asset break would falsify your view.

### LIVE NEWS & MACRO TELEMETRY (JSON)
\`\`\`json
{{NEWS_JSON_PAYLOAD}}
\`\`\``;

const CORTEX_RHYME_AI_PROMPT_TEMPLATE = `### ROLE & OBJECTIVE
Act as an Empirical Quantitative Microstructure Statistician auditing telemetry from **S2 CORTEX-RHYME v1.2.0 (MOD 63)**.
STRICT GUARDRAIL: Publish ONLY observational historical conditioning statistics and tail-risk interpretation. **NEVER issue a trade directive, leverage size, or entry permission.** Conclude \`insufficient data\` or \`pure noise\` when statistical separation fails.

Evaluate the state-space payload strictly using these rules:
1. **Freshness, Nulls & Sample Quality Gate:** Check \`meta.as_of_utc\` age (warn if \`> 65m\`), list any \`null\`/\`UNKNOWN\` fields, verify \`diagnostics.sample_quality\` (\`solid\` / \`moderate\` / \`thin\`), \`diagnostics.analogues_found\`, \`diagnostics.total_archive_bars\`, \`diagnostics.history_days\`, \`diagnostics.avg_vector_distance\`, and \`diagnostics.fallback_triggered\`. If \`thin\` or \`UNKNOWN\` regime, lead with a clear warning.
2. **Baseline-Adjusted Horizons (+4h, +24h, +72h):** Compare \`after_similar_setups\` (\`median_pct\`, \`up_share\`) side-by-side against \`baseline_all_hours\` via \`edge_vs_baseline\` (\`up_share_lift_pts\`, \`lift_se_pts\`, \`lift_z_score\`, \`median_lift_pct\`). Explicitly note if outcomes differ materially from random hours (\`|lift_z_score| >= 2.0\`) or look like sampling noise.
3. **Payoff & Tail Asymmetry:** Contrast \`median_up_pct\` vs. \`median_down_pct\` and \`tail_skew_ratio\` to flag upside or downside fat-tail cliffs.
4. **200D SMA Regime Context & Falsification:** Interpret \`current_state.raw_metrics\`, \`z_vector\`, \`patient_money_h\` (including \`carry_apr_pct\`), whether \`current_state.regime_context.trend_regime\` aligns with the archive, and what shift would falsify any historical skew.

### LIVE CORTEX-RHYME TELEMETRY (JSON)
\`\`\`json
{{RHYME_JSON_PAYLOAD}}
\`\`\``;

const SPOT_MAGNET_AI_PROMPT_TEMPLATE = `### ROLE & OBJECTIVE
Act as an Institutional Quantitative Spot Bitcoin Strategist auditing **BTC Magnet Monitor (DIBSE Dual-Sleeve Protocol)**.
Pre-computed DIBSE conclusions (\`dibse\`, \`lsce.action_verdict\`, \`regime_diagnosis\`) are intentionally stripped so you derive your own independent state classification strictly from raw metrics (Strict **1.0x Spot-Only**: 10% USDT Sleeve + 10% BTC Sleeve, 80% Core untouched). If feeds are stale or ambiguous, state \`HOLD BOTH SLEEVES / INSUFFICIENT DATA\`.

Answer these 6 audit questions strictly from the raw JSON telemetry:
1. **Freshness & Null Audit:** Check \`updated_at_utc\` age (flag stale if \`> 65m\`) and list every \`null\` / \`unavailable\` field and what it prevents concluding.
2. **Independent Regime Derivation:** Evaluate \`metrics\` (price vs. Daily/Weekly VWAP, Spot CVD Ratio + 7D/14D slopes, Coinbase Premium bps, Funding/OI, and L2 Book Depth) — does raw evidence independently support **Loop A (\`USDT -> BTC\`)**, **Loop B (\`BTC -> USDT\`)**, or **Hold Both Sleeves**?
3. **Modelled LSCE & 10x–100x Magnet Pull:** Inspect \`lsce\` (side, sweep_depth_pct, spot_absorption on modelled shelves) and \`magnets\` / \`cmc_liquidations\` — which liquidity cluster exerts dominant pull, and is sweep absorption genuine or fragile?
4. **Futures Trap Check:** Compare Spot CVD against Perp Funding/OI/Basis — is upside Spot-Led or Fragile Leverage?
5. **DIBSE Execution Zones & Falsification:** Propose Loop A accumulation or Loop B trim zones with sizing factor (\`0.0x–1.0x\` of the 10% sleeve), plus the exact invalidation condition that falsifies your read.
6. **Quick Mobile Summary (<= 80 words):** Crisp bullet summary of your independent verdict.

### LIVE SPOT MAGNET TELEMETRY (JSON)
\`\`\`json
{{SPOT_JSON_PAYLOAD}}
\`\`\``;

const MASTER_QUANT_PROMPT_TEMPLATE = `### ROLE & OBJECTIVE
Act as an Institutional Quantitative Bitcoin Swing Strategist and Risk Officer. Below is a compact market telemetry packet from **BTC Short-Term Futures Protocol (v4.1)** with pre-computed DIBSE spot instructions stripped; some upstream diagnostic tags (e.g., \`state_of_regime\`, \`macro_bias_status\`) remain for audit comparison — treat those tags as hypotheses to audit and challenge from raw numbers, never repeat them blindly, and explicitly state everywhere you disagree.

---

### HARD PROTOCOL RISK CONSTRAINTS (NON-NEGOTIABLE)
Every trade idea you evaluate MUST strictly obey these guardrails:
1. **Evaluation Cadence & Hold Window:** Signals are evaluated on **4H candle closes** with a **maximum hold window of 24 hours** (time-stop reduction at 8h, hard exit at 12–24h if stagnant).
2. **Leverage & Capital Risk:**
   - Maximum Futures Leverage: **1:2 (2.0x Isolated)**.
   - Maximum Risk per Trade: **0.40% of Account Equity** on weekdays; **0.20% (halved)** on weekends (\`is_weekend_utc: true\`). If \`is_weekend_utc\` is \`null\`, assume conservative weekday uncertainty and flag it.
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
6. **Data Integrity, Staleness & Null Guardrail (CRITICAL):**
   - Check \`meta.updated_at_utc\` age right away; if older than **65 minutes** or \`meta.completeness_score < 0.80\`, flag degraded freshness/completeness and default to \`STAND ASIDE / INSUFFICIENT DATA\` unless live data confirms structure.
   - List every \`null\`, \`unavailable\`, or \`UNKNOWN\` telemetry field and state explicitly what it prevents you from concluding.
   - Compare \`ticker.live_spot_price\` against \`meta.price_drift_from_4h_close_atr\`. If live price drifted \`> 0.35 * ATR_4H\` in the trade direction, downgrade market execution to **\`PLACE CONDITIONAL LIMIT ORDER\`**.
7. **Timezone & Falsification Discipline:** Evaluate strictly in **UTC** and explicitly state what price/close falsifies your thesis (including \`STAND ASIDE / INSUFFICIENT DATA\`).

---

### REQUIRED 5-STEP ANALYTICAL OUTPUT FORMAT

#### 1. EXECUTIVE DIRECTIVE (3-Second Summary)
- **Verdict:** \`[STAND ASIDE — WAIT]\` | \`[INSUFFICIENT DATA]\` | \`[PLACE CONDITIONAL LIMIT ORDER]\` | \`[EXECUTE LONG/SHORT ON 4H CLOSE]\`
- **Directional Bias:** \`BULLISH\` | \`BEARISH\` | \`NEUTRAL / RANGE-BOUND\` (State 1D structural bias vs. 4H tactical state, and note any disagreement with \`state_of_regime\`).
- **Primary Rationale:** 2 concise sentences explaining *why* with concrete prices, RSI/ATR figures, and R:R math.

#### 2. 5-PILLAR TELEMETRY AUDIT
- **A. Price Structure, Kline Primitives & Volume Profile:** Analyze \`charts_ohlcv_last30\` (\`[ts, O, H, L, C, Vol]\`), EMA alignment (\`ema20_4h\`, \`ema50_4h\`, \`ema50_d\`, \`ema200_d\`), tactical **\`7D Tactical VPOC / VAH / VAL\`**, macro **\`30D VPOC / VAH / VAL\`**, Layer-1 **\`kline_patterns\`**, Layer-2 **\`cortex_11p.pattern_state_flags\`**, and nearest swing highs/lows.
- **B. Momentum, State of Regime & Volatility:** Audit \`rsi_4h\`, \`rsi_d\`, \`roc6/12/20_4h_pct\`, \`atr_4h_usd\` (\`atr_4h_percentile\`), \`dvol\`, and \`derivatives.context_overlays.market_time_l\` against \`state_of_regime\` — state where raw indicators confirm or contradict the regime label.
- **C. Multi-Venue Derivatives, CMC Liquidation Map & Microstructure:** Evaluate multi-venue \`funding_rate_pct\`, \`oi_btc\` / \`venue_oi_btc\`, **\`derivatives.cmc_liquidations\`**, **\`cortex_11p.microstructure_rulebook_3\`**, **\`derivatives.liquidation_magnets\`**, **\`derivatives.positioning_matrix_g\`**, **\`derivatives.context_overlays.patient_money_h\`**, and **\`derivatives.orderbook_1pct\`**.
- **D. Institutional Flows & Macro Context:** Evaluate 5-day ETF flows (\`etf.sum5_usd_m\`), \`derivatives.context_overlays.etf_flow_regime\`, 7d stablecoin liquidity (\`stables.chg7d_pct\`), \`dxy\`, \`vix\`, Fear & Greed (\`fng_value\`), and session liquidity (\`session_name\`).
- **E. Telemetry Integrity, Freshness & Null Inventory:** State exact age of \`meta.updated_at_utc\`, verify \`meta.completeness_score\`, list \`null\`/\`unavailable\`/\`UNKNOWN\` fields, inspect \`fetch_errors\`, and check live spot drift.

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
- **What Invalidates / Falsifies This Setup:** Exact price level or candle close that cancels or falsifies the thesis.
- **Spot Positioning Note (1.0x Unleveraged):** Concise DCA/accumulation or hedging zones derived independently from raw \`spot_magnet.metrics\` & \`magnets\`.

#### 5. MOBILE EXECUTION TL;DR (Copy-Paste Block)
*(Strictly under 100 words, raw execution parameters for quick mobile reading — no narrative)*:
\`\`\`text
[DIR] | TYPE: [Market/Limit] | ENTRY: $X | STOP: $X (X%) | T1: $X (X:1) | T2: $X | SIZE: $X / X.XXXX BTC (X.XXx) | RISK: X% | PLAN B: [Action if Stop breaks] | INVALID IF: [Condition]
\`\`\`

After issuing your structured output above, remain grounded strictly in the telemetry packet below and answer any follow-up Q&A without inventing external prices.

---

### LIVE TELEMETRY PACKET (JSON)
\`\`\`json
{{RAW_JSON_PAYLOAD}}
\`\`\``;

function topHeadlines5(fullState) {
  return (fullState?.news_macro?.headlines || []).slice(0, 5).map((h) => ({
    category: h.category,
    source: h.source,
    published_utc: h.published_utc,
    title: h.title,
  }));
}

function stripSpotMagnetVerdicts(sm) {
  if (!sm || typeof sm !== "object") return sm ?? null;
  const lsce = sm.lsce && typeof sm.lsce === "object" ? sm.lsce : null;
  const mag = sm.magnets && typeof sm.magnets === "object" ? sm.magnets : null;
  return {
    data_quality: sm.data_quality ?? null,
    metrics: sm.metrics ?? null,
    lsce: lsce
      ? {
          side: lsce.side ?? null,
          cluster_tested: lsce.cluster_tested ?? null,
          sweep_depth_pct: lsce.sweep_depth_pct ?? null,
          reclaim_level: lsce.reclaim_level ?? null,
          spot_absorption: lsce.spot_absorption ?? null,
        }
      : null,
    magnets: mag
      ? {
          immediate_imbalance_ratio: mag.immediate_imbalance_ratio ?? null,
          total_ladder_lower_vol_m: mag.total_ladder_lower_vol_m ?? null,
          total_ladder_upper_vol_m: mag.total_ladder_upper_vol_m ?? null,
          total_ladder_imbalance_ratio: mag.total_ladder_imbalance_ratio ?? null,
          magnet_factors: mag.magnet_factors ?? null,
          liquidation_ladder: mag.liquidation_ladder ?? null,
        }
      : null,
  };
}

function stripSpotShieldVerdicts(sh) {
  if (!sh || typeof sh !== "object") return sh ?? null;
  const pf = sh.portfolio && typeof sh.portfolio === "object" ? { ...sh.portfolio } : {};
  delete pf.posture_label;
  const s1 = sh.sleeve1 && typeof sh.sleeve1 === "object" ? { ...sh.sleeve1 } : null;
  if (s1) delete s1.action;
  const s2 = sh.sleeve2 && typeof sh.sleeve2 === "object" ? { ...sh.sleeve2 } : null;
  if (s2) delete s2.action;
  return { ...sh, portfolio: pf, sleeve1: s1, sleeve2: s2 };
}

function compactMatrixG(fullState) {
  const pm = fullState?.positioning_matrix_g;
  if (!pm || pm.status !== "LIVE") return null;
  return {
    regime_200d: pm.regime_200d,
    funding_8h_pct: pm.funding_8h_pct,
    funding_daily_pct: pm.funding_daily_pct,
    oi_delta_pct: pm.oi_delta_pct,
    oi_window: pm.oi_window,
    leverage_state: pm.leverage_state_label,
    n_weeks: pm.active_cell?.n ?? null,
    hit_rate_pct: pm.active_cell?.hit_rate_pct ?? null,
    median_7d_pct: pm.active_cell?.median_7d_pct ?? null,
    reading: pm.active_cell?.reading ?? null,
    summary_line: pm.summary_line,
    guardrail: pm.guardrail,
  };
}

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

  const { cmc_exact_clusters: _dupCmc, ...cleanLiqMagnets } = liqMagnets;
  const cleanSor = fullState.state_of_regime && typeof fullState.state_of_regime === "object"
    ? (() => {
        const { all_regimes: _ar, summary: _sum, ...rest } = fullState.state_of_regime;
        return rest;
      })()
    : null;

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
      liquidation_magnets: cleanLiqMagnets,
      funding_30d_percentile: vl.funding_30d_percentile ?? null,
      positioning_matrix_g: compactMatrixG(fullState),
      context_overlays: fullState.context_overlays ?? null,
    },
    macro_and_flows: {
      vix: sc.vix ?? null,
      dxy: sc.dxy ?? null,
      macro_bias_status: fullState.news_macro?.macro_bias?.status ?? null,
      fng_value: fullState.extras?.fng_value ?? null,
      fng_label: fullState.extras?.fng_label ?? null,
      etf: fullState.etf ?? null,
      stables: fullState.stables ?? null,
      macro_calendar: fullState.macro_calendar || [],
      next_macro_event: sc.next_macro_event ?? null,
      next_macro_minutes: sc.next_macro_minutes ?? null,
      top_headlines_5: topHeadlines5(fullState),
    },
    charts_ohlcv_last30: {
      schema: "[timestamp_ms, open, high, low, close, volume]",
      h4: h4All.slice(-30),
      d1: d1All.slice(-30),
    },
    state_of_regime: cleanSor,
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
    spot_magnet: stripSpotMagnetVerdicts(fullState.spot_magnet),
    cortex_rhyme_prior: fullState.cortex_rhyme ? {
      as_of_utc: fullState.cortex_rhyme.meta?.as_of_utc ?? null,
      active_lens: fullState.cortex_rhyme.meta?.active_lens ?? null,
      current_state: fullState.cortex_rhyme.current_state ?? null,
      diagnostics: fullState.cortex_rhyme.diagnostics ?? null,
      after_similar_setups: fullState.cortex_rhyme.after_similar_setups ?? null,
      baseline_all_hours: fullState.cortex_rhyme.baseline_all_hours ?? null,
      edge_vs_baseline: fullState.cortex_rhyme.edge_vs_baseline ?? null,
    } : null,
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
  $("entryHubView")?.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-open-tab]");
    if (b) activateTab(b.dataset.openTab);
  });
  $("btnBackHub")?.addEventListener("click", showHub);
  $("btnNavHub")?.addEventListener("click", showHub);
  $("tabNav").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (b) activateTab(b.dataset.tab);
  });
  document.addEventListener("keydown", (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName || "")) return;
    if (e.key === "0" || e.key === "Escape") {
      showHub();
      return;
    }
    const map = { "1": "signal", "2": "regime", "3": "spot", "4": "rhyme", "5": "news", "6": "shield", "7": "ledger", "8": "audit", "9": "traps", "m": "srmap", "M": "srmap" };
    if (map[e.key]) activateTab(map[e.key]);
  });
  if ($("btnCopyShieldAi")) {
    $("btnCopyShieldAi").onclick = () => {
      if (!STATE?.spot_shield) return;
      const cleanShield = stripSpotShieldVerdicts(STATE.spot_shield);
      let promptText = SPOT_SHIELD_AI_PROMPT_TEMPLATE.replace("{{SHIELD_JSON_PAYLOAD}}", JSON.stringify(cleanShield, null, 2));
      const meta = window.DeskI18n?.getMeta();
      if (meta && meta.code !== "en") {
        promptText = `**Response Language:** Respond strictly in ${meta.aiName} while keeping all BTC prices and JSON values exact.\n\n` + promptText;
      }
      copyTextWithFeedback(promptText, "Copied Spot Shield (80/20) AI Prompt + JSON!", "shieldActionMsg");
    };
  }
  if ($("newsCatSeg")) {
    $("newsCatSeg").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-cat]");
      if (!b) return;
      NEWS_CAT = b.dataset.cat;
      document.querySelectorAll("#newsCatSeg .tab-btn").forEach((x) => x.classList.toggle("active", x === b));
      renderNewsTab();
    });
  }
  if ($("btnCopyNewsAi")) {
    $("btnCopyNewsAi").onclick = () => {
      if (!STATE?.news_macro) return;
      const nm = STATE.news_macro;
      const packet = {
        updated_at_utc: nm.updated_at_utc,
        btc_price: activePrice(),
        macro_bias: nm.macro_bias,
        cross_asset: nm.cross_asset,
        crypto_pulse: nm.crypto_pulse,
        etf_flow_regime: STATE.context_overlays?.etf_flow_regime ?? null,
        market_time_l: STATE.context_overlays?.market_time_l ?? null,
        calendar_usd: (nm.calendar_usd || []).slice(0, 8),
        headlines: (nm.headlines || []).slice(0, 15).map((h) => ({
          category: h.category,
          source: h.source,
          published_utc: h.published_utc,
          title: h.title,
          summary: h.summary,
        })),
      };
      let promptText = NEWS_MACRO_AI_PROMPT_TEMPLATE.replace("{{NEWS_JSON_PAYLOAD}}", JSON.stringify(packet, null, 2));
      const meta = window.DeskI18n?.getMeta();
      if (meta && meta.code !== "en") {
        promptText = `**Response Language:** Respond strictly in ${meta.aiName} while keeping all macro numbers, dates, and headline facts exact.\n\n` + promptText;
      }
      copyTextWithFeedback(promptText, "Copied News & Macro AI Prompt + JSON!", "newsActionMsg");
    };
  }
  if ($("rhymeLensSeg")) {
    $("rhymeLensSeg").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-lens]");
      if (!b) return;
      RHYME_LENS = b.dataset.lens;
      document.querySelectorAll("#rhymeLensSeg .tab-btn").forEach((x) => x.classList.toggle("active", x === b));
      renderRhymeTab();
    });
  }
  if ($("rhymeCondSeg")) {
    $("rhymeCondSeg").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-cond]");
      if (!b) return;
      RHYME_COND = b.dataset.cond;
      document.querySelectorAll("#rhymeCondSeg .tab-btn").forEach((x) => x.classList.toggle("active", x === b));
      renderRhymeTab();
    });
  }
  if ($("btnCopyRhymeAi")) {
    $("btnCopyRhymeAi").onclick = () => {
      if (!STATE?.cortex_rhyme) return;
      const rhymePayload = {
        ...STATE.cortex_rhyme,
        positioning_matrix_g: compactMatrixG(STATE),
        patient_money_h: STATE.context_overlays?.patient_money_h ?? null,
      };
      let promptText = CORTEX_RHYME_AI_PROMPT_TEMPLATE.replace("{{RHYME_JSON_PAYLOAD}}", JSON.stringify(rhymePayload, null, 2));
      const meta = window.DeskI18n?.getMeta();
      if (meta && meta.code !== "en") {
        promptText = `**Response Language:** Respond strictly in ${meta.aiName} while keeping all historical numbers and JSON values exact.\n\n` + promptText;
      }
      copyTextWithFeedback(promptText, "Copied S2 CORTEX-RHYME AI Prompt + JSON!", "rhymeActionMsg");
    };
  }
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
    const msg = window.DeskI18n ? window.DeskI18n.t("raw_copied") : "Copied compact Telemetry JSON (spot/shield verdicts stripped).";
    copyTextWithFeedback(serializeTelemetryCompact(raw), msg, "auditExportMsg");
  };
  $("btnCopyAi").onclick = () => {
    const raw = buildRawTelemetryPacket(STATE);
    if (!raw) return;
    let promptText = MASTER_QUANT_PROMPT_TEMPLATE.replace("{{RAW_JSON_PAYLOAD}}", serializeTelemetryCompact(raw));
    const meta = window.DeskI18n?.getMeta();
    if (meta && meta.code !== "en") {
      promptText = `**Response Language:** Respond strictly in ${meta.aiName} while keeping all BTC prices, levels, and JSON field values exact.\n\n` + promptText;
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
        spot_magnet: stripSpotMagnetVerdicts(STATE.spot_magnet),
        cmc_liquidations: STATE.derivatives?.cmc_liquidations ?? null,
        positioning_matrix_g: compactMatrixG(STATE),
        etf_flow_regime: STATE.context_overlays?.etf_flow_regime ?? null,
        market_time_l: STATE.context_overlays?.market_time_l ?? null,
        news_macro_brief: STATE.news_macro
          ? {
              macro_bias_status: STATE.news_macro.macro_bias?.status ?? null,
              next_high_impact: STATE.news_macro.macro_bias?.next_high_impact ?? null,
              top_headlines_5: topHeadlines5(STATE),
            }
          : null,
      };
      let promptText = SPOT_MAGNET_AI_PROMPT_TEMPLATE.replace("{{SPOT_JSON_PAYLOAD}}", JSON.stringify(payload, null, 2));
      const meta = window.DeskI18n?.getMeta();
      if (meta && meta.code !== "en") {
        promptText = `**Response Language:** Respond strictly in ${meta.aiName} while keeping all BTC prices and JSON values exact.\n\n` + promptText;
      }
      copyTextWithFeedback(promptText, "Copied Spot Magnet DIBSE Prompt + JSON!", "spotActionMsg");
    };
  }
  window.onDeskLangChanged = () => {
    renderHeaderLive();
    renderEntryHub();
    if (ACTIVE_VIEW === "traps") window.SpotTrapsModule?.render(STATE);
    if (ACTIVE_VIEW === "srmap") window.SrMapModule?.render(STATE);
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

function renderAllTabsFromState() {
  if (!STATE) return;
  $("snapMeta").textContent = `v${STATE.protocol_version || "4.0"} · Updated ${STATE.updated_at_utc} · 4H Close ${STATE.last_4h_close_utc || "—"} · Source ${STATE.ticker?.source || "—"}`;
  renderHeaderLive();
  renderSignalTab();
  renderRegimeTab();
  renderSpotTab();
  renderRhymeTab();
  renderNewsTab();
  renderShieldTab();
  renderLedgerTab();
  renderAuditTab();
  window.SpotTrapsModule?.render(STATE);
  window.SrMapModule?.render(STATE);
  renderEntryHub();
}

async function refreshStateFromServer(silent = false) {
  try {
    const nextState = await fetchJson("data/state.json?t=" + Date.now(), 2);
    if (!nextState || typeof nextState !== "object") {
      throw new Error("Invalid state packet");
    }
    STATE = nextState;
    await pollLivePrice();
    const editingField = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName || "");
    if (!silent || !editingField) {
      renderAllTabsFromState();
    } else {
      $("snapMeta").textContent = `v${STATE.protocol_version || "4.0"} · Updated ${STATE.updated_at_utc} · 4H Close ${STATE.last_4h_close_utc || "—"} · Source ${STATE.ticker?.source || "—"}`;
      renderHeaderLive();
    }
    return {
      ok: true,
      updated_at_utc: STATE.updated_at_utc,
      updated_at_ms: STATE.updated_at_ms,
    };
  } catch (err) {
    if (!silent) console.warn("Manual state refresh failed:", err);
    return { ok: false, error: String(err?.message || err) };
  }
}

async function init() {
  window.DeskI18n?.init();
  bindEvents();
  const trapsLoad = window.SpotTrapsModule?.loadData
    ? window.SpotTrapsModule.loadData().catch((err) => console.warn("Spot traps bundle skipped:", err))
    : Promise.resolve();
  const [loadedState] = await Promise.all([fetchJson("data/state.json?t=" + Date.now(), 2), trapsLoad]);
  STATE = loadedState;
  window.SpotTrapsModule?.init({
    getLivePrice: activePrice,
    copyWithFeedback: copyTextWithFeedback,
    buildTelemetryPacket: (s) => buildRawTelemetryPacket(s),
  });
  window.SrMapModule?.init({
    getLivePrice: activePrice,
    copyWithFeedback: copyTextWithFeedback,
    refreshState: () => refreshStateFromServer(false),
    openTrapGuide: (trapId) => {
      activateTab("traps");
      window.SpotTrapsModule?.openReader(trapId);
    },
  });
  renderAllTabsFromState();
  showHub();
  seedCalcFromState();
  pollLivePrice();
  setInterval(pollLivePrice, 5000);
  setInterval(() => refreshStateFromServer(true), 5 * 60 * 1000);
}

init().catch((err) => {
  $("snapMeta").textContent = `Failed to load data/state.json: ${err.message}`;
});
