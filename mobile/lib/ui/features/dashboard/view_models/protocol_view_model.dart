import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/foundation.dart';

import '../../../../data/repositories/protocol_repository.dart';
import '../../../../domain/models/protocol_state.dart';

class CalcResult {
  final bool valid;
  final List<String> issues;
  final double riskPct;
  final double targetRiskUsd;
  final double sizeBtc;
  final double notionalUsd;
  final double leverage;
  final bool leverageCapped;
  final double actualRiskUsd;
  final double actualRiskPct;
  final double stopDistPct;
  final double rawRr;
  final double sell20Btc;
  final double sell20Usd;

  const CalcResult({
    required this.valid,
    required this.issues,
    required this.riskPct,
    required this.targetRiskUsd,
    required this.sizeBtc,
    required this.notionalUsd,
    required this.leverage,
    required this.leverageCapped,
    required this.actualRiskUsd,
    required this.actualRiskPct,
    required this.stopDistPct,
    required this.rawRr,
    required this.sell20Btc,
    required this.sell20Usd,
  });
}

class ProtocolViewModel extends ChangeNotifier {
  ProtocolViewModel({
    required ProtocolRepository repository,
    this.enableTimers = true,
  }) : _repo = repository;

  final ProtocolRepository _repo;
  final bool enableTimers;

  ProtocolState? _state;
  ProtocolState? get state => _state;

  double? _livePrice;
  String? _liveSource;
  double? get activePrice => _livePrice ?? _state?.price;
  String get liveFeedLabel =>
      _liveSource != null ? 'Live $_liveSource' : 'Snapshot Price';

  bool _isLoading = false;
  bool get isLoading => _isLoading;

  String? _error;
  String? get error => _error;

  int _tabIndex = 0;
  int get tabIndex => _tabIndex;

  bool _videoExpanded = false;
  bool get videoExpanded => _videoExpanded;

  Timer? _liveTimer;
  Timer? _stateTimer;

  Future<void> initialize() async {
    await refreshAll();
    if (enableTimers) {
      _liveTimer = Timer.periodic(
        const Duration(seconds: 10),
        (_) => refreshLiveTicker(),
      );
      _stateTimer = Timer.periodic(
        const Duration(minutes: 2),
        (_) => refreshAll(),
      );
    }
  }

  void setTab(int idx) {
    if (_tabIndex == idx) return;
    _tabIndex = idx;
    notifyListeners();
  }

  void toggleVideoExpanded() {
    _videoExpanded = !_videoExpanded;
    notifyListeners();
  }

  Future<void> refreshAll() async {
    _isLoading = true;
    _error = null;
    notifyListeners();
    try {
      _state = await _repo.refreshState();
      await refreshLiveTicker(notify: false);
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> refreshLiveTicker({bool notify = true}) async {
    final tick = await _repo.refreshLivePrice();
    if (tick != null) {
      _livePrice = tick.price;
      _liveSource = tick.source;
      if (notify) notifyListeners();
    }
  }

  static CalcResult computeV4Sizing({
    required double equityUsd,
    required double spotInventoryBtc,
    required String direction,
    required bool weekendExtremeHalf,
    required bool ddTier1Active,
    required double entry,
    required double stop,
    required double target1,
  }) {
    var riskPct = ddTier1Active ? 0.002 : 0.004;
    if (weekendExtremeHalf) riskPct *= 0.5;

    final stopDist = (entry - stop).abs();
    final stopDistPct = entry > 0 ? (stopDist / entry) * 100.0 : 0.0;
    final validStopSide = direction == 'LONG' ? stop < entry : stop > entry;
    final validTpSide = direction == 'LONG' ? target1 > entry : target1 < entry;
    final rawRr =
        stopDist > 0 && validTpSide ? (target1 - entry).abs() / stopDist : 0.0;

    final targetRiskUsd = equityUsd * riskPct;
    final rawBtc = stopDist > 0 ? targetRiskUsd / stopDist : 0.0;
    final maxBtc = entry > 0 ? (equityUsd * 2.0) / entry : 0.0;
    final capped = rawBtc > maxBtc;
    final sizeBtc = math.min(rawBtc, maxBtc);
    final notional = sizeBtc * entry;
    final lev = equityUsd > 0 ? notional / equityUsd : 0.0;
    final actualRiskUsd = sizeBtc * stopDist;
    final actualRiskPct = equityUsd > 0 ? (actualRiskUsd / equityUsd) * 100.0 : 0.0;

    final issues = <String>[];
    if (entry <= 0 || stop <= 0 || target1 <= 0) {
      issues.add('Enter valid prices');
    } else {
      if (!validStopSide) issues.add('Stop on wrong side of entry');
      if (stopDistPct > 2.2) {
        issues.add('Stop ${stopDistPct.toStringAsFixed(2)}% > 2.20% max');
      }
      if (rawRr < 1.6) {
        issues.add('R:R ${rawRr.toStringAsFixed(2)}:1 < 1.60:1 min');
      }
    }

    final sell20Btc = spotInventoryBtc * 0.20;
    final sell20Usd = sell20Btc * entry;

    return CalcResult(
      valid: issues.isEmpty,
      issues: issues,
      riskPct: riskPct * 100.0,
      targetRiskUsd: targetRiskUsd,
      sizeBtc: sizeBtc,
      notionalUsd: notional,
      leverage: lev,
      leverageCapped: capped,
      actualRiskUsd: actualRiskUsd,
      actualRiskPct: actualRiskPct,
      stopDistPct: stopDistPct,
      rawRr: rawRr,
      sell20Btc: sell20Btc,
      sell20Usd: sell20Usd,
    );
  }

  @override
  void dispose() {
    _liveTimer?.cancel();
    _stateTimer?.cancel();
    super.dispose();
  }
}
