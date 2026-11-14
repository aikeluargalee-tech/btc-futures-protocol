import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:btc_futures_protocol/data/repositories/protocol_repository.dart';
import 'package:btc_futures_protocol/data/services/protocol_api_service.dart';
import 'package:btc_futures_protocol/domain/models/protocol_state.dart';
import 'package:btc_futures_protocol/main.dart';
import 'package:btc_futures_protocol/ui/features/dashboard/view_models/protocol_view_model.dart';

const String _sampleStateJson = '''
{
  "protocol_version": "4.0",
  "protocol_name": "BTC Short-Term Futures + Inventory Protocol",
  "updated_at_utc": "2026-11-14T05:00:00Z",
  "last_4h_close_utc": "2026-11-14T04:00:00Z",
  "ticker": {"price": 67000.0, "chg24_pct": -1.5, "source": "OKX"},
  "derivatives": {"current_rate_pct": 0.005, "oi_btc": 33000},
  "extras": {},
  "charts": {
    "h4": [[1700000000000, 66500, 67500, 66200, 67000], [1700014400000, 67000, 67400, 66800, 67100]],
    "d1": [[1700000000000, 65000, 68000, 64500, 67000], [1700086400000, 67000, 67600, 66500, 67100]]
  },
  "macro_calendar": [],
  "regime": {
    "score": 31.5,
    "bias": "SHORT",
    "daily_bias": "BEAR",
    "thresholds": {"long": 68, "short": 32, "dd_tier1_active": false},
    "is_weekend_utc": false,
    "dominant_factors": ["Trend Structure (18.0)"],
    "groups": {
      "trend_structure": {"weight": 0.30, "score": 18.0, "summary": "4H=BEAR, 1D=BEAR"},
      "momentum": {"weight": 0.25, "score": 25.0, "summary": "RSI4H=32.0"},
      "volatility_liquidity": {"weight": 0.25, "score": 40.0, "summary": "ATRp=55"},
      "session_context": {"weight": 0.20, "score": 42.0, "summary": "ASIA_OFFHOURS"}
    }
  },
  "signal": {
    "status": "FLAT",
    "active_signals": ["SELL_INVENTORY"],
    "checklist": [
      {"id": 1, "rule": "Regime Score Meets Threshold", "passed": true, "detail": "Score 31.5 <= 32"}
    ],
    "rejection_reasons": ["No 4H SHORT confirmation"],
    "proposal": {
      "direction": "SHORT",
      "entry_method": "LIMIT_AT_LEVEL",
      "entry_price": 67100.0,
      "stop_price": 68100.0,
      "target1_price": 65000.0,
      "target1_label": "Prior 1D Low",
      "raw_rr": 2.1,
      "funding_adjusted_rr": 2.1,
      "size_btc": 0.4,
      "notional_usd": 26840.0,
      "leverage": 0.27,
      "leverage_capped": false,
      "actual_risk_pct": 0.4,
      "actual_risk_usd": 400.0,
      "stop_distance_pct": 1.49,
      "weekend_halved": false
    },
    "sell_inventory": {
      "active": true,
      "recommended_pct": 20.0,
      "band_pct": "15-25%",
      "spot_inventory_btc": 2.0,
      "sell_btc": 0.4,
      "sell_usd": 26800.0,
      "structural_ref": "Prior 4H High @ 67,200.0",
      "reason": "Score 31.5 <= 32 - reduce 20% spot inventory"
    },
    "structural_levels": []
  },
  "portfolio": {
    "equity_usd": 100000.0,
    "high_water_mark_usd": 100000.0,
    "spot_inventory_btc": 2.0,
    "drawdown_pct": 0.0,
    "intraday_pnl_pct": 0.0,
    "daily_pnl_pct": 0.0,
    "weekly_pnl_pct": 0.0,
    "open_heat_pct": 0.0,
    "max_heat_pct": 1.5,
    "current_leverage": 0.0,
    "max_leverage": 2.0,
    "circuit_breakers": {
      "intraday_halted": false,
      "daily_halted": false,
      "weekly_halted": false,
      "dd_tier1_active": false,
      "dd_tier2_locked": false
    },
    "open_positions": [],
    "closed_trades": [],
    "review": {"total_closed_legs": 0, "win_rate_pct": 0.0, "profit_factor": 0.0, "expectancy_r": 0.0, "total_realized_pnl_usd": 0.0}
  },
  "audit_log_recent": [
    {"ts": "2026-11-14T04:00:00Z", "event": "SELL_INVENTORY_SIGNAL", "detail": "Trim 20% spot"}
  ],
  "config": {},
  "fetch_errors": []
}
''';

void main() {
  test('ProtocolState parses v4.0 JSON and sizing enforces 0.4% risk & 2x cap', () {
    final parsed = parseProtocolState(_sampleStateJson);
    expect(parsed.protocolVersion, '4.0');
    expect(parsed.regime.score, 31.5);
    expect(parsed.signal.sellInventory.active, isTrue);
    expect(parsed.signal.sellInventory.sellBtc, 0.4);

    final sizing = ProtocolViewModel.computeV4Sizing(
      equityUsd: 100000,
      spotInventoryBtc: 2.0,
      direction: 'LONG',
      weekendExtremeHalf: false,
      ddTier1Active: false,
      entry: 100000,
      stop: 99900,
      target1: 100400,
    );
    expect(sizing.valid, isTrue);
    expect(sizing.leverageCapped, isTrue);
    expect(sizing.sizeBtc, closeTo(2.0, 0.0001));
    expect(sizing.sell20Btc, closeTo(0.4, 0.0001));
  });

  testWidgets('HomeShell renders Signal Tab, expandable video card, Native & Banner slots', (tester) async {
    final mockClient = MockClient((req) async {
      if (req.url.toString().contains('state.json')) {
        return http.Response(_sampleStateJson, 200);
      }
      return http.Response('{"price":"67050.0"}', 200);
    });
    final repo = ProtocolRepository(
      apiService: ProtocolApiService(client: mockClient, parseInBackground: false),
    );
    final vm = ProtocolViewModel(repository: repo, enableTimers: false);
    await vm.refreshAll();

    await tester.pumpWidget(
      BtcProtocolApp(viewModel: vm, enablePlatformPlugins: false),
    );
    await tester.pump();

    expect(find.text('BTC PROTOCOL v4.0'), findsOneWidget);
    expect(find.text('PROTOCOL BRIEFING VIDEO (vGUZF.mp4)'), findsOneWidget);
    expect(find.text('AdMob Banner Slot (320x50 · Test Mode)'), findsOneWidget);
    expect(find.text('AdMob Native Advanced Ad Slot (Medium Template · Test Mode)'), findsOneWidget);

    await tester.tap(find.text('PROTOCOL BRIEFING VIDEO (vGUZF.mp4)'));
    await tester.pump();
    expect(find.text('Video Briefing Player Ready (vGUZF.mp4)'), findsOneWidget);
  });
}
