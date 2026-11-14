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
  $("derivKv").innerHTML = kv([
    ["Funding 8h (Venues)", venueStr],
    ["Open Interest (OKX / Total)", `${drv.oi_btc != null ? Math.round(drv.oi_btc).toLocaleString() + " BTC" : "—"} / ${drv.total_oi_btc != null ? Math.round(drv.total_oi_btc).toLocaleString() + " BTC" : "—"}`],
    ["Deribit DVOL", ext.dvol ?? "—"],
    ["Fear & Greed", ext.fng_value != null ? `${ext.fng_value} (${ext.fng_label})` : "—"],
    ["ETF Latest / 5D", STATE.etf ? `${STATE.etf.latest_usd_m}M (${STATE.etf.latest_date}) / ${STATE.etf.sum5_usd_m}M` : "—"],
    ["USDT+USDC 7D", STATE.stables ? `${STATE.stables.total_usd_b}B (${pct(STATE.stables.chg7d_pct, 2)})` : "—"],
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

const MASTER_QUANT_PROMPT_TEMPLATE = `### ROLE & OBJECTIVE
Act as an Institutional Quantitative Bitcoin Swing Strategist and Risk Officer. Below is a raw, unopinionated market telemetry packet from the **BTC Short-Term Futures Protocol (v4.0)**. Your job is to analyze the raw data independently from first principles (Auction Market Theory, 4H/1D price structure, Volume Profile, momentum exhaustion vs. impulse, multi-venue derivatives positioning, and institutional ETF/stablecoin flows) and issue an unbiased Long, Short, or Stand-Aside execution verdict.

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
   - When trend and momentum are aligned in a strong impulse but price is overextended, your verdict MUST be **\`STAND ASIDE / CONDITIONAL LIMIT ORDER\`** at a mean-reversion structural pullback level (e.g., 4H EMA20, prior broken S/R, or 30D Volume Profile node).

---

### REQUIRED 4-STEP ANALYTICAL OUTPUT FORMAT

#### 1. EXECUTIVE DIRECTIVE (3-Second Summary)
- **Verdict:** \`[STAND ASIDE — WAIT]\` | \`[PLACE CONDITIONAL LIMIT ORDER]\` | \`[EXECUTE LONG/SHORT ON 4H CLOSE]\`
- **Directional Bias:** \`BULLISH\` | \`BEARISH\` | \`NEUTRAL / RANGE-BOUND\` (State 1D structural bias vs. 4H tactical state).
- **Primary Rationale:** 2 concise sentences explaining *why* with concrete prices, RSI/ATR figures, and R:R math.

#### 2. 5-PILLAR TELEMETRY AUDIT
- **A. Price Structure & Volume Profile:** Analyze \`charts.h4\` and \`charts.d1\` OHLCV arrays (\`[ts, O, H, L, C, Vol]\`), EMA alignment (\`ema20_4h\`, \`ema50_4h\`, \`ema50_d\`, \`ema200_d\`), and distance to \`30D VAH / VPOC / VAL\` and nearest swing highs/lows.
- **B. Momentum & Volatility Regime:** Evaluate \`rsi_4h\`, \`rsi_d\`, \`roc6/12/20_4h_pct\`, \`atr_4h_usd\` (\`atr_4h_percentile\`), and \`dvol\`. Classify as **Compression**, **Early Expansion**, or **Late Climax / Exhaustion**.
- **C. Multi-Venue Derivatives & Microstructure:** Evaluate \`funding_rate_pct\` across OKX, Kraken Futures, Deribit, and Hyperliquid plus \`oi_btc\` / \`venue_oi_btc\`. Identify crowding or squeeze asymmetry.
- **D. Institutional Flows & Macro Context:** Evaluate 5-day ETF flows (\`etf.sum5_usd_m\`), 7d stablecoin liquidity (\`stables.chg7d_pct\`), \`dxy\`, \`vix\`, Fear & Greed (\`fng_value\`), and weekend/session liquidity (\`session_name\`).
- **E. Telemetry Integrity Check:** Flag any \`fetch_errors\` or timestamp staleness (\`updated_at_utc\` vs. \`last_4h_close_utc\`) that reduce conviction.

#### 3. FUTURES EXECUTION VERDICT (1:2 ISOLATED LONG / SHORT)
State clearly whether an immediate **4H Close Long**, **4H Close Short**, or **Flat / Wait** setup passes all v4.0 rules right now, listing which rules pass or block.

#### 4. CALCULATOR-READY EXECUTION OR CONDITIONAL TRIGGER TABLE
*(If \`STAND ASIDE\` at market, provide the exact **Conditional Limit / Alert Setup** that WOULD satisfy >= 1.6:1 R:R and <= 2.2% stop distance on a retest)*:
- **Setup Type:** \`Market on 4H Close\` OR \`Conditional Retest / Limit\`
- **Direction:** \`LONG\` | \`SHORT\`
- **Trigger / Entry Price ($):** \`$XX,XXX\` (Structural level reference)
- **Hard Invalidation Stop ($ & %):** \`$XX,XXX\` (\`X.XX%\` — must be \`<= 2.20%\`)
- **Target 1 ($ & R:R):** \`$XX,XXX\` (\`X.XX : 1\` — must be \`>= 1.60 : 1\`)
- **Target 2 ($ & R:R):** \`$XX,XXX\` (\`X.XX : 1\`)
- **Recommended Risk %:** \`0.40%\` (or \`0.20%\` if Weekend)
- **What Invalidates Waiting for This Setup:** Exact price level or candle close that cancels the plan.

After issuing your structured verdict above, remain grounded strictly in the telemetry packet below and answer any follow-up Q&A (alternative entry levels, invalidation distance, funding/slippage sensitivity, or custom equity sizing) without inventing external prices.

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

  const levels = (fullState.signal?.structural_levels || []).map((l) => {
    const diff = refPrice > 0 ? l.price - refPrice : 0;
    return {
      label: l.label,
      kind: l.kind,
      price: l.price,
      distance_pct: refPrice > 0 ? +((diff / refPrice) * 100).toFixed(2) : null,
      distance_atr: atrUsd > 0 ? +(diff / atrUsd).toFixed(2) : null,
    };
  });

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
      h4: (fullState.charts?.h4 || []).slice(-30),
      d1: (fullState.charts?.d1 || []).slice(-30),
    },
    risk_constraints_reference: {
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
    const map = { "1": "signal", "2": "regime", "3": "ledger", "4": "audit" };
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
    copyTextWithFeedback(serializeTelemetryCompact(raw), "Copied compact Raw JSON (no pre-computed verdicts).", "auditExportMsg");
  };
  $("btnCopyAi").onclick = () => {
    const raw = buildRawTelemetryPacket(STATE);
    if (!raw) return;
    const promptText = MASTER_QUANT_PROMPT_TEMPLATE.replace("{{RAW_JSON_PAYLOAD}}", serializeTelemetryCompact(raw));
    copyTextWithFeedback(promptText, "Copied! Paste into ChatGPT, Gemini, Claude, Grok, DeepSeek, or Kimi.");
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
  bindEvents();
  STATE = await fetchJson("data/state.json?t=" + Date.now());
  $("snapMeta").textContent = `v${STATE.protocol_version || "4.0"} · Updated ${STATE.updated_at_utc} · 4H Close ${STATE.last_4h_close_utc || "—"} · Source ${STATE.ticker?.source || "—"}`;
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
