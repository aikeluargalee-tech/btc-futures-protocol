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
      const nowStr = new Date().toISOString().slice(11, 19) + "Z";
      INTRADAY_DATA = {
        source: `Live Closed Bars @ ${nowStr} (BinanceVision)`,
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

  function renderClusterBarList(rows, maxUsdM, refPrice, side, isModeled) {
    if (!rows.length) return `<p class="mut" style="margin:6px 0 0;">No clusters reported on this side.</p>`;
    return rows
      .map((c) => {
        const usdM = c.usd_m;
        const pctWidth = maxUsdM > 0 && typeof usdM === "number" ? Math.max(6, Math.min(100, (usdM / maxUsdM) * 100)) : 8;
        const dist = liveDistPct(c.price, refPrice);
        const pull = computePullScore(usdM, dist);
        const farTag = typeof dist === "number" && Math.abs(dist) >= 6.0;
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

  function renderLiquidationSection(state, refPrice) {
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
          ${renderClusterBarList(cmcShorts, cmcMax, refPrice, "upper", false)}
          <div class="srmap-tf-sub" style="margin-top:10px;">&#9660; Lower Long Clusters (Long Liquidations Below)</div>
          ${renderClusterBarList(cmcLongs, cmcMax, refPrice, "lower", false)}
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
              <div class="mut">Estimated leverage buckets anchored to recent swing pivots · Labelled MODELED (not realized)</div>
            </div>
            <span class="badge">${typeof imb === "number" ? imb.toFixed(1) + "x Immed Skew" : "MODELED"}</span>
          </div>
          <div class="srmap-fuel-strip">
            <div><span class="mut">Upper 10x–100x Sum:</span> <b>$${fmtNum(mag.total_ladder_upper_vol_m, 1)}M</b></div>
            <div><span class="mut">Lower 10x–100x Sum:</span> <b>$${fmtNum(mag.total_ladder_lower_vol_m, 1)}M</b></div>
            <div><span class="mut">Ladder Skew:</span> <b>${typeof ladImb === "number" ? ladImb.toFixed(2) + "x" : "—"} (${escHtml(mag.dominant_magnet || "Balanced")})</b></div>
          </div>
          <div class="srmap-tf-sub" style="margin-top:8px;">&#9650; Modeled Short Tiers Above Spot</div>
          ${renderClusterBarList(modUpper, modMax, refPrice, "upper", true)}
          <div class="srmap-tf-sub" style="margin-top:10px;">&#9660; Modeled Long Tiers Below Spot</div>
          ${renderClusterBarList(modLower, modMax, refPrice, "lower", true)}
          <div class="mut" style="margin-top:8px;padding-top:6px;border-top:1px dashed var(--line);">
            Pull Score = <code>Size ($M) / max(|Dist %|, 0.15)</code>. Nearby bright pools (&lt;4%) pull harder than far pools (&ge;6%).
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
    const ladder = state?.spot_magnet?.magnets?.liquidation_ladder || null;
    const payload = {
      updated_at_utc: state?.updated_at_utc ?? null,
      live_spot_price: refPrice,
      sr_bands: sr,
      cmc_liquidations: cmc,
      f3_modeled_liquidation_ladder: ladder,
      etf_flow_regime: state?.context_overlays?.etf_flow_regime ?? null,
      market_time_l: state?.context_overlays?.market_time_l ?? null,
    };

    return (
      prefix +
      `### ROLE & OBJECTIVE
Act as an Institutional Bitcoin Market-Structure & Liquidity Analyst explaining S/R Bands & Liquidation Magnets in plain, beginner-friendly 1.0x Spot terms.

STRICT AUDIT GUARDRAILS:
1. **Freshness & Null Inventory:** Check \`updated_at_utc\` age (flag stale if \`> 65m\`) and list any missing/\`null\` feeds rather than guessing.
2. **Closed-Bar S/R vs Liquidity Distinction:** Strictly separate verified closed-candle S/R bands (\`1W / 1D / 4H / 1H\`), CMC \`Exact Hyperliquid\` liquidation clusters, and \`Modeled\` F3 ladder estimates — never treat modeled clusters as realized order flow.
3. **Overlap & Trap #05 Check:** Explicitly inspect whether a major lower liquidation cluster sits 0.2%–3.5% below the nearest \`1H\` or \`4H\` support band (wait-for-sweep risk vs clean shelf) and whether overhead short pools sit \`>= 6%\` away (Far Magnet).
4. **Actionable 4-Part Map:**
   - **Data Freshness & Overall Structure:** Are we boxed near support or pressing a resistance ceiling?
   - **Key Ceilings & Key Floors (\`1W / 1D / 4H / 1H\`):** Highlight any multi-timeframe **Confluence Zones**.
   - **Liquidation Magnet Traps Nearby:** Compare Pull Scores (` + "`$M / |Dist %|`" + `) above vs below spot and state whether Trap #05 / Trap #01 patience is needed.
   - **Falsification & "If-Then" Conditions:** Exact completed 4H/1D close that flips resistance into support or breaks current floor structure.

### LIVE S/R BANDS & LIQUIDATION TELEMETRY (JSON)
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

    host.innerHTML = `
      <div class="actions" style="margin-bottom:10px;justify-content:space-between;flex-wrap:wrap;gap:8px;">
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
          <button type="button" class="btn btn-primary" id="btnCopySrAi">[Copy Price Map AI Prompt + JSON]</button>
          <span class="mut" id="srAiMsg">Closed-bar 1W / 1D / 4H / 1H S/R Bands + Dual-Source Liquidation Magnets.</span>
        </div>
        <span class="badge ${sr.status === "LIVE" ? "up" : "warn"}">${escHtml(sr.status || "—")} · Spot ${fmtUsd(refPrice, 1)}</span>
      </div>

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
          ${staircase.ceilings.length ? staircase.ceilings.map((r) => renderStaircaseRow(r, "resistance")).join("") : `<div class="mut" style="padding:6px;">No overhead resistance zones mapped above live price.</div>`}
          <div class="srmap-live-divider">
            <span>&#9658; LIVE BTC REFERENCE PRICE</span>
            <strong>${fmtUsd(refPrice, 1)}</strong>
          </div>
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

      ${renderLiquidationSection(LAST_STATE, refPrice)}
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
