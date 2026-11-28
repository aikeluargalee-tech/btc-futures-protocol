"use strict";

(function () {
  function escHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  function fmtUtcSgtStamp(ms) {
    const u = new Date(ms);
    const s = new Date(ms + 8 * 3600 * 1000);
    const p2 = (n) => String(n).padStart(2, "0");
    const fmt = (d) =>
      `${d.getUTCFullYear()}-${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())} ` +
      `${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}:${p2(d.getUTCSeconds())}`;
    return {
      utc: `${fmt(u)} UTC`,
      sgt: `${fmt(s)} SGT`,
      pair: `${fmt(u)} UTC / ${fmt(s)} SGT`,
    };
  }

  function buildDisruptionScannerPrompt() {
    const nowMs = Date.now();
    const startMs = nowMs - 6 * 3600 * 1000;
    const nowStamp = fmtUtcSgtStamp(nowMs);
    const startStamp = fmtUtcSgtStamp(startMs);
    const meta = window.DeskI18n?.getMeta();
    const langPrefix =
      meta && meta.code !== "en"
        ? `**Response Language:** Respond strictly in ${meta.aiName} while keeping all event timestamps, URLs, and category codes exact.\n\n`
        : "";

    return (
      langPrefix +
      `AUTO-STAMPED SCAN CLOCK (USE EXACTLY):
- Scan Time Now: ${nowStamp.pair}
- Exact 6-Hour Window Start: ${startStamp.pair}
- Exact 6-Hour Window End: ${nowStamp.pair}

# BTC DISRUPTION SCANNER
NEWS INTELLIGENCE | PRE-TRADE INPUT

### ROLE
Act as an independent financial and cryptocurrency intelligence analyst.

Scan the SIX HOURS immediately preceding this request (${startStamp.utc} to ${nowStamp.utc}) for material developments that could disrupt Bitcoin's market environment.

This is news intelligence collection, NOT BTC technical analysis or trading advice.

### 1. CATEGORIES

1. MACRO: Federal Reserve, inflation, employment, interest rates, DXY, Treasury yields, liquidity, China.
2. CRYPTO: BTC regulation, ETF flows, institutional activity, exchange failures, hacks, stablecoins, major on-chain developments.
3. RISK-ON / RISK-OFF: S&P 500, Nasdaq, VIX, Gold, oil, dollar movements, credit stress.
4. GEOPOLITICAL: Wars, sanctions, US-China tensions, Iran, Russia, trade restrictions, systemic financial risks.
5. POLITICAL / REGULATORY: Trump administration decisions, SEC, CFTC, major government interventions.

### 2. FORWARD CALENDAR (new — do this even if nothing material happened)

List any SCHEDULED event in the next 72 HOURS that could move BTC:
FOMC decisions and minutes, CPI / PPI / NFP releases, options expiry, ETF decision deadlines, court dates, hard forks, regulatory comment deadlines.

For each: event | date and exact UTC + SGT (UTC+8) time | expected impact (HIGH/MED/LOW) | why it matters.

If the calendar is genuinely empty, say "NONE next 72h" and name the calendar you checked.
An empty backward scan with a loaded forward calendar is NOT a quiet environment — say so.

### 3. FILTERING AND VERIFICATION

- Report only MEDIUM, HIGH or CRITICAL developments.
- Ignore routine news, opinion, speculation and recycled headlines.
- Prioritise official sources and established financial news organisations.
- Provide a direct URL and exact publication time in UTC + SGT (UTC+8) for every item.
- Distinguish EVENT time from PUBLICATION time. A story about something that happened last week is not a six-hour development; label it.
- State the AGE IN HOURS of each item at the time of this scan.
- State the SOURCE COUNT: "1 outlet" or "2+ independent outlets". Outlets repeating one original report count as ONE source and must be labelled as such.
- Separate CONFIRMED facts from DEVELOPING or UNVERIFIED reports.
- Explain the potential BTC transmission channel.
- Do not assume every financial or geopolitical shock is bearish for BTC. Debasement, banking stress and capital controls have historically been bid for BTC. State direction honestly.

### 4. OUTPUT

A. SCAN METADATA
- Current UTC and SGT (UTC+8) time.
- Six-hour search window (exact start and end in UTC + SGT).
- Sources checked, by name.
- Coverage limitations — specifically: what you could NOT see (paywalled outlets, exchange status APIs, private Telegram/Discord channels, anything unpublished).

B. MATERIAL DEVELOPMENTS
For each qualifying item, give all fields:
Category | Event | Source URL | Event time UTC+SGT | Published UTC+SGT | Age (hours) | Source count (1 outlet / 2+) | Magnitude MED/HIGH/CRITICAL | BTC Bias BULLISH/BEARISH/MIXED/NEUTRAL | Confidence HIGH/MED/LOW | Transmission channel | Why it matters

Rank by potential impact, not publication time.

C. CROSS-MARKET ASSESSMENT
Summarise verified developments affecting:
- Global liquidity and monetary policy
- Dollar and Treasury markets
- Equity risk appetite
- Institutional crypto flows
- Crypto infrastructure and systemic stability

D. EXECUTIVE SUMMARY
1. Biggest bullish catalyst.
2. Biggest bearish catalyst.
3. Biggest systemic threat.
4. Most important unresolved development.
5. Nearest scheduled event in the forward calendar.
6. Overall external environment: RISK-ON / RISK-OFF / MIXED / UNRESOLVED.

### 5. FINAL RULES

- No invented facts, timestamps or URLs.
- No unsupported directional conclusions.
- No BTC price predictions, technical analysis, entries, targets or trade recommendations.
- Label every single-outlet claim explicitly; do not present a headline as an event.
- If no material developments occurred in the last 6 hours, state "NONE LAST 6H" explicitly, still complete Section 2 (72-hour forward calendar), and do not pad with low-impact filler.`
    );
  }

  const DESK_PROMPTS = [
    {
      id: "disruption_scanner",
      title: "BTC Disruption Scanner (6H Shock + 72H Calendar)",
      badge: "PRE-TRADE VETO CHECK · LIVE WEB/X AI",
      buttonLabel: "[Copy Disruption Scanner Prompt]",
      copiedLabel: "Copied 6H Disruption Scanner Prompt! Paste into Grok, Perplexity, Gemini, or ChatGPT Search.",
      desc: "Scan the last 6 hours for breaking macro, crypto, geopolitical or regulatory shocks + next 72h calendar before ticking Disruption Veto in F10. Paste into an AI with live web search.",
      aiLinks: [
        { label: "Grok", url: "https://grok.com/" },
        { label: "Perplexity", url: "https://www.perplexity.ai/" },
        { label: "Gemini", url: "https://gemini.google.com/app" },
        { label: "ChatGPT", url: "https://chatgpt.com/" },
      ],
      buildPrompt: buildDisruptionScannerPrompt,
    },
  ];

  const PREVIEW_OPEN = new Set();

  function renderNewsShelf(hostId, copyFn) {
    const host = document.getElementById(hostId);
    if (!host) return;

    if (host.dataset.bound !== "1") {
      host.dataset.bound = "1";
      host.addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-copy-prompt]");
        if (!btn) return;
        const id = btn.dataset.copyPrompt;
        const item = DESK_PROMPTS.find((p) => p.id === id);
        if (!item) return;
        const text = item.buildPrompt();
        if (typeof copyFn === "function") {
          copyFn(text, item.copiedLabel, `promptMsg_${id}`);
        } else {
          navigator.clipboard?.writeText?.(text);
        }
        const pre = host.querySelector(`[data-preview-pre="${id}"]`);
        if (pre) pre.textContent = text;
      });
      host.addEventListener(
        "toggle",
        (e) => {
          const det = e.target.closest("details[data-prompt-preview]");
          if (!det) return;
          const id = det.dataset.promptPreview;
          if (det.open) {
            PREVIEW_OPEN.add(id);
            const item = DESK_PROMPTS.find((p) => p.id === id);
            const pre = det.querySelector(`[data-preview-pre="${id}"]`);
            if (item && pre) pre.textContent = item.buildPrompt();
          } else {
            PREVIEW_OPEN.delete(id);
          }
        },
        true
      );
    }

    host.innerHTML = `
      <div class="prompt-shelf-head">
        <div>
          <h2>AI Intelligence Prompts</h2>
          <div class="mut">Live external search prompts built for beginners — stamps exact UTC &amp; SGT (UTC+8) time automatically on copy.</div>
        </div>
        <span class="badge">${DESK_PROMPTS.length} PROMPT${DESK_PROMPTS.length === 1 ? "" : "S"}</span>
      </div>
      <div class="prompt-shelf-list">
        ${DESK_PROMPTS.map((p) => {
          const isOpen = PREVIEW_OPEN.has(p.id);
          return `
            <div class="prompt-card">
              <div class="prompt-card-top">
                <div class="prompt-card-title">${escHtml(p.title)}</div>
                <span class="badge warn">${escHtml(p.badge)}</span>
              </div>
              <p class="mut" style="margin:4px 0 8px;">${escHtml(p.desc)}</p>
              <div class="actions">
                <button type="button" class="btn btn-primary" data-copy-prompt="${escHtml(p.id)}">${escHtml(p.buttonLabel)}</button>
                <span class="mut" id="promptMsg_${escHtml(p.id)}" style="align-self:center;">Auto-stamps exact UTC + SGT 6h window when copied.</span>
              </div>
              <div class="prompt-handoff">
                <span class="mut"><b>Best with live search:</b></span>
                ${p.aiLinks.map((a) => `<a class="prompt-chatlink" href="${escHtml(a.url)}" target="_blank" rel="noopener">${escHtml(a.label)}</a>`).join("")}
              </div>
              <details class="prompt-preview-drawer" data-prompt-preview="${escHtml(p.id)}" ${isOpen ? "open" : ""}>
                <summary>Preview Prompt Template</summary>
                <pre class="prompt-preview-pre" data-preview-pre="${escHtml(p.id)}">${isOpen ? escHtml(p.buildPrompt()) : ""}</pre>
              </details>
            </div>
          `;
        }).join("")}
      </div>
    `;
  }

  window.DeskPromptsModule = {
    list: () => DESK_PROMPTS.slice(),
    build: (id) => DESK_PROMPTS.find((p) => p.id === id)?.buildPrompt() || "",
    renderNewsShelf,
  };
})();
