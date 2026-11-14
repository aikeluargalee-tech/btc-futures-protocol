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
  const inv = sig.sell_inventory || {};
  const status = sig.status || "FLAT";
  const activeSignals = sig.active_signals || [status];

  const banner = $("signalBanner");
  banner.className = "card signal-banner " + status;
  const stBadge = status === "LONG" ? "up" : status === "SHORT" ? "dn" : inv.active ? "dn" : "warn";
  const biasBadge = reg.bias === "LONG" ? "up" : reg.bias === "SHORT" ? "dn" : "warn";

  $("signalSummary").innerHTML = `
    <div class="signal-head">
      <div class="big-num ${status === "LONG" ? "up" : status === "SHORT" ? "dn" : "warn"}">${esc(activeSignals.join(" + "))}</div>
      <span class="badge ${stBadge}">${status === "FLAT" ? (inv.active ? "INVENTORY REDUCTION" : "NO FUTURES ENTRY") : esc(prop.entry_method || "FUTURES ACTIVE")}</span>
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

  $("sellInventoryBox").innerHTML = `
    <div class="signal-head" style="margin-bottom:6px;">
      <div>
        <b class="${inv.active ? "dn" : "mut"}" style="font-size:15px;">${inv.active ? "SELL INVENTORY ACTIVE" : "HOLD SPOT INVENTORY"}</b>
        <span class="mut"> · Ref: ${esc(inv.structural_ref || "—")}</span>
      </div>
      <span class="badge ${inv.active ? "dn" : ""}">${inv.active ? `REDUCE ${num(inv.recommended_pct, 0)}% (${inv.sell_btc} BTC ≈ ${usd(inv.sell_usd, 0)})` : `Band ${esc(inv.band_pct || "15–25%")}`}</span>
    </div>
    <p class="mut" style="margin:0;">${esc(inv.reason || "—")} · Spot Inventory: <b>${num(inv.spot_inventory_btc, 2)} BTC</b> · Counts toward Futures Heat: <b>No</b> · Exempt from Futures Halts: <b>Yes</b></p>
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
    svg += `<text x="${W - Rp + 6}" y="${(yy + 4).toFixed(1)}" fill="var(--text)" font-size="11">${esc(l.label.slice(0, 14))} ${Math.round(l.price).toLocaleString()}</text>`;
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
        svg += `<text x="${Lp + 4}" y="${(yy - 4).toFixed(1)}" fill="${col}" font-size="11">${lbl} ${Math.round(val).toLocaleString()}</text>`;
      }
    }
  }
  svg += `</svg>`;
  $("chartBox").innerHTML = svg;
}

function updateCalc() {
  const eq = +$("cEq").value || 0;
  const invBtc = +$("cInv").value || 0;
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

  const sell20Btc = invBtc * 0.2;
  const sell20Usd = sell20Btc * entry;

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
    ["Sell Inventory (20% Short Opt)", `${sell20Btc.toFixed(4)} BTC (≈ ${usd(sell20Usd, 0)}) · 15–25% band`],
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
    ["Spot Inventory Tracked", `${num(port.spot_inventory_btc, 2)} BTC`],
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
    $("cInv").value = STATE?.portfolio?.spot_inventory_btc ?? 2.0;
    $("cWeekend").value = STATE?.regime?.is_weekend_utc ? "yes" : "no";
  }
  updateCalc();
}

function activateTab(tabId) {
  document.querySelectorAll("#tabNav .tab-btn").forEach((x) => x.classList.toggle("active", x.dataset.tab === tabId));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${tabId}`));
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
  ["cEq", "cInv", "cDir", "cWeekend", "cEntry", "cStop", "cTp"].forEach((id) => $(id).addEventListener("input", updateCalc));
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
