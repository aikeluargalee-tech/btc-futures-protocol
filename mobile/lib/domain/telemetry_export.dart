import 'dart:convert';

import 'models/protocol_state.dart';

const String masterQuantPromptTemplate = r'''### ROLE & OBJECTIVE
Act as an Institutional Quantitative Bitcoin Swing Strategist and Risk Officer. Below is a raw, unopinionated market telemetry packet from the **BTC Short-Term Futures Protocol (v4.0)**. Your job is to analyze the raw data independently from first principles (Auction Market Theory, 4H/1D price structure, Volume Profile, momentum exhaustion vs. impulse, multi-venue derivatives positioning, and institutional ETF/stablecoin flows) and issue an unbiased Long, Short, or Stand-Aside execution verdict.

---

### HARD PROTOCOL RISK CONSTRAINTS (NON-NEGOTIABLE)
Every trade idea you evaluate MUST strictly obey these guardrails:
1. **Evaluation Cadence & Hold Window:** Signals are evaluated on **4H candle closes** with a **maximum hold window of 24 hours** (time-stop reduction at 8h, hard exit at 12–24h if stagnant).
2. **Leverage & Capital Risk:**
   - Maximum Futures Leverage: **1:2 (2.0x Isolated)**.
   - Maximum Risk per Trade: **0.40% of Account Equity** on weekdays; **0.20% (halved)** on weekends (`is_weekend_utc: true`).
   - Maximum Portfolio Heat: **<= 1.50%** across all open risk.
   - Maximum Concurrent Futures Positions: **1** (LONG or SHORT only).
3. **Structural Geometry & R:R:**
   - **Minimum Reward-to-Risk (R:R):** **>= 1.6 : 1** to the first major opposing structural level (`Target 1`), net of estimated 24h funding and maker/taker fee drag.
   - **Maximum Stop Distance:** **<= 2.20%** from entry (placed beyond structural invalidation + ATR buffer).
4. **Macro Blackout:** **Zero new entries** if a high-impact USD macro release is scheduled within **<= 60 minutes**.
5. **Anti-Chasing & Exhaustion Guardrail (CRITICAL):**
   - **DO NOT** recommend market shorting into extreme oversold capitulation (`rsi_4h < 25`, `rsi_d < 30`, `fng_value < 15`, or price sitting directly on top of a primary 4H/1D support level where R:R to the next support is `< 1.6:1`).
   - **DO NOT** recommend market longing into extreme overbought exhaustion (`rsi_4h > 75`) or directly beneath a major resistance ceiling.
   - When trend and momentum are aligned in a strong impulse but price is overextended, your verdict MUST be **`STAND ASIDE / CONDITIONAL LIMIT ORDER`** at a mean-reversion structural pullback level (e.g., 4H EMA20, prior broken S/R, or 30D Volume Profile node).

---

### REQUIRED 4-STEP ANALYTICAL OUTPUT FORMAT

#### 1. EXECUTIVE DIRECTIVE (3-Second Summary)
- **Verdict:** `[STAND ASIDE — WAIT]` | `[PLACE CONDITIONAL LIMIT ORDER]` | `[EXECUTE LONG/SHORT ON 4H CLOSE]`
- **Directional Bias:** `BULLISH` | `BEARISH` | `NEUTRAL / RANGE-BOUND` (State 1D structural bias vs. 4H tactical state).
- **Primary Rationale:** 2 concise sentences explaining *why* with concrete prices, RSI/ATR figures, and R:R math.

#### 2. 5-PILLAR TELEMETRY AUDIT
- **A. Price Structure & Volume Profile:** Analyze `charts.h4` and `charts.d1` OHLCV arrays (`[ts, O, H, L, C, Vol]`), EMA alignment (`ema20_4h`, `ema50_4h`, `ema50_d`, `ema200_d`), and distance to `30D VAH / VPOC / VAL` and nearest swing highs/lows.
- **B. Momentum & Volatility Regime:** Evaluate `rsi_4h`, `rsi_d`, `roc6/12/20_4h_pct`, `atr_4h_usd` (`atr_4h_percentile`), and `dvol`. Classify as **Compression**, **Early Expansion**, or **Late Climax / Exhaustion**.
- **C. Multi-Venue Derivatives & Microstructure:** Evaluate `funding_rate_pct` across OKX, Kraken Futures, Deribit, and Hyperliquid plus `oi_btc` / `venue_oi_btc`. Identify crowding or squeeze asymmetry.
- **D. Institutional Flows & Macro Context:** Evaluate 5-day ETF flows (`etf.sum5_usd_m`), 7d stablecoin liquidity (`stables.chg7d_pct`), `dxy`, `vix`, Fear & Greed (`fng_value`), and weekend/session liquidity (`session_name`).
- **E. Telemetry Integrity Check:** Flag any `fetch_errors` or timestamp staleness (`updated_at_utc` vs. `last_4h_close_utc`) that reduce conviction.

#### 3. FUTURES EXECUTION VERDICT (1:2 ISOLATED LONG / SHORT)
State clearly whether an immediate **4H Close Long**, **4H Close Short**, or **Flat / Wait** setup passes all v4.0 rules right now, listing which rules pass or block.

#### 4. CALCULATOR-READY EXECUTION OR CONDITIONAL TRIGGER TABLE
*(If `STAND ASIDE` at market, provide the exact **Conditional Limit / Alert Setup** that WOULD satisfy >= 1.6:1 R:R and <= 2.2% stop distance on a retest)*:
- **Setup Type:** `Market on 4H Close` OR `Conditional Retest / Limit`
- **Direction:** `LONG` | `SHORT`
- **Trigger / Entry Price ($):** `$XX,XXX` (Structural level reference)
- **Hard Invalidation Stop ($ & %):** `$XX,XXX` (`X.XX%` — must be `<= 2.20%`)
- **Target 1 ($ & R:R):** `$XX,XXX` (`X.XX : 1` — must be `>= 1.60 : 1`)
- **Target 2 ($ & R:R):** `$XX,XXX` (`X.XX : 1`)
- **Recommended Risk %:** `0.40%` (or `0.20%` if Weekend)
- **What Invalidates Waiting for This Setup:** Exact price level or candle close that cancels the plan.

After issuing your structured verdict above, remain grounded strictly in the telemetry packet below and answer any follow-up Q&A—whether for **Spot positioning** (1.0x unleveraged accumulation/hedging levels with no funding drag) or **Futures leverage decisions** (1:2 max isolated sizing, invalidation distance, funding/slippage sensitivity, or custom equity sizing)—without inventing external prices.

---

### LIVE RAW TELEMETRY PACKET (JSON)
```json
{{RAW_JSON_PAYLOAD}}
```''';

final RegExp _compactOhlcvRegex = RegExp(
  r'\[\s*(-?\d+(?:\.\d+)?(?:\s*,\s*-?\d+(?:\.\d+)?){4,5})\s*\]',
);

/// Builds the unopinionated raw telemetry packet (no pre-computed verdicts),
/// mirroring `buildRawTelemetryPacket` in the web dashboard (`app.js`).
Map<String, dynamic> buildRawTelemetryPacket(
  ProtocolState state, {
  double? livePrice,
  String? liveSource,
}) {
  final raw = state.rawState;
  Map<String, dynamic> asMap(dynamic v) =>
      v is Map<String, dynamic> ? v : const {};
  List<dynamic> asList(dynamic v) => v is List<dynamic> ? v : const [];

  final regimeMap = asMap(raw['regime']);
  final groups = asMap(regimeMap['groups']);
  final ts = asMap(groups['trend_structure']);
  final mom = asMap(groups['momentum']);
  final vl = asMap(groups['volatility_liquidity']);
  final sc = asMap(groups['session_context']);

  final signalMap = asMap(raw['signal']);
  final tickerMap = asMap(raw['ticker']);
  final extrasMap = asMap(raw['extras']);
  final derivMap = asMap(raw['derivatives']);
  final chartsMap = asMap(raw['charts']);
  final configMap = state.rawConfig;
  final lr = asMap(configMap['leverage_and_risk']);
  final th = asMap(configMap['timeframe_and_hold']);

  final refPrice = (livePrice != null && livePrice > 0) ? livePrice : state.price;
  final atrRaw = vl['atr_4h_usd'] ?? signalMap['atr_4h'];
  final atrUsd = atrRaw is num ? atrRaw.toDouble() : 0.0;

  double round2(double v) => double.parse(v.toStringAsFixed(2));

  final levels = state.signal.structuralLevels.map((l) {
    final diff = refPrice > 0 ? l.price - refPrice : 0.0;
    return <String, dynamic>{
      'label': l.label,
      'kind': l.kind,
      'price': l.price,
      'distance_pct': refPrice > 0 ? round2((diff / refPrice) * 100.0) : null,
      'distance_atr': atrUsd > 0 ? round2(diff / atrUsd) : null,
    };
  }).toList();

  List<dynamic> last30(List<dynamic> src) =>
      src.length > 30 ? src.sublist(src.length - 30) : src;

  return <String, dynamic>{
    'meta': <String, dynamic>{
      'protocol_version': state.protocolVersion,
      'updated_at_utc': state.updatedAtUtc,
      'updated_at_ms': raw['updated_at_ms'],
      'last_4h_close_utc': state.last4hCloseUtc,
      'session_name': sc['session_name'],
      'is_weekend_utc': state.regime.isWeekendUtc,
    },
    'ticker': <String, dynamic>{
      if (tickerMap.isNotEmpty) ...tickerMap else ...{
        'price': state.price,
        'chg24_pct': state.chg24Pct,
        'source': state.tickerSource,
      },
      'live_spot_price': livePrice,
      'live_spot_source': liveSource,
    },
    'indicators': <String, dynamic>{
      'trend': <String, dynamic>{
        'ema20_4h': ts['ema20_4h'],
        'ema50_4h': ts['ema50_4h'],
        'ema50_d': ts['ema50_d'],
        'ema200_d': ts['ema200_d'],
        'h4_structure': ts['h4_structure'],
        'daily_structure': ts['daily_structure'],
      },
      'momentum': <String, dynamic>{
        'rsi_4h': mom['rsi_4h'],
        'rsi_d': mom['rsi_d'],
        'roc6_4h_pct': mom['roc6_4h_pct'],
        'roc12_4h_pct': mom['roc12_4h_pct'],
        'roc20_4h_pct': mom['roc20_4h_pct'],
      },
      'volatility_volume': <String, dynamic>{
        'atr_4h_usd': atrUsd > 0 ? atrUsd : null,
        'atr_4h_pct': vl['atr_4h_pct'],
        'atr_4h_percentile': vl['atr_4h_percentile'],
        'rel_volume_4h': vl['rel_volume_4h'],
        'dvol': extrasMap['dvol'],
      },
    },
    'structural_levels': levels,
    'derivatives': <String, dynamic>{
      if (derivMap.isNotEmpty) ...derivMap else ...{
        'current_rate_pct': state.derivatives.fundingRatePct,
        'oi_btc': state.derivatives.oiBtc,
      },
      'funding_30d_percentile': vl['funding_30d_percentile'],
    },
    'macro_and_flows': <String, dynamic>{
      'vix': sc['vix'],
      'dxy': sc['dxy'],
      'fng_value': extrasMap['fng_value'],
      'fng_label': extrasMap['fng_label'],
      'etf': raw['etf'],
      'stables': raw['stables'],
      'macro_calendar': raw['macro_calendar'] ?? const [],
      'next_macro_event': sc['next_macro_event'],
      'next_macro_minutes': sc['next_macro_minutes'],
    },
    'charts_ohlcv_last30': <String, dynamic>{
      'schema': '[timestamp_ms, open, high, low, close, volume]',
      'h4': last30(asList(chartsMap['h4'])),
      'd1': last30(asList(chartsMap['d1'])),
    },
    'risk_constraints_reference': <String, dynamic>{
      'max_leverage': lr['max_leverage'] ?? 2.0,
      'risk_per_trade_pct': lr['risk_per_trade_pct'] ?? 0.004,
      'weekend_size_mult': th['weekend_size_mult'] ?? 0.5,
      'max_portfolio_heat_pct': lr['max_portfolio_heat_pct'] ?? 0.015,
      'max_concurrent_futures': lr['max_concurrent_futures'] ?? 1,
      'min_rr': lr['min_rr'] ?? 1.6,
      'max_stop_distance_pct': lr['max_stop_distance_pct'] ?? 0.022,
      'max_hold_hours': th['max_hold_hours'] ?? 24,
      'macro_blackout_minutes': lr['macro_blackout_minutes'] ?? 60,
    },
    'fetch_errors': state.fetchErrors,
  };
}

/// Serializes JSON with compact single-line 5–6 element numeric OHLCV arrays.
String serializeTelemetryCompact(Map<String, dynamic> raw) {
  final pretty = const JsonEncoder.withIndent('  ').convert(raw);
  return pretty.replaceAllMapped(_compactOhlcvRegex, (m) {
    final inner = m.group(1)!.replaceAll(RegExp(r'\s+'), ' ');
    return '[$inner]';
  });
}

String buildFullAiPrompt(
  ProtocolState state, {
  double? livePrice,
  String? liveSource,
}) {
  final packet = buildRawTelemetryPacket(
    state,
    livePrice: livePrice,
    liveSource: liveSource,
  );
  final compactJson = serializeTelemetryCompact(packet);
  return masterQuantPromptTemplate.replaceFirst('{{RAW_JSON_PAYLOAD}}', compactJson);
}
