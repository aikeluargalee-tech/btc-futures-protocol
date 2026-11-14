import 'dart:convert';

ProtocolState parseProtocolState(String responseBody) {
  final raw = jsonDecode(responseBody) as Map<String, dynamic>;
  return ProtocolState.fromJson(raw);
}

double _asDouble(dynamic v, [double fallback = 0.0]) {
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v) ?? fallback;
  return fallback;
}

int _asInt(dynamic v, [int fallback = 0]) {
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v) ?? fallback;
  return fallback;
}

bool _asBool(dynamic v, [bool fallback = false]) {
  if (v is bool) return v;
  return fallback;
}

class ProtocolState {
  final String protocolVersion;
  final String protocolName;
  final String updatedAtUtc;
  final String last4hCloseUtc;
  final double price;
  final double chg24Pct;
  final String tickerSource;
  final RegimeData regime;
  final SignalData signal;
  final PortfolioData portfolio;
  final DerivativesData derivatives;
  final Map<String, List<ChartCandle>> charts;
  final List<MacroEventItem> macroCalendar;
  final List<AuditLogItem> auditLogRecent;
  final Map<String, dynamic> rawConfig;
  final List<String> fetchErrors;

  const ProtocolState({
    required this.protocolVersion,
    required this.protocolName,
    required this.updatedAtUtc,
    required this.last4hCloseUtc,
    required this.price,
    required this.chg24Pct,
    required this.tickerSource,
    required this.regime,
    required this.signal,
    required this.portfolio,
    required this.derivatives,
    required this.charts,
    required this.macroCalendar,
    required this.auditLogRecent,
    required this.rawConfig,
    required this.fetchErrors,
  });

  factory ProtocolState.fromJson(Map<String, dynamic> json) {
    final ticker = (json['ticker'] as Map<String, dynamic>?) ?? const {};
    final chartsRaw = (json['charts'] as Map<String, dynamic>?) ?? const {};
    final parsedCharts = <String, List<ChartCandle>>{};
    for (final key in ['h4', 'd1']) {
      final list = (chartsRaw[key] as List<dynamic>?) ?? const [];
      parsedCharts[key] = list
          .whereType<List<dynamic>>()
          .where((e) => e.length >= 5)
          .map(
            (e) => ChartCandle(
              tsMs: _asInt(e[0]),
              open: _asDouble(e[1]),
              high: _asDouble(e[2]),
              low: _asDouble(e[3]),
              close: _asDouble(e[4]),
            ),
          )
          .toList();
    }

    final cal = ((json['macro_calendar'] as List<dynamic>?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(MacroEventItem.fromJson)
        .toList();

    final logs = ((json['audit_log_recent'] as List<dynamic>?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(AuditLogItem.fromJson)
        .toList();

    final errs = ((json['fetch_errors'] as List<dynamic>?) ?? const [])
        .map((e) => e.toString())
        .toList();

    return ProtocolState(
      protocolVersion: (json['protocol_version'] ?? '4.0').toString(),
      protocolName: (json['protocol_name'] ?? 'BTC Short-Term Futures + Inventory Protocol').toString(),
      updatedAtUtc: (json['updated_at_utc'] ?? '').toString(),
      last4hCloseUtc: (json['last_4h_close_utc'] ?? '—').toString(),
      price: _asDouble(ticker['price']),
      chg24Pct: _asDouble(ticker['chg24_pct']),
      tickerSource: (ticker['source'] ?? 'Snapshot').toString(),
      regime: RegimeData.fromJson((json['regime'] as Map<String, dynamic>?) ?? const {}),
      signal: SignalData.fromJson((json['signal'] as Map<String, dynamic>?) ?? const {}),
      portfolio: PortfolioData.fromJson((json['portfolio'] as Map<String, dynamic>?) ?? const {}),
      derivatives: DerivativesData.fromJson(
        (json['derivatives'] as Map<String, dynamic>?) ?? const {},
        (json['extras'] as Map<String, dynamic>?) ?? const {},
        json['etf'] as Map<String, dynamic>?,
        json['stables'] as Map<String, dynamic>?,
      ),
      charts: parsedCharts,
      macroCalendar: cal,
      auditLogRecent: logs,
      rawConfig: (json['config'] as Map<String, dynamic>?) ?? const {},
      fetchErrors: errs,
    );
  }
}

class ChartCandle {
  final int tsMs;
  final double open;
  final double high;
  final double low;
  final double close;

  const ChartCandle({
    required this.tsMs,
    required this.open,
    required this.high,
    required this.low,
    required this.close,
  });
}

class FactorGroup {
  final String key;
  final double weight;
  final double score;
  final String summary;
  final Map<String, dynamic> components;

  const FactorGroup({
    required this.key,
    required this.weight,
    required this.score,
    required this.summary,
    required this.components,
  });

  factory FactorGroup.fromJson(String key, Map<String, dynamic> json) {
    return FactorGroup(
      key: key,
      weight: _asDouble(json['weight']),
      score: _asDouble(json['score'], 50.0),
      summary: (json['summary'] ?? '—').toString(),
      components: (json['components'] as Map<String, dynamic>?) ?? const {},
    );
  }
}

class RegimeData {
  final double score;
  final String bias;
  final String dailyBias;
  final double longThreshold;
  final double shortThreshold;
  final bool ddTier1Active;
  final bool isWeekendUtc;
  final List<String> dominantFactors;
  final Map<String, FactorGroup> groups;

  const RegimeData({
    required this.score,
    required this.bias,
    required this.dailyBias,
    required this.longThreshold,
    required this.shortThreshold,
    required this.ddTier1Active,
    required this.isWeekendUtc,
    required this.dominantFactors,
    required this.groups,
  });

  factory RegimeData.fromJson(Map<String, dynamic> json) {
    final th = (json['thresholds'] as Map<String, dynamic>?) ?? const {};
    final grpsRaw = (json['groups'] as Map<String, dynamic>?) ?? const {};
    final groups = <String, FactorGroup>{};
    for (final entry in grpsRaw.entries) {
      if (entry.value is Map<String, dynamic>) {
        groups[entry.key] = FactorGroup.fromJson(entry.key, entry.value as Map<String, dynamic>);
      }
    }
    return RegimeData(
      score: _asDouble(json['score'], 50.0),
      bias: (json['bias'] ?? 'FLAT').toString(),
      dailyBias: (json['daily_bias'] ?? 'NEUTRAL').toString(),
      longThreshold: _asDouble(th['long'], 68.0),
      shortThreshold: _asDouble(th['short'], 32.0),
      ddTier1Active: _asBool(th['dd_tier1_active']),
      isWeekendUtc: _asBool(json['is_weekend_utc']),
      dominantFactors: ((json['dominant_factors'] as List<dynamic>?) ?? const [])
          .map((e) => e.toString())
          .toList(),
      groups: groups,
    );
  }
}

class ChecklistItem {
  final int id;
  final String rule;
  final bool passed;
  final String detail;

  const ChecklistItem({
    required this.id,
    required this.rule,
    required this.passed,
    required this.detail,
  });

  factory ChecklistItem.fromJson(Map<String, dynamic> json) {
    return ChecklistItem(
      id: _asInt(json['id']),
      rule: (json['rule'] ?? '').toString(),
      passed: _asBool(json['passed']),
      detail: (json['detail'] ?? '').toString(),
    );
  }
}

class OrderProposal {
  final String direction;
  final String entryMethod;
  final double entryPrice;
  final double stopPrice;
  final double target1Price;
  final String target1Label;
  final double rawRr;
  final double fundingAdjustedRr;
  final double sizeBtc;
  final double notionalUsd;
  final double leverage;
  final bool leverageCapped;
  final double actualRiskPct;
  final double actualRiskUsd;
  final double stopDistancePct;
  final bool weekendHalved;

  const OrderProposal({
    required this.direction,
    required this.entryMethod,
    required this.entryPrice,
    required this.stopPrice,
    required this.target1Price,
    required this.target1Label,
    required this.rawRr,
    required this.fundingAdjustedRr,
    required this.sizeBtc,
    required this.notionalUsd,
    required this.leverage,
    required this.leverageCapped,
    required this.actualRiskPct,
    required this.actualRiskUsd,
    required this.stopDistancePct,
    required this.weekendHalved,
  });

  factory OrderProposal.fromJson(Map<String, dynamic> json) {
    return OrderProposal(
      direction: (json['direction'] ?? 'FLAT').toString(),
      entryMethod: (json['entry_method'] ?? '—').toString(),
      entryPrice: _asDouble(json['entry_price']),
      stopPrice: _asDouble(json['stop_price']),
      target1Price: _asDouble(json['target1_price']),
      target1Label: (json['target1_label'] ?? '—').toString(),
      rawRr: _asDouble(json['raw_rr']),
      fundingAdjustedRr: _asDouble(json['funding_adjusted_rr']),
      sizeBtc: _asDouble(json['size_btc']),
      notionalUsd: _asDouble(json['notional_usd']),
      leverage: _asDouble(json['leverage']),
      leverageCapped: _asBool(json['leverage_capped']),
      actualRiskPct: _asDouble(json['actual_risk_pct']),
      actualRiskUsd: _asDouble(json['actual_risk_usd']),
      stopDistancePct: _asDouble(json['stop_distance_pct']),
      weekendHalved: _asBool(json['weekend_halved']),
    );
  }
}

class SellInventoryData {
  final bool active;
  final double recommendedPct;
  final String bandPct;
  final double spotInventoryBtc;
  final double sellBtc;
  final double sellUsd;
  final String structuralRef;
  final String reason;

  const SellInventoryData({
    required this.active,
    required this.recommendedPct,
    required this.bandPct,
    required this.spotInventoryBtc,
    required this.sellBtc,
    required this.sellUsd,
    required this.structuralRef,
    required this.reason,
  });

  factory SellInventoryData.fromJson(Map<String, dynamic> json) {
    return SellInventoryData(
      active: _asBool(json['active']),
      recommendedPct: _asDouble(json['recommended_pct'], 20.0),
      bandPct: (json['band_pct'] ?? '15–25%').toString(),
      spotInventoryBtc: _asDouble(json['spot_inventory_btc'], 2.0),
      sellBtc: _asDouble(json['sell_btc']),
      sellUsd: _asDouble(json['sell_usd']),
      structuralRef: (json['structural_ref'] ?? '—').toString(),
      reason: (json['reason'] ?? '—').toString(),
    );
  }
}

class StructuralLevel {
  final double price;
  final String label;
  final String kind;

  const StructuralLevel({required this.price, required this.label, required this.kind});

  factory StructuralLevel.fromJson(Map<String, dynamic> json) {
    return StructuralLevel(
      price: _asDouble(json['price']),
      label: (json['label'] ?? '').toString(),
      kind: (json['kind'] ?? 'pivot').toString(),
    );
  }
}

class SignalData {
  final String status;
  final List<String> activeSignals;
  final List<ChecklistItem> checklist;
  final List<String> rejectionReasons;
  final OrderProposal? proposal;
  final SellInventoryData sellInventory;
  final List<StructuralLevel> structuralLevels;

  const SignalData({
    required this.status,
    required this.activeSignals,
    required this.checklist,
    required this.rejectionReasons,
    required this.proposal,
    required this.sellInventory,
    required this.structuralLevels,
  });

  factory SignalData.fromJson(Map<String, dynamic> json) {
    final checks = ((json['checklist'] as List<dynamic>?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(ChecklistItem.fromJson)
        .toList();
    final lvls = ((json['structural_levels'] as List<dynamic>?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(StructuralLevel.fromJson)
        .toList();
    final propMap = json['proposal'] as Map<String, dynamic>?;
    return SignalData(
      status: (json['status'] ?? 'FLAT').toString(),
      activeSignals: ((json['active_signals'] as List<dynamic>?) ?? const ['FLAT'])
          .map((e) => e.toString())
          .toList(),
      checklist: checks,
      rejectionReasons: ((json['rejection_reasons'] as List<dynamic>?) ?? const [])
          .map((e) => e.toString())
          .toList(),
      proposal: propMap != null ? OrderProposal.fromJson(propMap) : null,
      sellInventory: SellInventoryData.fromJson(
        (json['sell_inventory'] as Map<String, dynamic>?) ?? const {},
      ),
      structuralLevels: lvls,
    );
  }
}

class CircuitBreakers {
  final bool intradayHalted;
  final bool dailyHalted;
  final bool weeklyHalted;
  final bool ddTier1Active;
  final bool ddTier2Locked;

  const CircuitBreakers({
    required this.intradayHalted,
    required this.dailyHalted,
    required this.weeklyHalted,
    required this.ddTier1Active,
    required this.ddTier2Locked,
  });

  factory CircuitBreakers.fromJson(Map<String, dynamic> json) {
    return CircuitBreakers(
      intradayHalted: _asBool(json['intraday_halted']),
      dailyHalted: _asBool(json['daily_halted']),
      weeklyHalted: _asBool(json['weekly_halted']),
      ddTier1Active: _asBool(json['dd_tier1_active']),
      ddTier2Locked: _asBool(json['dd_tier2_locked']),
    );
  }

  List<String> get activeLabels {
    final list = <String>[];
    if (intradayHalted) list.add('INTRADAY -1.2%');
    if (dailyHalted) list.add('DAILY -2.0%');
    if (weeklyHalted) list.add('WEEKLY -4.0%');
    if (ddTier1Active) list.add('DD -6.0%');
    if (ddTier2Locked) list.add('DD -10.0% LOCK');
    return list;
  }
}

class PortfolioData {
  final double equityUsd;
  final double highWaterMarkUsd;
  final double spotInventoryBtc;
  final double drawdownPct;
  final double intradayPnlPct;
  final double dailyPnlPct;
  final double weeklyPnlPct;
  final double openHeatPct;
  final double maxHeatPct;
  final double currentLeverage;
  final double maxLeverage;
  final CircuitBreakers breakers;
  final List<Map<String, dynamic>> openPositions;
  final List<Map<String, dynamic>> closedTrades;
  final int totalClosedLegs;
  final double winRatePct;
  final double profitFactor;
  final double expectancyR;
  final double netRealizedPnlUsd;

  const PortfolioData({
    required this.equityUsd,
    required this.highWaterMarkUsd,
    required this.spotInventoryBtc,
    required this.drawdownPct,
    required this.intradayPnlPct,
    required this.dailyPnlPct,
    required this.weeklyPnlPct,
    required this.openHeatPct,
    required this.maxHeatPct,
    required this.currentLeverage,
    required this.maxLeverage,
    required this.breakers,
    required this.openPositions,
    required this.closedTrades,
    required this.totalClosedLegs,
    required this.winRatePct,
    required this.profitFactor,
    required this.expectancyR,
    required this.netRealizedPnlUsd,
  });

  factory PortfolioData.fromJson(Map<String, dynamic> json) {
    final rev = (json['review'] as Map<String, dynamic>?) ?? const {};
    return PortfolioData(
      equityUsd: _asDouble(json['equity_usd'], 100000.0),
      highWaterMarkUsd: _asDouble(json['high_water_mark_usd'], 100000.0),
      spotInventoryBtc: _asDouble(json['spot_inventory_btc'], 2.0),
      drawdownPct: _asDouble(json['drawdown_pct']),
      intradayPnlPct: _asDouble(json['intraday_pnl_pct']),
      dailyPnlPct: _asDouble(json['daily_pnl_pct']),
      weeklyPnlPct: _asDouble(json['weekly_pnl_pct']),
      openHeatPct: _asDouble(json['open_heat_pct']),
      maxHeatPct: _asDouble(json['max_heat_pct'], 1.5),
      currentLeverage: _asDouble(json['current_leverage']),
      maxLeverage: _asDouble(json['max_leverage'], 2.0),
      breakers: CircuitBreakers.fromJson(
        (json['circuit_breakers'] as Map<String, dynamic>?) ?? const {},
      ),
      openPositions: ((json['open_positions'] as List<dynamic>?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .toList(),
      closedTrades: ((json['closed_trades'] as List<dynamic>?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .toList(),
      totalClosedLegs: _asInt(rev['total_closed_legs']),
      winRatePct: _asDouble(rev['win_rate_pct']),
      profitFactor: _asDouble(rev['profit_factor']),
      expectancyR: _asDouble(rev['expectancy_r']),
      netRealizedPnlUsd: _asDouble(rev['total_realized_pnl_usd']),
    );
  }
}

class DerivativesData {
  final double? fundingRatePct;
  final double? oiBtc;
  final double? dvol;
  final int? fngValue;
  final String? fngLabel;
  final double? etfLatestM;
  final double? etf5dM;
  final double? stablesB;
  final double? stables7dPct;

  const DerivativesData({
    this.fundingRatePct,
    this.oiBtc,
    this.dvol,
    this.fngValue,
    this.fngLabel,
    this.etfLatestM,
    this.etf5dM,
    this.stablesB,
    this.stables7dPct,
  });

  factory DerivativesData.fromJson(
    Map<String, dynamic> deriv,
    Map<String, dynamic> extras,
    Map<String, dynamic>? etf,
    Map<String, dynamic>? stables,
  ) {
    return DerivativesData(
      fundingRatePct: deriv['current_rate_pct'] is num ? _asDouble(deriv['current_rate_pct']) : null,
      oiBtc: deriv['oi_btc'] is num ? _asDouble(deriv['oi_btc']) : null,
      dvol: extras['dvol'] is num ? _asDouble(extras['dvol']) : null,
      fngValue: extras['fng_value'] is num ? _asInt(extras['fng_value']) : null,
      fngLabel: extras['fng_label']?.toString(),
      etfLatestM: etf != null && etf['latest_usd_m'] is num ? _asDouble(etf['latest_usd_m']) : null,
      etf5dM: etf != null && etf['sum5_usd_m'] is num ? _asDouble(etf['sum5_usd_m']) : null,
      stablesB: stables != null && stables['total_usd_b'] is num ? _asDouble(stables['total_usd_b']) : null,
      stables7dPct: stables != null && stables['chg7d_pct'] is num ? _asDouble(stables['chg7d_pct']) : null,
    );
  }
}

class MacroEventItem {
  final String title;
  final String timeUtc;
  final double minutesAway;

  const MacroEventItem({required this.title, required this.timeUtc, required this.minutesAway});

  factory MacroEventItem.fromJson(Map<String, dynamic> json) {
    return MacroEventItem(
      title: (json['title'] ?? '').toString(),
      timeUtc: (json['time_utc'] ?? '').toString(),
      minutesAway: _asDouble(json['minutes_away'], 9999),
    );
  }
}

class AuditLogItem {
  final String ts;
  final String event;
  final String detail;

  const AuditLogItem({required this.ts, required this.event, required this.detail});

  factory AuditLogItem.fromJson(Map<String, dynamic> json) {
    return AuditLogItem(
      ts: (json['ts'] ?? json['ts_utc'] ?? '').toString(),
      event: (json['event'] ?? '').toString(),
      detail: (json['detail'] ?? '').toString(),
    );
  }
}
