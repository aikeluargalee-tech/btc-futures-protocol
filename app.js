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
  $("liveFeed").textContent = LIVE.src ? `live ${LIVE.src} · ${age}s` : "snapshot price";
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
  const biasBadge = reg.bias === "LONG_ELIGIBLE" ? "up" : reg.bias === "SHORT_ELIGIBLE" ? "dn" : "warn";

  $("signalSummary").innerHTML = `
    <div class="signal-head">
      <div class="big-num ${status === "LONG" ? "up" : status === "SHORT" ? "dn" : "warn"}">${esc(status)}</div>
      <span class="badge ${stBadge}">${status === "FLAT" ? "NO QUALIFIED ENTRY" : esc(prop.entry_method || "SIGNAL ACTIVE")}</span>
    </div>
    <p class="mut" style="margin:8px 0 4px;">Dominant drivers: <b>${esc((reg.dominant_factors || []).join(" · ") || "—")}</b></p>
    <p class="mut" style="margin:0;">Open positions: <b>${(port.open_positions || []).length}</b> · Portfolio equity: <b>${usd(port.equity_usd, 2)}</b></p>
  `;

  const sc = typeof reg.score === "number" ? reg.score : 50;
  const th = reg.thresholds || { long: 65, short: 35, dd_tier1_active: false };
  $("regimeGaugeBox").innerHTML = `
    <div class="signal-head">
      <div class="big-num">${num(sc, 1)} <span class="mut">/ 100</span></div>
      <span class="badge ${biasBadge}">${esc(reg.bias || "NEUTRAL")}</span>
    </div>
    <div class="gauge-track"><div class="gauge-marker" style="left:${Math.max(0, Math.min(100, sc))}%"></div></div>
    <div class="mut" style="display:flex;justify-content:space-between;">
      <span>Short ≤ ${th.short}</span>
      <span>Neutral ${th.short + 1}–${th.long - 1}</span>
      <span>Long ≥ ${th.long}</span>
    </div>
    <p class="mut" style="margin:6px 0 0;">
      UTC Day: ${esc(reg.recalc_utc_day)} · HTF Break: ${reg.htf_structural_break ? '<b class="warn">YES</b>' : "No"}
      ${th.dd_tier1_active ? ' · <b class="dn">-8% DD Tier 1 Thresholds Active (75/25)</b>' : ""}
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
    ? `<div class="reject-box"><b class="dn">Setup Rejected (${rej.length})</b><ul>${rej.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>`
    : `<div class="mut" style="margin-top:8px;color:var(--up);">All 7 protocol qualification criteria satisfied.</div>`;

  if (prop && prop.entry_price) {
    $("proposalKv").innerHTML = kv([
      ["Proposed Direction", `${prop.direction} (${prop.role})`],
      ["Nearest HTF Level", prop.level_label ? `${prop.level_label} @ ${usd(prop.level_price, 1)}` : "—"],
      ["Proposed Entry", `${usd(prop.entry_price, 1)} (${prop.entry_method})`],
      ["Hard Stop", `${usd(prop.stop_price, 1)} (${num(prop.stop_distance_pct, 2)}% ≤ 4.0%)`],
      ["Target 1", `${usd(prop.target1_price, 1)} (${prop.target1_label})`],
      ["Raw / Funding-Adj R:R", `${num(prop.raw_rr, 2)}:1 / ${num(prop.funding_adjusted_rr, 2)}:1`],
      ["Calculated Size", `${prop.size_btc ?? "—"} BTC (${usd(prop.notional_usd, 0)})`],
      ["Effective Leverage", `${num(prop.leverage, 2)}x / 2.00x max${prop.leverage_capped ? " (CLAMPED)" : ""}`],
      ["Risk Allocation", `${num(prop.actual_risk_pct, 3)}% (${usd(prop.actual_risk_usd, 2)})`],
    ]);
  } else {
    $("proposalKv").innerHTML = kv([["Proposal", "Unavailable"]]);
  }

  const cb = port.circuit_breakers || {};
  const heatPct = Math.min(100, ((port.open_heat_pct || 0) / (port.max_heat_pct || 2)) * 100);
  const activeCBs = [
    cb.daily_halted && "DAILY -1.5% HALT",
    cb.weekly_halted && "WEEKLY -3.0% FLAT",
    cb.dd_tier1_active && "DD -8.0% THROTTLE",
    cb.dd_tier2_locked && "DD -12.0% LOCKED",
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
        ["Daily PnL / Limit", `${pct(port.daily_pnl_pct, 2)} (buffer ${num(port.daily_buffer_pct, 2)}% to -1.50%)`],
        ["Weekly PnL / Limit", `${pct(port.weekly_pnl_pct, 2)} (buffer ${num(port.weekly_buffer_pct, 2)}% to -3.00%)`],
        ["HWM Drawdown", `${pct(port.drawdown_pct, 2)} (HWM ${usd(port.high_water_mark_usd, 0)})`],
        ["Dist to -8% / -12% DD", `${num(port.dd_tier1_buffer_pct, 2)}% / ${num(port.dd_tier2_buffer_pct, 2)}%`],
        ["Circuit Breakers", activeCBs.length ? activeCBs.join(", ") : "CLEAR"],
      ])}
    </dl>
  `;
}

function renderRegimeTab() {
  const groups = STATE.regime?.groups || {};
  const meta = [
    ["trend_structure", "1. Trend Structure (30%)"],
    ["momentum_breadth", "2. Momentum & Breadth (25%)"],
    ["volatility_liquidity", "3. Volatility & Liquidity (25%)"],
    ["macro_external", "4. Macro / External Context (20%)"],
  ];

  $("factorCards").innerHTML = meta
    .map(([k, title]) => {
      const g = groups[k];
      if (!g) return `<div class="card"><h2>${esc(title)}</h2><p class="mut">Unavailable</p></div>`;
      const comps = Object.entries(g.components || {}).map(([ck, cv]) => [ck.replace(/_/g, " "), `${cv}/100`]);
      const extraRows = [];
      if (k === "trend_structure") {
        extraRows.push(["1D / 4H Structure", `${g.daily_structure} / ${g.h4_structure}`]);
        extraRows.push(["EMA50 / EMA200 (1D)", `${usd(g.ema50_d, 0)} / ${usd(g.ema200_d, 0)}`]);
      } else if (k === "momentum_breadth") {
        extraRows.push(["RSI(14) 1D / 4H", `${g.rsi_d ?? "—"} / ${g.rsi_4h ?? "—"}`]);
        extraRows.push(["ROC 10D / 20D", `${pct(g.roc10_d_pct, 1)} / ${pct(g.roc20_d_pct, 1)}`]);
        extraRows.push(["RS vs SPX / ETH (10D)", `${pct(g.btc_vs_spx_10d_pct, 1)} / ${pct(g.btc_vs_eth_10d_pct, 1)}`]);
      } else if (k === "volatility_liquidity") {
        extraRows.push(["Quality Score (raw)", `${g.quality_score ?? g.score}/100`]);
        extraRows.push(["RV20 / RV60 Pctile", `${g.rv20_percentile ?? "—"}% / ${g.rv60_percentile ?? "—"}%`]);
        extraRows.push(["ATR(14) 1D", `${usd(g.atr14_d_usd, 0)} (${g.atr14_d_pct ?? "—"}%, ${g.atr_vs_60d_med ?? "—"}x 60d med)`]);
        extraRows.push(["Funding / 30d Pctile", `${pct(g.funding_rate_pct, 4)} (${g.funding_30d_percentile ?? "—"}%)`]);
      } else if (k === "macro_external") {
        extraRows.push(["VIX / DXY / US10Y", `${g.vix ?? "—"} / ${g.dxy ?? "—"} / ${g.us10y ?? "—"}%`]);
        extraRows.push(["ETF 5D / Stables 7D", `${g.etf_5d_usd_m != null ? "$" + g.etf_5d_usd_m + "M" : "—"} / ${pct(g.stables_7d_pct, 2)}`]);
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
          const near = Math.abs(e.minutes_away) <= 30;
          return `<div class="row"><div><div class="title">${near ? "⚠️ " : ""}${esc(e.title)}</div><div class="mut">${esc(e.time_utc)}</div></div><span class="badge ${near ? "dn" : ""}">${e.minutes_away >= 0 ? `in ${Math.round(e.minutes_away)}m` : `${Math.round(e.minutes_away)}m ago`}</span></div>`;
        })
        .join("")
    : `<p class="mut">No USD High-Impact events in upcoming window.</p>`;
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
  const levels = (STATE.signal?.structural_levels || []).filter((l) => l.price >= lo && l.price <= hi);
  let lastY = -100;
  for (const l of levels.slice().sort((a, b) => b.price - a.price)) {
    const yy = y(l.price);
    if (yy - lastY < 14) continue;
    lastY = yy;
    const col = l.kind === "resistance" ? "var(--dn)" : l.kind === "support" ? "var(--up)" : "var(--muted)";
    svg += `<line x1="${Lp}" x2="${W - Rp}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${col}" stroke-dasharray="4 4" opacity="0.5"/>`;
    svg += `<text x="${W - Rp + 6}" y="${(yy + 4).toFixed(1)}" fill="var(--muted)" font-size="11">${esc(l.label.slice(0, 14))} ${Math.round(l.price).toLocaleString()}</text>`;
  }

  // Price line
  const path = closes.map((c, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(c).toFixed(1)}`).join(" ");
  svg += `<path d="${path}" fill="none" stroke="var(--acc)" stroke-width="2.2"/>`;

  // Proposal Entry/Stop/Target lines
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
        svg += `<text x="${Lp + 4}" y="${(yy - 4).toFixed(1)}" fill="${col}" font-size="11">${lbl} ${Math.round(val).toLocaleString()}</text>`;
      }
    }
  }
  svg += `</svg>`;
  $("chartBox").innerHTML = svg;
}

function updateCalc() {
  const eq = +$("cEq").value || 0;
  const dir = $("cDir").value;
  const role = $("cRole").value;
  const entry = +$("cEntry").value || 0;
  const stop = +$("cStop").value || 0;
  const tp = +$("cTp").value || 0;
  const cfg = STATE?.config || {};
  const ddTier1 = STATE?.portfolio?.circuit_breakers?.dd_tier1_active;

  let riskPct = role === "satellite" ? 0.0025 : ddTier1 ? 0.0025 : 0.005;
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
  if (stopPct > 4.0) issues.push(`Stop ${stopPct.toFixed(2)}% > 4.00% max`);
  if (rawRR < 1.8) issues.push(`R:R ${rawRR.toFixed(2)}:1 < 1.80:1 min`);

  $("calcOutKv").innerHTML = kv([
    ["Protocol Status", issues.length ? `INVALID (${issues.join("; ")})` : "VALID SIZING"],
    ["Risk Budget", `${(riskPct * 100).toFixed(2)}% (${usd(targetRiskUsd, 2)} target)`],
    ["Position Size", `${sizeBtc.toFixed(6)} BTC (${usd(notional, 2)} notional)`],
    ["Leverage", `${lev.toFixed(2)}x / 2.00x max${clamped ? " (2x LEVERAGE CLAMPED)" : ""}`],
    ["Actual Risk", `${actualRiskPct.toFixed(3)}% (${usd(actualRiskUsd, 2)})`],
    ["Stop Distance / R:R", `${stopPct.toFixed(2)}% / ${rawRR.toFixed(2)}:1`],
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
          <div class="title">${esc(p.id)} · <span class="${p.direction === "LONG" ? "up" : "dn"}">${esc(p.direction)}</span> (${esc(p.role)})</div>
          <div class="mut">Entry ${usd(p.entry_price, 1)} · Stop ${usd(p.stop_price, 1)} · TP1 ${usd(p.target1_price, 1)} · Size ${p.size_btc} BTC (${num(p.leverage, 2)}x)</div>
          <div class="mut">Regime@${p.regime_score_at_entry} · BE moved: ${p.be_moved ? "Yes" : "No"} · Scale-out: ${p.scale_out_done ? "Yes" : "No"}</div>
        </div>
        <div style="text-align:right;">
          <div class="${p.unrealized_pnl_usd >= 0 ? "up" : "dn"}" style="font-weight:700;">${usd(p.unrealized_pnl_usd, 2)} (${num(p.unrealized_r, 2)}R)</div>
          <div class="mut">Risk ${num(p.risk_pct, 3)}%</div>
        </div>
      </div>`
        )
        .join("")
    : `<p class="mut">No open paper positions (Flat).</p>`;

  const rev = port.review || {};
  $("reviewKv").innerHTML = kv([
    ["Completed Trades", `${rev.total_trades ?? 0} (min ${rev.min_sample_for_weight_adjustment ?? 30} to tune weights)`],
    ["Win Rate", rev.win_rate_pct != null ? `${rev.win_rate_pct}% (${rev.wins}W / ${rev.losses}L)` : "n/a (0 trades)"],
    ["Average R-Multiple", rev.avg_r != null ? `${rev.avg_r}R` : "n/a"],
    ["Largest Win / Loss", rev.largest_winner_r != null ? `${rev.largest_winner_r}R / ${rev.largest_loser_r}R` : "n/a"],
    ["Net Realized PnL", usd(rev.net_pnl_usd, 2)],
    ["Weight Adjustment Gate", rev.weight_adjustment_unlocked ? "UNLOCKED (≥ 30 trades)" : `LOCKED (${rev.total_trades ?? 0}/30)`],
  ]);

  const drv = STATE.derivatives || {};
  const ext = STATE.extras || {};
  $("derivKv").innerHTML = kv([
    ["Perp Funding (8h)", pct(drv.current_rate_pct, 5)],
    ["Open Interest (OKX)", drv.oi_btc != null ? `${Math.round(drv.oi_btc).toLocaleString()} BTC` : "—"],
    ["Deribit DVOL", ext.dvol ?? "—"],
    ["Fear & Greed", ext.fng_value != null ? `${ext.fng_value} (${ext.fng_label})` : "—"],
    ["ETF Latest / 5D", STATE.etf ? `${STATE.etf.latest_usd_m}M (${STATE.etf.latest_date}) / ${STATE.etf.sum5_usd_m}M` : "—"],
    ["USDT+USDC 7D", STATE.stables ? `${STATE.stables.total_usd_b}B (${pct(STATE.stables.chg7d_pct, 2)})` : "—"],
  ]);

  const closed = port.closed_trades || [];
  $("closedTradesBox").innerHTML = closed.length
    ? `<table><thead><tr><th>ID</th><th>Dir</th><th>Entry</th><th>Exit</th><th>R</th><th>PnL</th><th>Reason</th></tr></thead><tbody>${closed
        .slice()
        .reverse()
        .map(
          (t) =>
            `<tr><td>${esc(t.id)}</td><td class="${t.direction === "LONG" ? "up" : "dn"}">${esc(t.direction)}</td><td>${usd(t.entry_price, 1)}</td><td>${usd(t.exit_price, 1)}</td><td class="${t.r_multiple >= 0 ? "up" : "dn"}">${num(t.r_multiple, 2)}R</td><td class="${t.pnl_usd >= 0 ? "up" : "dn"}">${usd(t.pnl_usd, 2)}</td><td>${esc(t.exit_reason)}</td></tr>`
        )
        .join("")}</tbody></table>`
    : `<p class="mut">No closed paper trades yet. Trades are logged automatically when signals qualify and resolve.</p>`;
}

function renderAuditTab() {
  const logs = STATE.audit_log_recent || [];
  $("auditLogBox").innerHTML = logs.length
    ? `<table><thead><tr><th>UTC Time</th><th>Trade</th><th>Event</th><th>Details</th></tr></thead><tbody>${logs
        .map(
          (e) =>
            `<tr><td>${esc(e.ts_utc)}</td><td>${esc(e.trade_id || "SYSTEM")}</td><td><b>${esc(e.event)}</b></td><td class="mut">${esc(JSON.stringify(e))}</td></tr>`
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
  }
  updateCalc();
}

function bindEvents() {
  $("tabNav").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (!b) return;
    document.querySelectorAll("#tabNav .tab-btn").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${b.dataset.tab}`));
  });
  $("chartSeg").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tf]");
    if (!b) return;
    CHART_TF = b.dataset.tf;
    document.querySelectorAll("#chartSeg .tab-btn").forEach((x) => x.classList.toggle("active", x === b));
    renderChart();
  });
  ["cEq", "cDir", "cRole", "cEntry", "cStop", "cTp"].forEach((id) => $(id).addEventListener("input", updateCalc));
  $("btnDlJson").onclick = () => {
    const u = URL.createObjectURL(new Blob([JSON.stringify(STATE, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = u;
    a.download = `btc-protocol-state-${Date.now()}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(u), 2000);
  };
}

async function init() {
  bindEvents();
  STATE = await fetchJson("data/state.json?t=" + Date.now());
  $("snapMeta").textContent = `Updated ${STATE.updated_at_utc} · Source ${STATE.ticker?.source || "—"} · Refreshed every 15m by GitHub Actions`;
  renderHeaderLive();
  renderSignalTab();
  renderRegimeTab();
  renderLedgerTab();
  renderAuditTab();
  seedCalcFromState();
  pollLivePrice();
  setInterval(pollLivePrice, 5000);
}

init().catch((err) => {
  $("snapMeta").textContent = `Failed to load data/state.json: ${err.message}`;
});
