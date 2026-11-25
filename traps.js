"use strict";

(function () {
  let BUNDLE = null;
  let LAST_STATE = null;
  let INIT_OPTS = {};
  let MODE = "scanner"; // "scanner" | "library"
  let PILLAR_FILTER = "ALL"; // "ALL" | "ACTIVE" | "p1" | "p2" | "p3" | "p4" | "bonus"
  let SEARCH_QUERY = "";
  let SELECTED_ID = null; // null | "trap_01" .. "bonus_b1"
  let GUARDRAILS_OPEN = false;

  const FORM = {
    action: "BUY_SPOT", // "BUY_SPOT" | "SELL_TRIM" | "SET_STOP" | "AUDIT_CALL"
    entry: "",
    stop: "",
    target: "",
    text: "",
    flags: new Set(),
  };

  const SITUATION_CHIPS = [
    { id: "flag_chase_1h", trapId: "trap_01", label: "Chasing a fast 1H green candle" },
    { id: "flag_mid_candle", trapId: "trap_02", label: "Entering before candle closes" },
    { id: "flag_no_retest", trapId: "trap_03", label: "Buying breakout without retest" },
    { id: "flag_panic_dump", trapId: "trap_04", label: "Panic-selling on a red drop" },
    { id: "flag_above_cluster", trapId: "trap_05", label: "Buying support above lower liq band" },
    { id: "flag_short_squeeze", trapId: "trap_06", label: "Expecting big overhead squeeze" },
    { id: "flag_tight_stop", trapId: "trap_07", label: "Tight stop just under 1H low" },
    { id: "flag_order_wall", trapId: "trap_08", label: "Trusting a huge order-book wall" },
    { id: "flag_cheap_dip", trapId: "trap_15", label: "Price looks cheap — buying the dip" },
    { id: "flag_indicators", trapId: "trap_16", label: "RSI / MACD / EMA all turned green" },
    { id: "flag_weekend", trapId: "trap_13", label: "Weekend / thin-holiday move" },
    { id: "flag_chat_target", trapId: "bonus_b1", label: "Bold chart target from chat / X" },
  ];

  const ACTION_OPTIONS = [
    { id: "BUY_SPOT", label: "Buy Spot BTC" },
    { id: "SELL_TRIM", label: "Sell / Trim BTC" },
    { id: "SET_STOP", label: "Set / Move Stop" },
    { id: "AUDIT_CALL", label: "Fact-Check Chart / Call" },
  ];

  function escHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  function fmtNum(v, d = 2) {
    return typeof v === "number" && isFinite(v) ? v.toFixed(d) : "—";
  }

  function fmtUsd(v, d = 0) {
    return typeof v === "number" && isFinite(v)
      ? "$" + v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })
      : "—";
  }

  function fmtPct(v, d = 2) {
    return typeof v === "number" && isFinite(v) ? `${v >= 0 ? "+" : ""}${v.toFixed(d)}%` : "—";
  }

  function formatInlineMd(raw) {
    const tokens = [];
    let work = String(raw ?? "").replace(/`([^`]+)`/g, (_, inner) => {
      const idx = tokens.length;
      tokens.push(`<code>${escHtml(inner)}</code>`);
      return `\u0000CODE${idx}\u0000`;
    });
    work = escHtml(work);
    work = work.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label) => label);
    work = work.replace(/\*\*\*([^*\n]+?)\*\*\*/g, "<strong><em>$1</em></strong>");
    work = work.replace(/\*\*((?:(?!\*\*(?!\*)).)+?)\*\*(?!\*)/g, "<strong>$1</strong>");
    work = work.replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, "$1<em>$2</em>");
    work = work.replace(/\u0000CODE(\d+)\u0000/g, (_, i) => tokens[Number(i)] || "");
    return work;
  }

  function splitMdTableRow(line) {
    const s = line.trim();
    const inner = s.slice(1, -1);
    const cells = [];
    let buf = "";
    let inCode = false;
    for (let i = 0; i < inner.length; i += 1) {
      const ch = inner[i];
      if (ch === "\\" && inner[i + 1] === "|") {
        buf += "|";
        i += 1;
      } else if (ch === "`") {
        inCode = !inCode;
        buf += ch;
      } else if (ch === "|" && !inCode) {
        cells.push(buf.trim());
        buf = "";
      } else {
        buf += ch;
      }
    }
    cells.push(buf.trim());
    return cells;
  }

  function isSeparatorRow(cells) {
    return cells.length > 0 && cells.every((c) => /^:?-{2,}:?$/.test(c.trim()));
  }

  function renderMarkdownSafe(md) {
    const lines = String(md ?? "").replace(/\r\n/g, "\n").split("\n");
    const out = [];
    let i = 0;

    while (i < lines.length) {
      const raw = lines[i];
      const tr = raw.trim();

      if (!tr) {
        i += 1;
        continue;
      }

      if (/^---+$/.test(tr)) {
        out.push('<hr class="trap-hr">');
        i += 1;
        continue;
      }

      const hMatch = tr.match(/^(#{1,3})\s+(.+)$/);
      if (hMatch) {
        const lvl = hMatch[1].length;
        const cls = lvl === 1 ? "trap-md-h1" : lvl === 2 ? "trap-md-h2" : "trap-md-h3";
        out.push(`<h${lvl + 1} class="${cls}">${formatInlineMd(hMatch[2])}</h${lvl + 1}>`);
        i += 1;
        continue;
      }

      if (tr.startsWith(">")) {
        const bqLines = [];
        while (i < lines.length && lines[i].trim().startsWith(">")) {
          bqLines.push(lines[i].trim().replace(/^>\s?/, ""));
          i += 1;
        }
        out.push(`<blockquote class="trap-bq">${bqLines.map(formatInlineMd).join("<br>")}</blockquote>`);
        continue;
      }

      if (tr.startsWith("|") && tr.endsWith("|")) {
        const tableLines = [];
        while (i < lines.length && lines[i].trim().startsWith("|") && lines[i].trim().endsWith("|")) {
          tableLines.push(lines[i].trim());
          i += 1;
        }
        if (tableLines.length >= 2) {
          const parsedRows = tableLines.map(splitMdTableRow);
          const hasHeaderSep = parsedRows.length >= 2 && isSeparatorRow(parsedRows[1]);
          let html = '<div class="trap-table-wrap"><table class="trap-table">';
          if (hasHeaderSep) {
            html += "<thead><tr>" + parsedRows[0].map((c) => `<th>${formatInlineMd(c)}</th>`).join("") + "</tr></thead>";
            html += "<tbody>";
            for (let r = 2; r < parsedRows.length; r += 1) {
              html += "<tr>" + parsedRows[r].map((c) => `<td>${formatInlineMd(c)}</td>`).join("") + "</tr>";
            }
            html += "</tbody>";
          } else {
            html += "<tbody>";
            for (const row of parsedRows) {
              html += "<tr>" + row.map((c) => `<td>${formatInlineMd(c)}</td>`).join("") + "</tr>";
            }
            html += "</tbody>";
          }
          html += "</table></div>";
          out.push(html);
          continue;
        }
      }

      if (/^\d+\.\s+/.test(tr)) {
        out.push('<ol class="trap-ol">');
        while (i < lines.length) {
          const cur = lines[i].trim();
          const mOrd = cur.match(/^\d+\.\s+(.+)$/);
          if (mOrd) {
            const parts = [formatInlineMd(mOrd[1])];
            i += 1;
            while (i < lines.length) {
              const nxtRaw = lines[i];
              const nxt = nxtRaw.trim();
              if (!nxt || /^\d+\.\s+/.test(nxt) || /^(#{1,3})\s+/.test(nxt) || /^---+$/.test(nxt)) break;
              if (nxtRaw.startsWith("  ") || nxtRaw.startsWith("\t")) {
                if (nxt.startsWith("- ") || nxt.startsWith("* ")) {
                  parts.push(`<div class="trap-sub-bullet">&bull; ${formatInlineMd(nxt.slice(2))}</div>`);
                } else {
                  parts.push(`<div class="trap-sub-line">${formatInlineMd(nxt)}</div>`);
                }
                i += 1;
              } else {
                break;
              }
            }
            out.push(`<li>${parts.join("")}</li>`);
          } else {
            break;
          }
        }
        out.push("</ol>");
        continue;
      }

      if (tr.startsWith("- ") || tr.startsWith("* ")) {
        out.push('<ul class="trap-ul">');
        while (i < lines.length && (lines[i].trim().startsWith("- ") || lines[i].trim().startsWith("* "))) {
          out.push(`<li>${formatInlineMd(lines[i].trim().slice(2))}</li>`);
          i += 1;
        }
        out.push("</ul>");
        continue;
      }

      const paraLines = [];
      while (i < lines.length) {
        const cur = lines[i].trim();
        if (
          !cur ||
          /^---+$/.test(cur) ||
          /^(#{1,3})\s+/.test(cur) ||
          cur.startsWith(">") ||
          (cur.startsWith("|") && cur.endsWith("|")) ||
          /^\d+\.\s+/.test(cur) ||
          cur.startsWith("- ") ||
          cur.startsWith("* ")
        ) {
          break;
        }
        paraLines.push(cur);
        i += 1;
      }
      if (paraLines.length) {
        out.push(`<p>${paraLines.map(formatInlineMd).join(" ")}</p>`);
      }
    }

    return out.join("\n");
  }

  function itemById(id) {
    return (BUNDLE?.items || []).find((it) => it.id === id) || null;
  }

  function computeTrafficLight(state) {
    const etf5 = state?.etf?.sum5_usd_m;
    const etf1 = state?.etf?.latest_usd_m;
    const dBias = state?.regime?.daily_bias;
    const score = state?.regime?.score;
    const macroSt = state?.news_macro?.macro_bias?.status;

    const reasons = [];
    let color = "AMBER";
    let label = "AMBER (Selective / Defensive)";

    if ((typeof etf5 === "number" && etf5 <= -500) || (dBias === "BEAR" && typeof score === "number" && score < 45)) {
      color = "RED";
      label = "RED (Defensive USDT Priority)";
    } else if (
      typeof etf5 === "number" && etf5 >= 250 &&
      dBias === "BULL" &&
      typeof score === "number" && score >= 58 &&
      macroSt !== "RISK_OFF"
    ) {
      color = "GREEN";
      label = "GREEN (Constructive 1.0x Execution)";
    }

    if (typeof etf5 === "number") reasons.push(`5D ETF ${etf5 >= 0 ? "+" : ""}$${etf5.toFixed(1)}M (settled ${state?.etf?.latest_date || "latest"})`);
    if (typeof etf1 === "number" && etf1 < -200) reasons.push(`1D ETF $${etf1.toFixed(1)}M`);
    if (dBias) reasons.push(`1D Bias ${dBias}`);
    if (typeof score === "number") reasons.push(`4H Score ${score.toFixed(1)}/100`);

    return { color, label, summary: reasons.join(" · ") || "Telemetry pending" };
  }

  function evaluateLiveRadar(state) {
    if (!state) {
      return {
        trafficLight: { color: "AMBER", label: "AMBER (Loading)", summary: "Waiting for telemetry" },
        alertsById: {},
        activeIds: [],
        watchIds: [],
      };
    }

    const tl = computeTrafficLight(state);
    const sm = state.spot_magnet || {};
    const m = sm.metrics || {};
    const lsce = sm.lsce || {};
    const mag = sm.magnets || {};
    const ov = state.context_overlays || {};
    const mtL = ov.market_time_l || {};
    const etfReg = ov.etf_flow_regime || {};
    const etf = state.etf || {};
    const pmG = state.positioning_matrix_g || {};
    const us10y = state.news_macro?.cross_asset?.us10y?.value;
    const cal = state.macro_calendar || state.news_macro?.calendar_usd || [];
    const alertsById = {};

    const addAlert = (id, status, reason) => {
      alertsById[id] = { id, status, reason };
    };

    // #12 Basis-Trade Unwind & T+1 ETF Lag
    const basis = m.futures_basis_annualized_pct;
    const etf5 = etf.sum5_usd_m;
    const etf1 = etf.latest_usd_m;
    if ((typeof etf5 === "number" && etf5 <= -500) || (typeof basis === "number" && typeof us10y === "number" && basis < us10y)) {
      const parts = [];
      if (typeof etf5 === "number") parts.push(`5D ETF $${etf5.toFixed(1)}M (settled ${etf.latest_date || "—"})`);
      if (typeof basis === "number" && typeof us10y === "number") parts.push(`Futures Basis ${fmtPct(basis)} < US10Y ${us10y.toFixed(2)}%`);
      parts.push("Today's unprinted US ETF session remains T+1 pending");
      addAlert("trap_12", "ACTIVE", parts.join(" · "));
    } else if (typeof etf1 === "number" && etf1 < 0) {
      addAlert("trap_12", "WATCH", `Latest settled (${etf.latest_date || "—"}) ETF outflow $${etf1.toFixed(1)}M — watch T+1 lag.`);
    }

    // #15 Cheap Price & Capital Paralysis (RED regime)
    if (tl.color === "RED") {
      addAlert("trap_15", "ACTIVE", `Phase 1 is RED (${tl.summary}). Lower prices alone do not reverse outflow regimes.`);
    } else if (tl.color === "AMBER") {
      addAlert("trap_15", "WATCH", `Phase 1 is AMBER (${tl.summary}). Stage entries slowly; do not rush all tactical USDT.`);
    }

    // #05 Unswept Magnet Trap
    const lowerC = mag.nearest_lower_cluster;
    const lowerDist = lowerC?.distance_pct;
    const imb = mag.immediate_imbalance_ratio;
    const lsceObserved = lsce.status === "SWEEP_AND_RECLAIM_OBSERVED";
    if (typeof lowerDist === "number" && lowerDist <= 3.5 && (typeof imb === "number" && imb >= 1.5)) {
      if (lsceObserved && lsce.side === "LOWER") {
        addAlert(
          "trap_05",
          "WATCH",
          `Modelled lower shelf (${fmtUsd(lowerC.price_level)}) ${lowerDist.toFixed(2)}% away (${imb.toFixed(1)}x lower skew) shows recent sweep/reclaim; wait for completed 1H/4H close hold.`
        );
      } else {
        addAlert(
          "trap_05",
          "ACTIVE",
          `Modelled lower pool at ${fmtUsd(lowerC.price_level)} sits -${lowerDist.toFixed(2)}% below spot (${imb.toFixed(1)}x immediate skew) — don't front-run support.`
        );
      }
    }

    // #06 Ghost Band / Far Magnet
    const upperC = mag.nearest_upper_cluster;
    const upperDist = upperC?.distance_pct;
    if ((typeof upperDist === "number" && upperDist >= 6.0) || pmG.leverage_state === "quiet_deleveraging") {
      const reasons = [];
      if (typeof upperDist === "number" && upperDist >= 6.0) reasons.push(`Nearest upper pool +${upperDist.toFixed(2)}% away (>=6% far filter)`);
      if (pmG.leverage_state === "quiet_deleveraging") reasons.push(`Project G in Quiet Deleveraging (OI falling)`);
      addAlert("trap_06", "WATCH", `${reasons.join(" · ")} — overhead clusters alone are not immediate squeeze fuel.`);
    }

    // #07 Obvious Stop-Loss Trap
    if (mtL.stop_noise_warning === true || (typeof mtL.expected_day_range_pct === "number" && mtL.expected_day_range_pct >= 2.8)) {
      const dayRng = typeof mtL.expected_day_range_pct === "number" ? `~${mtL.expected_day_range_pct.toFixed(2)}%` : "normal";
      addAlert(
        "trap_07",
        mtL.stop_noise_warning ? "ACTIVE" : "WATCH",
        `Expected day range is ${dayRng} (${mtL.day_of_week || "session"}): tight stops under clean 1H lows sit inside routine daily noise.`
      );
    }

    // #09 Fake Deleveraging
    const chg24 = m.price_change_24h_pct;
    const oi24 = m.oi_change_24h_pct;
    if (typeof chg24 === "number" && typeof oi24 === "number" && chg24 < 0 && oi24 > 0.5) {
      addAlert(
        "trap_09",
        chg24 <= -1.5 && oi24 >= 2.0 ? "ACTIVE" : "WATCH",
        `Spot is ${fmtPct(chg24)} (24h) while BTC-unit OI rose ${fmtPct(oi24)} (${etfReg.regime || "building leverage"}) — leverage has NOT flushed out.`
      );
    }

    // #10 Baseline Funding Rate Trap
    const fund8h = m.funding_rate_8h_pct ?? state.derivatives?.current_rate_pct;
    if (typeof fund8h === "number" && Math.abs(fund8h - 0.01) <= 0.004) {
      addAlert(
        "trap_10",
        "WATCH",
        `8h funding is ${fmtPct(fund8h, 4)} — right around the neutral +0.01%/8h clamp, not an extreme long or squeeze extreme.`
      );
    }

    // #11 Hollow Rally
    const chg1h = m.price_change_1h_pct;
    if (typeof chg24 === "number" && typeof oi24 === "number" && chg24 > 1.0 && oi24 < -0.5 && tl.color === "RED") {
      addAlert(
        "trap_11",
        "ACTIVE",
        `Spot bounced ${fmtPct(chg24)} while BTC OI fell ${fmtPct(oi24)} inside a RED flow regime — looks like short-covering, not fresh spot demand.`
      );
    } else if (typeof chg1h === "number" && chg1h >= 0.7 && tl.color === "RED") {
      addAlert("trap_11", "WATCH", `Intraday bounce (${fmtPct(chg1h)} 1h) inside a RED ETF outflow backdrop — check spot volume & BTC OI.`);
    }

    // #13 Weekend / Monday Gap / Thin Liquidity
    if (mtL.is_weekend_utc || state.regime?.is_weekend_utc) {
      addAlert("trap_13", "ACTIVE", `Weekend UTC (${mtL.summary_line || "Sat/Sun"}): CME & US ETF desks are closed — thin-book moves often fade.`);
    } else if (mtL.is_monday_gap_risk || mtL.awake_state === "QUIET_THIN" || mtL.is_quiet_exec_window) {
      addAlert("trap_13", "WATCH", `Session note (${mtL.summary_line || mtL.awake_state}): verify institutional London/NY volume before trusting breakouts.`);
    }

    // #14 Macro Event Whipsaw
    const imminent = cal.find((ev) => typeof ev.minutes_away === "number" && ev.minutes_away >= -15 && ev.minutes_away <= 60);
    const upcoming = !imminent ? cal.find((ev) => typeof ev.minutes_away === "number" && ev.minutes_away > 60 && ev.minutes_away <= 360) : null;
    if (imminent) {
      addAlert("trap_14", "ACTIVE", `USD event "${imminent.title}" in ${Math.round(imminent.minutes_away)}m — wait through the first 15m whipsaw window.`);
    } else if (upcoming) {
      const hrs = (upcoming.minutes_away / 60).toFixed(1);
      addAlert("trap_14", "WATCH", `Upcoming USD release "${upcoming.title}" in ~${hrs}h — tighten event awareness.`);
    }

    // #01 Fractal Trap (approaching overhead 4H high / weekly VWAP)
    const liveP = (INIT_OPTS.getLivePrice ? INIT_OPTS.getLivePrice() : null) ?? state.ticker?.price ?? m.price;
    const res4h = m.swing_high_4h;
    const wkVwap = m.weekly_vwap;
    if (typeof liveP === "number" && liveP > 0) {
      const ceilings = [
        typeof res4h === "number" && res4h > liveP ? { name: "4H Swing High", val: res4h, dist: ((res4h - liveP) / liveP) * 100 } : null,
        typeof wkVwap === "number" && wkVwap > liveP ? { name: "Weekly VWAP", val: wkVwap, dist: ((wkVwap - liveP) / liveP) * 100 } : null,
      ].filter(Boolean);
      const nearWall = ceilings.find((c) => c.dist <= 2.2);
      if (nearWall && (tl.color === "RED" || (typeof chg1h === "number" && chg1h >= 0.6))) {
        addAlert(
          "trap_01",
          nearWall.dist <= 1.2 ? "ACTIVE" : "WATCH",
          `${nearWall.name} (${fmtUsd(nearWall.val)}) is only +${nearWall.dist.toFixed(2)}% above spot — watch R:R before chasing green bars.`
        );
      }
    }

    const activeIds = Object.values(alertsById).filter((a) => a.status === "ACTIVE").map((a) => a.id);
    const watchIds = Object.values(alertsById).filter((a) => a.status === "WATCH").map((a) => a.id);

    return { trafficLight: tl, alertsById, activeIds, watchIds };
  }

  function scanUserDecision(state, form) {
    const radar = evaluateLiveRadar(state);
    const sm = state?.spot_magnet || {};
    const m = sm.metrics || {};
    const mag = sm.magnets || {};
    const lsce = sm.lsce || {};
    const mtL = state?.context_overlays?.market_time_l || {};
    const liveP = (INIT_OPTS.getLivePrice ? INIT_OPTS.getLivePrice() : null) ?? state?.ticker?.price ?? m.price ?? null;

    const entryVal = parseFloat(form.entry);
    const stopVal = parseFloat(form.stop);
    const targetVal = parseFloat(form.target);
    const refEntry = isFinite(entryVal) && entryVal > 0 ? entryVal : (typeof liveP === "number" && liveP > 0 ? liveP : null);
    const rawText = String(form.text || "").trim();

    const hits = new Map();
    const sevRank = { HIGH: 3, WARN: 2, CHECK: 1 };

    const addHit = (trapId, severity, sourceTag, reason) => {
      const existing = hits.get(trapId);
      if (!existing) {
        hits.set(trapId, { trapId, severity, sources: [sourceTag], reasons: [reason] });
      } else {
        if (sevRank[severity] > sevRank[existing.severity]) existing.severity = severity;
        if (!existing.sources.includes(sourceTag)) existing.sources.push(sourceTag);
        if (!existing.reasons.includes(reason)) existing.reasons.push(reason);
      }
    };

    // 1. Live telemetry context matched against intended action
    if (form.action === "BUY_SPOT") {
      if (radar.alertsById.trap_15?.status === "ACTIVE") addHit("trap_15", "HIGH", "LIVE TELEMETRY", radar.alertsById.trap_15.reason);
      if (radar.alertsById.trap_12?.status === "ACTIVE") addHit("trap_12", "HIGH", "LIVE TELEMETRY", radar.alertsById.trap_12.reason);
      if (radar.alertsById.trap_05) {
        addHit("trap_05", radar.alertsById.trap_05.status === "ACTIVE" ? "HIGH" : "WARN", "LIVE TELEMETRY", radar.alertsById.trap_05.reason);
      }
      if (radar.alertsById.trap_09?.status === "ACTIVE") addHit("trap_09", "HIGH", "LIVE TELEMETRY", radar.alertsById.trap_09.reason);
      if (radar.alertsById.trap_11) {
        addHit("trap_11", radar.alertsById.trap_11.status === "ACTIVE" ? "HIGH" : "WARN", "LIVE TELEMETRY", radar.alertsById.trap_11.reason);
      }
      if (radar.alertsById.trap_13) addHit("trap_13", "WARN", "LIVE TELEMETRY", radar.alertsById.trap_13.reason);
      if (radar.alertsById.trap_14?.status === "ACTIVE") addHit("trap_14", "HIGH", "LIVE TELEMETRY", radar.alertsById.trap_14.reason);
      if (radar.alertsById.trap_01) addHit("trap_01", "WARN", "LIVE TELEMETRY", radar.alertsById.trap_01.reason);
    } else if (form.action === "SELL_TRIM") {
      if (typeof m.swing_low_4h === "number" && refEntry) {
        const distLowPct = ((refEntry - m.swing_low_4h) / refEntry) * 100;
        if (distLowPct >= -0.5 && distLowPct <= 1.8) {
          addHit(
            "trap_04",
            "WARN",
            "LIVE TELEMETRY",
            `Price is only ${distLowPct.toFixed(2)}% from 4H Swing Low (${fmtUsd(m.swing_low_4h)}). Avoid panic-selling spot into support before a completed 4H breakdown close.`
          );
        }
      }
      if (radar.alertsById.trap_14?.status === "ACTIVE") addHit("trap_14", "HIGH", "LIVE TELEMETRY", radar.alertsById.trap_14.reason);
      if (radar.alertsById.trap_05?.status === "WATCH" && lsce.status === "SWEEP_AND_RECLAIM_OBSERVED") {
        addHit("trap_04", "CHECK", "LIVE TELEMETRY", `Recent lower sweep & reclaim observed (${lsce.cluster_tested || "lower shelf"}) — confirm it isn't a spring before selling spot.`);
      }
    } else if (form.action === "SET_STOP") {
      const dayRng = mtL.expected_day_range_pct;
      addHit(
        "trap_07",
        mtL.stop_noise_warning ? "HIGH" : "WARN",
        "LIVE TELEMETRY",
        `Expected BTC day range is ${typeof dayRng === "number" ? "~" + dayRng.toFixed(2) + "%" : "elevated"} — anchor stops beyond 4H structure + ATR buffer, not tight under 1H lows.`
      );
      if (radar.alertsById.trap_05) addHit("trap_05", "WARN", "LIVE TELEMETRY", radar.alertsById.trap_05.reason);
    } else if (form.action === "AUDIT_CALL") {
      addHit("bonus_b1", "CHECK", "CHART HYGIENE", "Separate any external chart target from its regime condition and demand an explicit invalidation level.");
      if (radar.alertsById.trap_12) addHit("trap_12", "WARN", "LIVE TELEMETRY", radar.alertsById.trap_12.reason);
      if (radar.alertsById.trap_15) addHit("trap_15", "WARN", "LIVE TELEMETRY", radar.alertsById.trap_15.reason);
    }

    // 2. Checked beginner situation boxes
    for (const chip of SITUATION_CHIPS) {
      if (form.flags.has(chip.id)) {
        addHit(chip.trapId, "HIGH", "CHECKLIST FLAG", `You flagged: "${chip.label}". Review the 4-Step Defense below before placing an order.`);
      }
    }

    // 3. Quantitative price checks from Entry / Stop / Target inputs
    let mathSummary = null;
    if (refEntry) {
      const hasStop = isFinite(stopVal) && stopVal > 0 && stopVal !== refEntry;
      const hasTarget = isFinite(targetVal) && targetVal > 0 && targetVal !== refEntry;
      const stopDistPct = hasStop ? (Math.abs(refEntry - stopVal) / refEntry) * 100 : null;
      const targetDistPct = hasTarget ? ((targetVal - refEntry) / refEntry) * 100 : null;
      const rr = hasStop && hasTarget && stopDistPct > 0 ? Math.abs(targetDistPct) / stopDistPct : null;

      mathSummary = {
        entryPrice: refEntry,
        entrySource: isFinite(entryVal) && entryVal > 0 ? "Planned Entry" : "Current Spot",
        stopDistPct,
        targetDistPct,
        rr,
      };

      const dayRng = mtL.expected_day_range_pct ?? 3.0;
      if (stopDistPct !== null && stopDistPct < Math.max(1.2, dayRng * 0.45)) {
        addHit(
          "trap_07",
          "HIGH",
          "PRICE MATH",
          `Your stop distance (${stopDistPct.toFixed(2)}%) is less than half of BTC's ~${dayRng.toFixed(2)}% daily range — high probability of getting wicked out.`
        );
      }

      if (hasTarget && targetDistPct > 0 && targetDistPct >= 6.0) {
        addHit(
          "trap_06",
          "WARN",
          "PRICE MATH",
          `Target sits +${targetDistPct.toFixed(2)}% above entry (>= 6.0% Far Magnet zone) — don't rely on distant overhead liquidity alone.`
        );
      }

      if (form.action !== "SELL_TRIM") {
        const ceilings = [m.swing_high_4h, m.weekly_vwap].filter((x) => typeof x === "number" && x > refEntry);
        if (ceilings.length) {
          const nearestCeil = Math.min(...ceilings);
          const upRoom = ((nearestCeil - refEntry) / refEntry) * 100;
          if (upRoom <= 1.8) {
            addHit(
              "trap_01",
              stopDistPct !== null && upRoom / stopDistPct < 1.3 ? "HIGH" : "WARN",
              "PRICE MATH",
              `Overhead 4H/Weekly shelf (${fmtUsd(nearestCeil)}) sits only +${upRoom.toFixed(2)}% above ${fmtUsd(refEntry)} — tight upside headroom.`
            );
          }
        }
        const lc = mag.nearest_lower_cluster;
        if (lc && typeof lc.price_level === "number" && refEntry > lc.price_level) {
          const gapPct = ((refEntry - lc.price_level) / refEntry) * 100;
          if (gapPct >= 0.4 && gapPct <= 4.0 && lsce.status !== "SWEEP_AND_RECLAIM_OBSERVED") {
            addHit(
              "trap_05",
              "HIGH",
              "PRICE MATH",
              `Your entry (${fmtUsd(refEntry)}) sits ${gapPct.toFixed(2)}% above a modelled lower pool (${fmtUsd(lc.price_level)}) — wait for sweep + closed-candle reclaim.`
            );
          }
        }
      }

      if (rr !== null && rr < 1.5 && form.action === "BUY_SPOT") {
        addHit("trap_01", "WARN", "PRICE MATH", `Reward-to-Risk ratio is ${rr.toFixed(2)} : 1 — aim for asymmetric setups after sweeps/retests rather than cramped upside.`);
      }
    }

    // 4. Text / external call analyzer across all 16 traps + Bonus B1
    if (rawText) {
      const lower = rawText.toLowerCase();
      const textRules = [
        {
          id: "bonus_b1",
          re: /\$\s*\d{2,3}\s*k\b|\b(1[0-9]|2[0-9]|3[0-9])k\b|descending triangle|rising wedge|measured move|bear flag|bull flag|black monday|black friday|catching knives|guaranteed|100% crash|going to \$\d/i,
          sev: "HIGH",
          msg: "Pasted text contains a bold chart projection or dramatic price target — audit whether it is a prophecy or a conditional If-Then map.",
        },
        { id: "trap_01", re: /1h\s*(green|candle|break)|chasing|fomo|4h\s*resistance|pumping\s*fast/i, sev: "WARN", msg: "Mentions 1H velocity or chasing near resistance (#01)." },
        { id: "trap_02", re: /mid[- ]?candle|before\s*(the\s*)?close|wick|live\s*bar|hasn'?t\s*closed/i, sev: "WARN", msg: "Mentions live candle wicks / unclosed bars (#02)." },
        { id: "trap_03", re: /breakout|broke\s*out|retest|failed\s*break/i, sev: "WARN", msg: "Mentions breakout entry — verify 4H close + polarity retest & real spot volume (#03)." },
        { id: "trap_04", re: /panic|capitulat|dumping|all\s*out|sell\s*everything/i, sev: "WARN", msg: "Mentions panic-selling / crash fear — separate Core BTC from Tactical USDT (#04)." },
        { id: "trap_05", re: /heatmap|coinglass|liq(uidation)?\s*(band|cluster|pool)|unswept|support\s*touch/i, sev: "WARN", msg: "Mentions heatmap / support bounce — verify lower Pull Score wasn't left unswept (#05)." },
        { id: "trap_06", re: /short\s*squeeze|overhead\s*cluster|ghost\s*band|squeeze\s*fuel/i, sev: "WARN", msg: "Assumes overhead liquidity forces a squeeze — check stale clusters, distance >=6%, and BTC OI (#06)." },
        { id: "trap_07", re: /stop[- ]?loss|stop\s*limit|oco|swing\s*low|tight\s*stop|stopped\s*out/i, sev: "WARN", msg: "Mentions tight stops — check ATR buffer and normal daily range (#07)." },
        { id: "trap_08", re: /order\s*book|bid\s*wall|ask\s*wall|spoof|buy\s*wall|sell\s*wall/i, sev: "WARN", msg: "Cites resting order-book walls — unexecuted depth can vanish on contact (#08)." },
        { id: "trap_09", re: /deleverag|oi\s*(drop|fell|down)|clean\s*reset|leverage\s*flushed/i, sev: "WARN", msg: "Claims leverage flushed — audit BTC-unit OI, not USD notional OI (#09)." },
        { id: "trap_10", re: /funding\s*rate|0\.01%|neutral\s*funding|overheated\s*long/i, sev: "WARN", msg: "References funding — remember +0.01%/8h is venue clamp baseline, not crowding (#10)." },
        { id: "trap_11", re: /relief\s*bounce|short[- ]?cover|v[- ]?shape|hollow\s*rally/i, sev: "WARN", msg: "Mentions sharp rebound — verify whether BTC OI rose or fell during the bounce (#11)." },
        { id: "trap_12", re: /etf|ibit|fbtc|basis\s*trade|arbitrage\s*unwind|farside|t\+1|treasury/i, sev: "WARN", msg: "Mentions ETF / basis trade — real spot redemptions still weigh on books regardless of motive; mind T+1 lag (#12)." },
        { id: "trap_13", re: /weekend|saturday|sunday|holiday|cme\s*gap/i, sev: "WARN", msg: "Mentions weekend / holiday price action — apply liquidity discount until Monday confirmation (#13)." },
        { id: "trap_14", re: /\bcpi\b|\bpce\b|\bfomc\b|\bnfp\b|powell|fed\s*rate|options\s*expir|headline/i, sev: "WARN", msg: "Mentions macro event catalyst — enforce 15m post-print blackout before acting (#14)." },
        { id: "trap_15", re: /cheap|discount|buy\s*the\s*dip|btfd|dip\s*buy|bottom\s*is\s*in/i, sev: "HIGH", msg: "Uses 'cheap / buy the dip' reasoning — always gate dip-buying through Phase 1 flow status (#15)." },
        { id: "trap_16", re: /\brsi\b|\bmacd\b|ema\s*cross|golden\s*cross|oscillator|indicators?\s*(all|turn)/i, sev: "WARN", msg: "Relies on lagging oscillators — verify chart location & higher-timeframe wall first (#16)." },
      ];

      for (const r of textRules) {
        if (r.re.test(rawText)) addHit(r.id, r.sev, "TEXT SCAN", r.msg);
      }

      const mentionsPriceTarget = /(\$\s*\d{2,3}[,\d]*k?|\b\d{2,3}k\b)/i.test(rawText);
      const mentionsInvalidation = /invalidat|cancel|wrong\s*if|stop[- ]?loss|\bsl\b|close\s*(above|below)|unless/i.test(lower);
      if (mentionsPriceTarget && !mentionsInvalidation) {
        addHit(
          "bonus_b1",
          "HIGH",
          "MISSING INVALIDATION",
          "Your text includes a price level/target with NO invalidation criterion. Under B1, a target without invalidation is entertainment — define what cancels the idea first."
        );
      }
    }

    const sortedHits = Array.from(hits.values()).sort((a, b) => {
      const diff = sevRank[b.severity] - sevRank[a.severity];
      if (diff !== 0) return diff;
      const itA = itemById(a.trapId);
      const itB = itemById(b.trapId);
      return String(itA?.code || "").localeCompare(String(itB?.code || ""));
    });

    return { radar, hits: sortedHits, mathSummary, refEntry, rawText };
  }

  function buildTrapAuditAiPrompt(state, scan) {
    const meta = window.DeskI18n?.getMeta();
    const prefix =
      meta && meta.code !== "en"
        ? `**Response Language:** Respond strictly in ${meta.aiName} while keeping all BTC prices, levels, and JSON field values exact.\n\n`
        : "";

    const rawTelemetry = INIT_OPTS.buildTelemetryPacket ? INIT_OPTS.buildTelemetryPacket(state) : {};
    const checkedLabels = SITUATION_CHIPS.filter((c) => FORM.flags.has(c.id)).map((c) => `${c.trapId.toUpperCase()}: ${c.label}`);
    const userPlan = {
      intended_action: ACTION_OPTIONS.find((a) => a.id === FORM.action)?.label || FORM.action,
      planned_entry_usd: FORM.entry ? Number(FORM.entry) : null,
      planned_stop_usd: FORM.stop ? Number(FORM.stop) : null,
      planned_target_usd: FORM.target ? Number(FORM.target) : null,
      math_check: scan.mathSummary || null,
      user_situation_flags: checkedLabels,
      user_pasted_analysis_or_call: scan.rawText || null,
      local_scanner_matches: scan.hits.map((h) => ({
        trap_id: h.trapId,
        severity: h.severity,
        sources: h.sources,
        reasons: h.reasons,
      })),
    };

    const rubric17 = (BUNDLE?.items || []).map((it) => ({
      id: it.id,
      code: it.code,
      title: it.short_title,
      core_mistake: it.core_mistake,
      key_defense: it.key_defense,
    }));

    const packet = {
      user_decision_and_analysis: userPlan,
      live_market_radar: scan.radar,
      spot_trap_rubric_17: rubric17,
      live_btc_telemetry: rawTelemetry,
    };

    const promptBody = `### ROLE & OBJECTIVE
Act as an Unleveraged 1.0x Bitcoin Spot Risk Officer & Trap Auditor speaking clearly to a spot trader (mostly beginners — explain every risk in plain English, zero jargon without immediate explanation).

STRICT AUDIT GUARDRAILS:
1. **1.0x Spot-Only Discipline:** Strictly BTC <-> USDT cash & spot risk management. Zero leverage, zero margin/futures entries.
2. **Freshness & Null Inventory:** Check \`live_btc_telemetry.meta.updated_at_utc\` (warn if \`> 65m\` old) and list any \`null\` / unavailable fields and what they prevent concluding. Conclude \`insufficient data\` rather than guessing missing feeds.
3. **Challenge Summary Labels From Raw Numbers:** Treat any local tags (\`trafficLight\`, \`spot_flow_regime\`, local scanner matches) strictly as hypotheses — verify every claim directly from raw \`etf\`, \`derivatives\`, \`spot_magnet.metrics\`, \`charts_ohlcv_last30\`, and \`macro_calendar\` numbers. Explicitly state wherever raw data disagrees.
4. **Prophecy & Invalidation Test (Bonus B1):** If the user pasted a chart projection or price target, check whether it states a falsifiable **invalidation level** and **regime condition** rather than linear extrapolation.
5. **Actionable 4-Part Output:**
   - **Verdict & Data Freshness:** Is this spot decision safe to take right now, wait, or stand down?
   - **Top Active Market & Behavioral Traps Matched:** Explain which of Traps #01–#16 or B1 apply (and why, citing live prices & flows).
   - **What Must Happen Next ("If-Then" Conditions):** State exact completed 1H/4H close or ETF flow condition needed AND the exact falsification level.
   - **Beginner 3-Bullet Protection Checklist:** Simple, concrete steps to protect tactical USDT and core BTC.

### USER DECISION, 16+1 TRAP RUBRIC & LIVE TELEMETRY (JSON)
\`\`\`json
${JSON.stringify(packet, null, 2)}
\`\`\``;

    return prefix + promptBody;
  }

  function sevBadgeClass(sev) {
    if (sev === "ACTIVE" || sev === "HIGH") return "dn";
    if (sev === "WATCH" || sev === "WARN") return "warn";
    return "";
  }

  function openReader(id) {
    MODE = "library";
    SELECTED_ID = id;
    render(LAST_STATE);
    window.scrollTo(0, 0);
  }

  function renderGuardrailsDrawer() {
    if (!BUNDLE) return "";
    return `
      <div class="trap-drawer ${GUARDRAILS_OPEN ? "open" : "hidden"}">
        <div class="trap-chain-box">
          <div class="trap-kicker">MASTER CHAIN OF COMMAND (AUTHORITY FLOWS DOWNWARD)</div>
          <div class="trap-chain-text">${escHtml(BUNDLE.chain_of_command)}</div>
        </div>
        <div class="trap-guardrails-grid">
          ${(BUNDLE.guardrails || [])
            .map(
              (g) => `
            <div class="trap-guardrail-item">
              <div class="trap-g-title">[${g.num}] ${formatInlineMd(g.title)}</div>
              <div class="trap-g-body">${formatInlineMd(g.text)}</div>
            </div>`
            )
            .join("")}
        </div>
      </div>
    `;
  }

  function renderScannerMode(state, radar) {
    const scan = scanUserDecision(state, FORM);
    const activeItems = radar.activeIds.map(itemById).filter(Boolean);
    const watchItems = radar.watchIds.map(itemById).filter(Boolean);
    const radarItems = [...activeItems, ...watchItems];
    const tl = radar.trafficLight;
    const tlCls = tl.color === "RED" ? "dn" : tl.color === "GREEN" ? "up" : "warn";
    const placeholderPrice = scan.refEntry ? Math.round(scan.refEntry) : 60000;

    return `
      <div class="card trap-tl-card ${tl.color}">
        <div class="trap-tl-head">
          <div>
            <div class="trap-kicker">LIVE SPOT TRAFFIC LIGHT &amp; TODAY'S ACTIVE TRAPS</div>
            <div class="trap-tl-title">Phase 1 Environment: <span class="badge ${tlCls}">${escHtml(tl.label)}</span></div>
            <div class="mut" style="margin-top:4px;">${escHtml(tl.summary)}</div>
          </div>
          <div class="trap-tl-counts">
            <span class="badge dn">${radar.activeIds.length} ACTIVE TRAP${radar.activeIds.length === 1 ? "" : "S"}</span>
            <span class="badge warn">${radar.watchIds.length} WATCH</span>
          </div>
        </div>
        ${
          radarItems.length
            ? `<div class="trap-radar-grid">
                ${radarItems
                  .map((it) => {
                    const al = radar.alertsById[it.id];
                    const cls = al.status === "ACTIVE" ? "dn" : "warn";
                    return `
                      <button type="button" class="trap-radar-chip ${cls}" data-open-trap="${escHtml(it.id)}">
                        <div class="trap-rc-top">
                          <span class="trap-code">#${escHtml(it.code)}</span>
                          <span class="badge ${cls}">${escHtml(al.status)}</span>
                        </div>
                        <div class="trap-rc-title">${escHtml(it.short_title)}</div>
                        <div class="trap-rc-reason">${escHtml(al.reason)}</div>
                        <div class="trap-rc-link">Read defense guide &rarr;</div>
                      </button>
                    `;
                  })
                  .join("")}
              </div>`
            : `<p class="mut" style="margin:8px 0 0;">No acute live traps firing right now — still verify candle closes &amp; structure before acting.</p>`
        }
      </div>

      <div class="card">
        <div class="trap-sec-head">
          <div>
            <h2>Pre-Trade Decision &amp; Analysis Scanner ("Scan Before You Click")</h2>
            <p class="mut" style="margin:3px 0 0;">Check what you're about to do, paste any chart target or trading idea, and cross-check it instantly against all 16 Spot Traps + B1 + live BTC telemetry.</p>
          </div>
          <button type="button" class="btn btn-primary" id="btnCopyTrapAi">[Copy Trap-Audit AI Prompt + Live JSON]</button>
        </div>
        <div class="mut" id="trapAiMsg" style="margin-bottom:8px;">Works offline right here — or copy the full prompt + rubric into ChatGPT, Gemini, Claude, Grok, DeepSeek, or Kimi.</div>

        <div class="trap-scanner-form">
          <div class="trap-field-group">
            <div class="trap-kicker">1. WHAT ARE YOU CONSIDERING RIGHT NOW?</div>
            <div class="trap-action-pills" id="trapActionPills">
              ${ACTION_OPTIONS.map(
                (a) => `<button type="button" class="tab-btn ${FORM.action === a.id ? "active" : ""}" data-trap-action="${escHtml(a.id)}">${escHtml(a.label)}</button>`
              ).join("")}
            </div>
          </div>

          <div class="trap-field-group">
            <div class="trap-kicker">2. OPTIONAL NUMBERS (FOR INSTANT STOP / TARGET / MAGNET MATH CHECK)</div>
            <div class="trap-num-row">
              <label class="field"><span>Planned Entry / Check Price ($)</span><input type="number" id="trapScanEntry" step="50" placeholder="${placeholderPrice}" value="${escHtml(FORM.entry)}"></label>
              <label class="field"><span>Planned Stop / Invalidation ($)</span><input type="number" id="trapScanStop" step="50" placeholder="e.g. 58500" value="${escHtml(FORM.stop)}"></label>
              <label class="field"><span>Target Price ($)</span><input type="number" id="trapScanTarget" step="50" placeholder="e.g. 64500" value="${escHtml(FORM.target)}"></label>
            </div>
          </div>

          <div class="trap-field-group">
            <div class="trap-kicker">3. CHECK ANY SITUATION THAT MATCHES WHAT YOU SEE OR FEEL</div>
            <div class="trap-check-grid" id="trapCheckGrid">
              ${SITUATION_CHIPS.map(
                (c) => `
                <label class="trap-chk-pill ${FORM.flags.has(c.id) ? "checked" : ""}">
                  <input type="checkbox" data-trap-flag="${escHtml(c.id)}" ${FORM.flags.has(c.id) ? "checked" : ""}>
                  <span>${escHtml(c.label)}</span>
                </label>`
              ).join("")}
            </div>
          </div>

          <div class="trap-field-group">
            <div class="trap-kicker">4. PASTE YOUR ANALYSIS OR AN EXTERNAL CHART CALL / TWEET (OPTIONAL)</div>
            <textarea id="trapScanText" class="trap-textarea" rows="3" placeholder="Example: BTC looks cheap after dropping! Saw someone say descending triangle targets $19K by Friday, thinking to buy the dip with a tight stop below the 1H low...">${escHtml(FORM.text)}</textarea>
          </div>

          <div class="actions">
            <button type="button" class="btn btn-primary" id="btnRunTrapScan">[Scan My Decision Now]</button>
            <button type="button" class="btn" id="btnResetTrapScan">[Clear Inputs]</button>
          </div>
        </div>
      </div>

      <div class="card" id="trapScanResultsCard">
        ${renderScanResultsInner(scan)}
      </div>
    `;
  }

  function renderScanResultsInner(scan) {
    const ms = scan.mathSummary;
    const msParts = [];
    if (ms) {
      msParts.push(`${ms.entrySource}: ${fmtUsd(ms.entryPrice, 0)}`);
      if (ms.stopDistPct !== null) msParts.push(`Stop Dist: -${ms.stopDistPct.toFixed(2)}%`);
      if (ms.targetDistPct !== null) msParts.push(`Target: ${fmtPct(ms.targetDistPct, 2)}`);
      if (ms.rr !== null) msParts.push(`Est. R:R ${ms.rr.toFixed(2)} : 1`);
    }

    return `
      <div class="trap-sec-head" style="margin-bottom:8px;">
        <div>
          <h2>Scanner Audit Report (${scan.hits.length} Match${scan.hits.length === 1 ? "" : "es"})</h2>
          ${msParts.length ? `<div class="mut" style="margin-top:2px;"><b>${escHtml(msParts.join(" · "))}</b></div>` : ""}
        </div>
        <span class="badge ${scan.hits.some((h) => h.severity === "HIGH") ? "dn" : scan.hits.length ? "warn" : "up"}">
          ${scan.hits.some((h) => h.severity === "HIGH") ? "HIGH CAUTION ADVISED" : scan.hits.length ? "REVIEW CHECKS BELOW" : "NO OBVIOUS TRAP MATCHED"}
        </span>
      </div>
      ${
        scan.hits.length
          ? `<div class="trap-scan-results">
              ${scan.hits
                .map((h) => {
                  const it = itemById(h.trapId);
                  if (!it) return "";
                  const cls = sevBadgeClass(h.severity);
                  return `
                    <div class="trap-hit-card ${cls}">
                      <div class="trap-hit-top">
                        <div class="trap-hit-title-wrap">
                          <span class="trap-code">#${escHtml(it.code)}</span>
                          <strong>${escHtml(it.short_title)}</strong>
                        </div>
                        <div class="trap-hit-badges">
                          ${h.sources.map((s) => `<span class="badge">${escHtml(s)}</span>`).join("")}
                          <span class="badge ${cls}">${escHtml(h.severity)}</span>
                        </div>
                      </div>
                      <ul class="trap-hit-reasons">
                        ${h.reasons.map((r) => `<li>${escHtml(r)}</li>`).join("")}
                      </ul>
                      <div class="trap-hit-defense">
                        <b>10-Sec Defense:</b> ${formatInlineMd(it.key_defense)}
                      </div>
                      <div class="trap-hit-steps">
                        ${(it.quick_steps || [])
                          .map(
                            (st) => `
                            <label class="trap-step-check">
                              <input type="checkbox">
                              <span><b>${st.num}. ${formatInlineMd(st.title)}</b>${st.detail ? ` — ${formatInlineMd(st.detail)}` : ""}</span>
                            </label>`
                          )
                          .join("")}
                      </div>
                      <div class="trap-hit-actions">
                        <button type="button" class="btn" data-open-trap="${escHtml(it.id)}">[Read Full Guide #${escHtml(it.code)} &rarr;]</button>
                      </div>
                    </div>
                  `;
                })
                .join("")}
            </div>`
          : `<p class="mut" style="margin:6px 0 0;">No acute trap flags matched your current inputs — keep guardrails active and check Phase 1 traffic light before sizing.</p>`
      }
    `;
  }

  function renderLibraryCardsHtml(radar) {
    const items = (BUNDLE?.items || []).filter((it) => {
      if (PILLAR_FILTER === "ACTIVE") {
        if (!radar.alertsById[it.id]) return false;
      } else if (PILLAR_FILTER !== "ALL" && it.pillar_key !== PILLAR_FILTER) {
        return false;
      }
      if (SEARCH_QUERY.trim()) {
        const q = SEARCH_QUERY.trim().toLowerCase();
        const hay = `${it.code} ${it.title} ${it.core_mistake} ${it.key_defense} ${(it.tags || []).join(" ")}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    if (!items.length) {
      return `<div class="card"><p class="mut" style="margin:0;">No guides match your filter. Try clearing the search box or switching to ALL.</p></div>`;
    }
    return `
      <div class="trap-library-grid">
        ${items
          .map((it) => {
            const al = radar.alertsById[it.id];
            const alCls = al ? sevBadgeClass(al.status) : "";
            const pLabel = (BUNDLE?.pillars || []).find((p) => p.key === it.pillar_key)?.short_label || it.pillar;
            return `
              <button type="button" class="trap-card ${it.id === "bonus_b1" ? "bonus" : ""}" data-open-trap="${escHtml(it.id)}">
                <div class="trap-card-top">
                  <span class="trap-code">${it.id === "bonus_b1" ? "BONUS B1" : "#" + escHtml(it.code)}</span>
                  <div class="trap-card-badges">
                    <span class="badge">${escHtml(pLabel)}</span>
                    ${al ? `<span class="badge ${alCls}">${escHtml(al.status)}</span>` : ""}
                  </div>
                </div>
                <div class="trap-card-title">${escHtml(it.short_title)}</div>
                <div class="trap-card-row"><b>Mistake:</b> ${formatInlineMd(it.core_mistake)}</div>
                <div class="trap-card-row"><b>Defense:</b> ${formatInlineMd(it.key_defense)}</div>
                <div class="trap-card-foot">
                  <span>Regimes: ${(it.regime_risk || []).join(" / ")}</span>
                  <span class="trap-read-cta">Open guide &rarr;</span>
                </div>
              </button>
            `;
          })
          .join("")}
      </div>
    `;
  }

  function renderLibraryMode(radar) {
    if (SELECTED_ID) {
      return renderReaderView(SELECTED_ID, radar);
    }

    const filterBtns = [
      { key: "ALL", label: `ALL (${(BUNDLE?.items || []).length})` },
      { key: "ACTIVE", label: `ACTIVE NOW (${radar.activeIds.length + radar.watchIds.length})` },
      ...(BUNDLE?.pillars || []).map((p) => ({ key: p.key, label: `${p.short_label} (${p.count})` })),
    ];

    return `
      <div class="card">
        <div class="trap-lib-controls">
          <div class="tabs" id="trapPillarSeg" style="margin:0;">
            ${filterBtns
              .map((b) => `<button type="button" class="tab-btn ${PILLAR_FILTER === b.key ? "active" : ""}" data-trap-pillar="${escHtml(b.key)}">${escHtml(b.label)}</button>`)
              .join("")}
          </div>
          <input type="search" id="trapSearchInput" class="trap-search-input" placeholder="Search traps, ETF, RSI, heatmap, weekend..." value="${escHtml(SEARCH_QUERY)}">
        </div>
      </div>
      <div id="trapLibGridHost">${renderLibraryCardsHtml(radar)}</div>
    `;
  }

  function renderReaderView(id, radar) {
    const items = BUNDLE?.items || [];
    const idx = items.findIndex((it) => it.id === id);
    const it = idx >= 0 ? items[idx] : items[0];
    if (!it) return "";

    const prevIt = idx > 0 ? items[idx - 1] : null;
    const nextIt = idx >= 0 && idx < items.length - 1 ? items[idx + 1] : null;
    const al = radar.alertsById[it.id];

    return `
      <div class="card trap-reader">
        <div class="trap-reader-nav">
          <button type="button" class="btn" id="btnTrapBackLib">&larr; Back to Library (16+1)</button>
          <div class="actions">
            ${prevIt ? `<button type="button" class="btn" data-open-trap="${escHtml(prevIt.id)}">&lsaquo; #${escHtml(prevIt.code)}</button>` : ""}
            ${nextIt ? `<button type="button" class="btn" data-open-trap="${escHtml(nextIt.id)}">#${escHtml(nextIt.code)} &rsaquo;</button>` : ""}
          </div>
        </div>

        <div class="trap-reader-meta">
          <span class="trap-code">${it.id === "bonus_b1" ? "BONUS B1" : "#" + escHtml(it.code)}</span>
          <span class="badge">${escHtml(it.pillar)}</span>
          <span class="badge">1.0x SPOT ONLY</span>
          <span class="badge">RISK: ${(it.regime_risk || []).join(" / ")}</span>
          ${al ? `<span class="badge ${sevBadgeClass(al.status)}">LIVE: ${escHtml(al.status)}</span>` : ""}
        </div>

        ${al ? `<div class="trap-live-callout ${sevBadgeClass(al.status)}"><b>Live Telemetry Note:</b> ${escHtml(al.reason)}</div>` : ""}

        <div class="trap-quick-box">
          <div class="trap-kicker">10-SECOND BEGINNER SUMMARY</div>
          <div class="trap-q-row"><b>The Trap:</b> ${formatInlineMd(it.core_mistake)}</div>
          <div class="trap-q-row"><b>The Defense:</b> ${formatInlineMd(it.key_defense)}</div>
          ${
            (it.quick_steps || []).length
              ? `<div class="trap-q-steps">
                  <div class="trap-kicker" style="margin-top:8px;">ACTION CHECKLIST</div>
                  ${it.quick_steps
                    .map(
                      (s) => `
                    <div class="trap-q-step">
                      <b>${s.num}. ${formatInlineMd(s.title)}</b>${s.detail ? ` — ${formatInlineMd(s.detail)}` : ""}
                    </div>`
                    )
                    .join("")}
                </div>`
              : ""
          }
        </div>

        <div class="trap-md">
          ${renderMarkdownSafe(it.body_md)}
        </div>

        ${
          (it.related_traps || []).length
            ? `<div class="trap-related">
                <div class="trap-kicker">RELATED SPOT TRAPS</div>
                <div class="actions" style="margin-top:6px;">
                  ${it.related_traps
                    .map((rid) => {
                      const rel = itemById(rid);
                      return rel
                        ? `<button type="button" class="btn" data-open-trap="${escHtml(rel.id)}">#${escHtml(rel.code)} ${escHtml(rel.short_title)}</button>`
                        : "";
                    })
                    .join("")}
                </div>
              </div>`
            : ""
        }
      </div>
    `;
  }

  function render(state) {
    LAST_STATE = state ?? LAST_STATE;
    const host = document.getElementById("trapsRoot");
    if (!host) return;
    if (!BUNDLE) {
      host.innerHTML = `<div class="card"><p class="mut" style="margin:0;">Loading 16+1 Spot Trap Field Guide…</p></div>`;
      return;
    }

    const radar = evaluateLiveRadar(LAST_STATE);

    host.innerHTML = `
      <div class="trap-mode-bar">
        <div class="tabs" id="trapModeSeg" style="margin:0;">
          <button type="button" class="tab-btn ${MODE === "scanner" ? "active" : ""}" data-trap-mode="scanner">1. Live Radar &amp; Decision Scanner</button>
          <button type="button" class="tab-btn ${MODE === "library" ? "active" : ""}" data-trap-mode="library">2. Field Guide Library (16 Traps + B1)</button>
        </div>
        <button type="button" class="btn ${GUARDRAILS_OPEN ? "btn-primary" : ""}" id="btnToggleGuardrails">
          ${GUARDRAILS_OPEN ? "Hide" : "Show"} 7 Non-Negotiable 1.0x Spot Guardrails
        </button>
      </div>
      ${renderGuardrailsDrawer()}
      ${MODE === "scanner" ? renderScannerMode(LAST_STATE, radar) : renderLibraryMode(radar)}
    `;
  }

  function refreshScanOnly() {
    const card = document.getElementById("trapScanResultsCard");
    if (!card || !BUNDLE) return;
    const scan = scanUserDecision(LAST_STATE, FORM);
    card.innerHTML = renderScanResultsInner(scan);
  }

  function bindDomEvents() {
    const host = document.getElementById("trapsRoot");
    if (!host || host.dataset.trapsBound === "1") return;
    host.dataset.trapsBound = "1";

    host.addEventListener("click", (e) => {
      const modeBtn = e.target.closest("button[data-trap-mode]");
      if (modeBtn) {
        MODE = modeBtn.dataset.trapMode;
        if (MODE === "library" && SELECTED_ID && !itemById(SELECTED_ID)) SELECTED_ID = null;
        render(LAST_STATE);
        return;
      }

      if (e.target.closest("#btnToggleGuardrails")) {
        GUARDRAILS_OPEN = !GUARDRAILS_OPEN;
        render(LAST_STATE);
        return;
      }

      const actBtn = e.target.closest("button[data-trap-action]");
      if (actBtn) {
        FORM.action = actBtn.dataset.trapAction;
        host.querySelectorAll("button[data-trap-action]").forEach((b) => b.classList.toggle("active", b === actBtn));
        refreshScanOnly();
        return;
      }

      const pilBtn = e.target.closest("button[data-trap-pillar]");
      if (pilBtn) {
        PILLAR_FILTER = pilBtn.dataset.trapPillar;
        render(LAST_STATE);
        return;
      }

      const openBtn = e.target.closest("[data-open-trap]");
      if (openBtn) {
        openReader(openBtn.dataset.openTrap);
        return;
      }

      if (e.target.closest("#btnTrapBackLib")) {
        SELECTED_ID = null;
        render(LAST_STATE);
        return;
      }

      if (e.target.closest("#btnRunTrapScan")) {
        refreshScanOnly();
        document.getElementById("trapScanResultsCard")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        return;
      }

      if (e.target.closest("#btnResetTrapScan")) {
        FORM.entry = "";
        FORM.stop = "";
        FORM.target = "";
        FORM.text = "";
        FORM.flags.clear();
        render(LAST_STATE);
        return;
      }

      if (e.target.closest("#btnCopyTrapAi")) {
        const scan = scanUserDecision(LAST_STATE, FORM);
        const promptText = buildTrapAuditAiPrompt(LAST_STATE, scan);
        if (INIT_OPTS.copyWithFeedback) {
          INIT_OPTS.copyWithFeedback(promptText, "Copied Trap-Audit AI Prompt + 16+1 Rubric + Live JSON!", "trapAiMsg");
        }
      }
    });

    host.addEventListener("change", (e) => {
      const chk = e.target.closest("input[data-trap-flag]");
      if (chk) {
        if (chk.checked) FORM.flags.add(chk.dataset.trapFlag);
        else FORM.flags.delete(chk.dataset.trapFlag);
        chk.closest(".trap-chk-pill")?.classList.toggle("checked", chk.checked);
        refreshScanOnly();
      }
    });

    host.addEventListener("input", (e) => {
      const t = e.target;
      if (t.id === "trapScanEntry") {
        FORM.entry = t.value;
        refreshScanOnly();
      } else if (t.id === "trapScanStop") {
        FORM.stop = t.value;
        refreshScanOnly();
      } else if (t.id === "trapScanTarget") {
        FORM.target = t.value;
        refreshScanOnly();
      } else if (t.id === "trapScanText") {
        FORM.text = t.value;
        refreshScanOnly();
      } else if (t.id === "trapSearchInput") {
        SEARCH_QUERY = t.value;
        const gridHost = document.getElementById("trapLibGridHost");
        if (gridHost && BUNDLE) {
          gridHost.innerHTML = renderLibraryCardsHtml(evaluateLiveRadar(LAST_STATE));
        }
      }
    });
  }

  window.SpotTrapsModule = {
    async loadData() {
      const res = await fetch("data/spot_traps.json?t=" + Date.now(), { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      BUNDLE = await res.json();
      return BUNDLE;
    },
    init(opts = {}) {
      INIT_OPTS = opts;
      bindDomEvents();
    },
    getHubSummary(state) {
      const radar = evaluateLiveRadar(state);
      const topTitles = radar.activeIds
        .slice(0, 3)
        .map((id) => {
          const it = itemById(id);
          return it ? `#${it.code} ${it.short_title}` : id;
        });
      return {
        trafficLight: radar.trafficLight,
        activeCount: radar.activeIds.length,
        watchCount: radar.watchIds.length,
        topTitles,
      };
    },
    render,
    openReader,
  };
})();
