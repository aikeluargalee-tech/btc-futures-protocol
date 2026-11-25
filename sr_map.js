"use strict";

(function () {
  let LAST_STATE = null;
  let INIT_OPTS = {};
  let INTRADAY_OPEN = false;
  let INTRADAY_LOADING = false;
  let INTRADAY_DATA = null; // { source, fetchedUtc, error, timeframes: { "12H", "30m", "15m" } }

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
      fullPair: `${fmtD(u)} ${fmtT(u)} UTC / ${fmtT(s)} SGT`,
    };
  }

  function fmtUtcSgt(isoUtc, addMinutes = 0) {
    if (!isoUtc) return { utc: "MISSING", sgt: "MISSING", shortPair: "MISSING", fullPair: "MISSING" };
    const ms = Date.parse(isoUtc);
    if (!isFinite(ms)) return { utc: String(isoUtc), sgt: "MISSING", shortPair: String(isoUtc), fullPair: String(isoUtc) };
    return _toUtcSgtParts(ms + addMinutes * 60 * 1000);
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

  function extractTrendAndFlow(state) {
    const valOrMissing = (v) => (v === null || v === undefined || v === "" ? "MISSING" : v);
    const ts = state?.regime?.groups?.trend_structure || {};
    const sor = state?.state_of_regime || {};
    const smM = state?.spot_magnet?.metrics || {};
    const ov = state?.context_overlays || {};
    const etfReg = ov.etf_flow_regime || {};
    const etf = state?.etf || {};

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

    return {
      trendCue,
      driverCue,
      trend: {
        regime_code: valOrMissing(sor.code),
        regime_name: valOrMissing(sor.name),
        regime_bias: valOrMissing(sor.bias),
        regime_4h_score: valOrMissing(score),
        daily_bias: valOrMissing(dBias),
        daily_structure: valOrMissing(d1Struct),
        h4_structure: valOrMissing(h4Struct),
        summary: valOrMissing(ts.summary),
      },
      flow: {
        etf_latest_settled_date: valOrMissing(etf.latest_date),
        etf_1d_usd_m: valOrMissing(etf.latest_usd_m),
        etf_5d_usd_m: valOrMissing(etf5d),
        etf_flow_regime: valOrMissing(etfReg.regime),
        spot_cvd_ratio: valOrMissing(spotCvd),
        spot_cvd_slope_7d: valOrMissing(smM.spot_cvd_slope_7d),
        perp_cvd_slope_24h: valOrMissing(smM.perp_cvd_slope_24h),
        perp_cvd_trend: valOrMissing(smM.perp_cvd_trend),
        spot_vol_ratio_vs_ma20: valOrMissing(smM.spot_vol_ratio),
        oi_change_4h_pct: valOrMissing(smM.oi_change_4h_pct),
        oi_change_24h_pct: valOrMissing(oi24),
        oi_change_3d_pct: valOrMissing(smM.oi_change_3d_pct),
        funding_rate_8h_pct: valOrMissing(smM.funding_rate_8h_pct ?? state?.derivatives?.current_rate_pct),
        funding_rate_annualized_pct: valOrMissing(smM.funding_rate_annualized_pct),
      },
    };
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

  function calcAtr14Client(bars) {
    if (!Array.isArray(bars) || bars.length < 2) return null;
    const trs = [];
    for (let i = 1; i < bars.length; i += 1) {
      const cur = bars[i];
      const prevClose = bars[i - 1].close;
      const tr = Math.max(
        cur.high - cur.low,
        Math.abs(cur.high - prevClose),
        Math.abs(cur.low - prevClose)
      );
      trs.push(tr);
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
    const pad = Math.max(refPrice * 0.001, Math.min(refPrice * 0.012, 0.2 * atr14));
    const clusterTol = Math.max(0.75 * atr14, refPrice * 0.0035);
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
      const grp = groups[groups.length - 1];
      const mean = grp.reduce((s, p) => s + p.price, 0) / grp.length;
      if (Math.abs(points[i].price - mean) <= clusterTol) grp.push(points[i]);
      else groups.push([points[i]]);
    }

    const res = [];
    const sup = [];
    for (const grp of groups) {
      const loRaw = Math.min(...grp.map((p) => p.price));
      const hiRaw = Math.max(...grp.map((p) => p.price));
      const mid = +(grp.reduce((s, p) => s + p.price, 0) / grp.length).toFixed(1);
      const lowB = +(Math.min(loRaw, mid) - pad * 0.5).toFixed(1);
      const highB = +(Math.max(hiRaw, mid) + pad * 0.5).toFixed(1);
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

      // Start with multi-timeframe confluence zones
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
        // Mark raw zones covered by this confluence so staircase avoids double-listing identical price
        for (const tfKey of sr.core_order || ["1W", "1D", "4H", "1H"]) {
          const zs = sr.timeframes?.[tfKey]?.[side] || [];
          for (const z of zs) {
            if (z.mid >= c.low && z.mid <= c.high) {
              usedZones.add(`${tfKey}|${z.mid}`);
            }
          }
        }
      }

      // Add remaining individual TF zones
      for (const tfKey of sr.core_order || ["1W", "1D", "4H", "1H"]) {
        const zs = sr.timeframes?.[tfKey]?.[side] || [];
        for (const z of zs) {
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
        // Nearest 4 above refPrice, ordered highest-to-lowest down toward live spot
        return rows
          .filter((r) => !refPrice || r.mid >= refPrice || r.inZone)
          .sort((a, b) => a.mid - b.mid)
          .slice(0, 4)
          .sort((a, b) => b.mid - a.mid);
      }
      // Nearest 4 below refPrice, ordered highest-to-lowest away from live spot
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
    const rowCls = isRes ? "ceil" : "floor";
    return `
      <div class="srmap-stair-row ${rowCls} ${r.isConfluence ? "conf" : ""} ${r.inZone ? "in-zone" : ""}">
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
              <div class="mut">Estimated leverage buckets anchored to recent swing pivots · Labelled MODELED (never added to CMC Exact)</div>
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

  function buildAiPrompt(state, refPrice) {
    const meta = window.DeskI18n?.getMeta();
    const prefix =
      meta && meta.code !== "en"
        ? `**Response Language:** Respond strictly in ${meta.aiName} while keeping all BTC prices, levels, and JSON values exact.\n\n`
        : "";

    const sr = state?.sr_bands || null;
    const cmc = state?.derivatives?.cmc_liquidations || null;
    const ladder = state?.spot_magnet?.magnets?.liquidation_ladder || [];
    const wick24 = get24hWickRange(state);
    const tfCtx = extractTrendAndFlow(state);
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
      scope: "1.0x Spot Only (zero leverage, zero futures, zero shorting) · 1H-4H short-term timing layer only",
      updated_at_utc: tsPair.utc,
      updated_at_sgt: tsPair.sgt,
      stale_after_utc: stalePair.utc,
      stale_after_sgt: stalePair.sgt,
      live_spot_price: refPrice,
      wick_range_24h: wick24,
      trend_filter: tfCtx.trend,
      flow_filter: tfCtx.flow,
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
      market_time_l: state?.context_overlays?.market_time_l ?? "MISSING",
    };

    return (
      prefix +
      `### ROLE & OBJECTIVE
Act as a 1.0x Spot Bitcoin Market-Structure & Timing Analyst. Strictly 1.0x Spot Only (zero leverage, zero futures, zero shorting). Use S/R Bands + Liquidation Magnets as a **1H–4H timing and trap-avoidance layer**, NOT as a standalone direction predictor or long-term valuation tool.

STRICT AUDIT & OUTPUT RULES:
1. **Timestamps (\`UTC\` + \`SGT\` ONLY):** Report packet time and stale cutoff (\`+65m\`) strictly in **UTC and SGT (UTC+8)** using \`updated_at_utc\` / \`updated_at_sgt\` and \`stale_after_utc\` / \`stale_after_sgt\`. Mark stale if >65m old.
2. **Never Invent Missing Feeds:** Inspect \`trend_filter\` and \`flow_filter\`; report any field marked \`"MISSING"\` explicitly without guessing.
3. **Never Mix Liquidations:** Keep **CMC Exact Hyperliquid** and **Modeled F3 Ladder** strictly separate. State clearly that magnets represent leverage fuel (not a guaranteed must-visit) and modeled pools are mathematical estimates, not confirmed resting positions.
4. **Deliver a Structured 5-Part Review:**
   - **1. Freshness (\`UTC + SGT\`), Scope & Missing Inventory:** Note short-term 1H–4H timing scope explicitly.
   - **2. Trend & Flow Filter ("Who Is Driving?"):** Assess \`trend_filter\` (HH/HL vs LH/LL, Range vs Trend) and \`flow_filter\` (Spot CVD vs Perp CVD trend, Vol Ratio, OI Δ%, Funding, ETF flows). State whether Spot is supporting floors or Futures leverage is driving.
   - **3. Key S/R Ceilings, Floors & Confluence (\`1W / 1D / 4H / 1H\`)**
   - **4. Dual Magnets (\`FRESH\` vs \`TESTED_24H\`), OI/Vol Context & Traps (\`#05\` / \`#01\`):** Note which pools are \`FRESH\` vs \`TESTED_24H\`.
   - **5. 1.0x Spot Risk Filter ("If-Then"):** State (a) the exact completed **4H/1D close** that invalidates the floor/thesis, (b) the next floor below & next ceiling above if a sweep extends, and (c) the exact **reclaim close** required before acting. Zero automatic entry or leverage instructions.

### LIVE 1.0X SPOT TIMING PACKET (JSON)
\`\`\`json
${JSON.stringify(payload, null, 2)}
\`\`\``
    );
  }

  function renderContextStrip(tfCtx, state) {
    const t = tfCtx.trend;
    const f = tfCtx.flow;
    const dCls = t.daily_bias === "BEAR" ? "dn" : t.daily_bias === "BULL" ? "up" : "warn";
    const etfStr = typeof f.etf_5d_usd_m === "number" ? `5D ETF ${f.etf_5d_usd_m >= 0 ? "+" : ""}$${f.etf_5d_usd_m.toFixed(1)}M` : "5D ETF MISSING";
    const oiStr = typeof f.oi_change_24h_pct === "number" ? `OI 24h ${fmtPct(f.oi_change_24h_pct)}` : "OI MISSING";
    const cvdStr = typeof f.spot_cvd_ratio === "number" ? `Spot CVD ${f.spot_cvd_ratio.toFixed(3)}` : "Spot CVD MISSING";
    const volStr = typeof f.spot_vol_ratio_vs_ma20 === "number" ? `Vol ${f.spot_vol_ratio_vs_ma20.toFixed(2)}x` : "Vol MISSING";
    const fundStr = typeof f.funding_rate_8h_pct === "number" ? `Fund ${fmtPct(f.funding_rate_8h_pct, 4)}` : "Fund MISSING";

    return `
      <div class="srmap-ctx-strip">
        <div class="srmap-ctx-box">
          <div class="srmap-ctx-kicker">1. TREND FILTER (RANGE VS TREND)</div>
          <div class="srmap-ctx-val">
            <span class="badge ${dCls}">1D ${escHtml(t.daily_structure)}</span>
            <span class="badge">4H ${escHtml(t.h4_structure)}</span>
            ${t.regime_code !== "MISSING" ? `<span class="badge">${escHtml(t.regime_code)}</span>` : ""}
          </div>
          <div class="srmap-ctx-sub">${escHtml(tfCtx.trendCue)}</div>
        </div>

        <div class="srmap-ctx-box">
          <div class="srmap-ctx-kicker">2. FLOW FILTER (WHO IS DRIVING?)</div>
          <div class="srmap-ctx-val">
            <b>${escHtml(f.etf_flow_regime)}</b> · ${escHtml(etfStr)} · ${escHtml(oiStr)}
          </div>
          <div class="srmap-ctx-sub">${escHtml(cvdStr)} · ${escHtml(volStr)} · ${escHtml(fundStr)}<br>${escHtml(tfCtx.driverCue)}</div>
        </div>

        <div class="srmap-ctx-box scope">
          <div class="srmap-ctx-kicker">3. SCOPE · 1.0X SPOT TIMING ONLY</div>
          <div class="srmap-ctx-val"><b>1H–4H Trap &amp; Timing Layer Only</b></div>
          <div class="srmap-ctx-sub">Not long-term valuation. Magnets show leverage fuel, never must-visit targets. Check 4H/1D closes first.</div>
        </div>
      </div>
    `;
  }

  function render(state) {
    LAST_STATE = state ?? LAST_STATE;
    const host = document.getElementById("srMapRoot");
    if (!host) return;
    const sr = LAST_STATE?.sr_bands;
    const refPrice = getRefPrice(LAST_STATE);

    if (!LAST_STATE || !sr) {
      host.innerHTML = `<div class="card"><p class="mut" style="margin:0;">Waiting for S/R Bands &amp; Liquidation telemetry…</p></div>`;
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
    const tfCtx = extractTrendAndFlow(LAST_STATE);
    const tsPair = fmtUtcSgt(LAST_STATE.updated_at_utc);

    host.innerHTML = `
      <div class="actions" style="margin-bottom:10px;justify-content:space-between;flex-wrap:wrap;gap:8px;">
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
          <button type="button" class="btn btn-primary" id="btnCopySrAi">[Copy Price Map AI Prompt + JSON]</button>
          <span class="mut" id="srAiMsg">Closed-bar 1W–1H S/R · Trend &amp; Flow Filters · Fresh/Tested Liquidations (1.0x Spot Timing).</span>
        </div>
        <span class="badge ${sr.status === "LIVE" ? "up" : "warn"}">${escHtml(tsPair.shortPair)} · Spot ${fmtUsd(refPrice, 1)}</span>
      </div>

      ${renderContextStrip(tfCtx, LAST_STATE)}

      <details class="card srmap-guide-card">
        <summary class="srmap-guide-summary">
          <span>30-Second Beginner Guide: How to Read S/R Bands + Liquidation Magnets</span>
          <span class="badge">TAP TO EXPAND</span>
        </summary>
        <div class="srmap-guide-body">
          <div><b>1. Ceilings Above (Resistance):</b> Zones where sellers stepped in before. Avoid chasing green candles when a strong 4H/1D ceiling sits just +1% overhead (Trap #01).</div>
          <div><b>2. Floors Below (Support) + Confluence:</b> Zones where buyers defended before. When two higher timeframes (e.g. 1W + 1D) agree, the zone is stronger.</div>
          <div><b>3. Liquidation Magnets Below Support (Trap #05):</b> If a big leveraged Long cluster sits right underneath 1H/4H support, price often wicks through that line to sweep stops before bouncing.</div>
          <div><b>4. Why 15m / 30m / 12H Is Hidden by Default:</b> Fast intraday lines break constantly during normal ~3% BTC daily swings — use higher timeframes first.</div>
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
            <h2>Unified Structural Price Staircase (1W · 1D · 4H · 1H)</h2>
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

      <div class="card">
        <div class="srmap-sec-head" style="margin-bottom:10px;">
          <div>
            <h2>Multi-Timeframe Support &amp; Resistance Bands (Core 1W / 1D / 4H / 1H)</h2>
            <div class="mut">Bands padded cleanly with 0.20 × ATR(14) around closed-candle fractal swing highs, lows &amp; S/R flips.</div>
          </div>
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

      ${renderLiquidationSection(LAST_STATE, refPrice, wick24)}
    `;
  }

  function bindEvents() {
    const host = document.getElementById("srMapRoot");
    if (!host || host.dataset.srBound === "1") return;
    host.dataset.srBound = "1";

    host.addEventListener("click", (e) => {
      if (e.target.closest("#btnToggleIntraday")) {
        INTRADAY_OPEN = !INTRADAY_OPEN;
        if (INTRADAY_OPEN && !INTRADAY_DATA && LAST_STATE) {
          fetchLiveIntradayBands(LAST_STATE);
        } else {
          render(LAST_STATE);
        }
        return;
      }

      if (e.target.closest("#btnRefreshIntraday")) {
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
        INIT_OPTS.copyWithFeedback?.(promptText, "Copied S/R Bands + Liquidation Map AI Prompt + JSON!", "srAiMsg");
      }
    });
  }

  window.SrMapModule = {
    init(opts = {}) {
      INIT_OPTS = opts;
      bindEvents();
    },
    getHubSummary(state) {
      const sr = state?.sr_bands;
      if (!sr) return "1W/1D/4H/1H S/R Bands & Dual Liquidation Clusters";
      const ovCount = (sr.magnet_overlaps || []).length;
      const ovPart = ovCount ? ` · ${ovCount} Magnet Alert${ovCount === 1 ? "" : "s"}` : "";
      return `${sr.summary_line || "1W/1D/4H/1H Map"}${ovPart}`;
    },
    render,
  };
})();
