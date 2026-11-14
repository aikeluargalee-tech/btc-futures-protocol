import 'package:flutter/material.dart';

import '../../../core/formatters.dart';
import '../../../core/theme.dart';
import '../view_models/protocol_view_model.dart';
import '../widgets/admob_widgets.dart';
import '../widgets/protocol_video_card.dart';

class SignalTabView extends StatelessWidget {
  const SignalTabView({
    super.key,
    required this.vm,
    this.enablePlatformPlugins = true,
  });

  final ProtocolViewModel vm;
  final bool enablePlatformPlugins;

  @override
  Widget build(BuildContext context) {
    final s = vm.state;
    if (s == null) {
      return const Center(child: CircularProgressIndicator());
    }

    final sig = s.signal;
    final reg = s.regime;
    final port = s.portfolio;
    final inv = sig.sellInventory;
    final prop = sig.proposal;

    final statusColor = sig.status == 'LONG'
        ? TerminalColors.up
        : (sig.status == 'SHORT' || inv.active)
            ? TerminalColors.down
            : TerminalColors.warn;

    return RefreshIndicator(
      onRefresh: vm.refreshAll,
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          // 1. Collapsible Protocol Briefing Video Card (vGUZF.mp4)
          ProtocolVideoCard(
            expanded: vm.videoExpanded,
            onToggleExpanded: vm.toggleVideoExpanded,
            enablePlatformPlugins: enablePlatformPlugins,
          ),
          const SizedBox(height: 10),

          // 2. Active Signal & 4H Regime Score Cards
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'ACTIVE PROTOCOL ACTION (v4.0)',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: TerminalColors.muted,
                      letterSpacing: 0.6,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Flexible(
                        child: Text(
                          sig.activeSignals.join(' + '),
                          style: TextStyle(
                            fontSize: 22,
                            fontWeight: FontWeight.w800,
                            color: statusColor,
                          ),
                        ),
                      ),
                      _Pill(
                        label: sig.status == 'FLAT'
                            ? (inv.active ? 'INVENTORY TRIM' : 'NO FUTURES')
                            : (prop?.entryMethod ?? 'ACTIVE'),
                        color: statusColor,
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    '1D Bias: ${reg.dailyBias}  •  Open Futures: ${port.openPositions.length}/1  •  Eq: ${fmtUsd(port.equityUsd, decimals: 2)}',
                    style: const TextStyle(color: TerminalColors.muted, fontSize: 12),
                  ),
                  if (reg.dominantFactors.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      'Drivers: ${reg.dominantFactors.join(" · ")}',
                      style: const TextStyle(color: TerminalColors.text, fontSize: 12),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),

          // 3. 4H Regime Score Gauge Card
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        '${reg.score.toStringAsFixed(1)} / 100',
                        style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
                      ),
                      _Pill(
                        label: reg.bias,
                        color: reg.bias == 'LONG'
                            ? TerminalColors.up
                            : reg.bias == 'SHORT'
                                ? TerminalColors.down
                                : TerminalColors.warn,
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(999),
                    child: LinearProgressIndicator(
                      value: (reg.score / 100.0).clamp(0.0, 1.0),
                      minHeight: 8,
                      backgroundColor: TerminalColors.panelAlt,
                      valueColor: AlwaysStoppedAnimation(
                        reg.bias == 'LONG'
                            ? TerminalColors.up
                            : reg.bias == 'SHORT'
                                ? TerminalColors.down
                                : TerminalColors.accent,
                      ),
                    ),
                  ),
                  const SizedBox(height: 6),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text('Short ≤ ${reg.shortThreshold.toInt()}', style: const TextStyle(fontSize: 11, color: TerminalColors.muted)),
                      Text('Flat ${reg.shortThreshold.toInt() + 1}–${reg.longThreshold.toInt() - 1}', style: const TextStyle(fontSize: 11, color: TerminalColors.muted)),
                      Text('Long ≥ ${reg.longThreshold.toInt()}', style: const TextStyle(fontSize: 11, color: TerminalColors.muted)),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),

          // 4. Inline Google AdMob Native Advanced Ad Card
          AdMobNativeAdCard(enablePlatformPlugins: enablePlatformPlugins),
          const SizedBox(height: 10),

          // 5. Sell Inventory Card
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        inv.active ? 'SELL INVENTORY ACTIVE' : 'HOLD SPOT INVENTORY',
                        style: TextStyle(
                          fontWeight: FontWeight.w700,
                          color: inv.active ? TerminalColors.down : TerminalColors.muted,
                        ),
                      ),
                      _Pill(
                        label: inv.active
                            ? '${inv.recommendedPct.toInt()}% (${inv.sellBtc} BTC)'
                            : inv.bandPct,
                        color: inv.active ? TerminalColors.down : TerminalColors.muted,
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(inv.reason, style: const TextStyle(fontSize: 12, color: TerminalColors.text)),
                  const SizedBox(height: 4),
                  Text(
                    'Ref: ${inv.structuralRef}  •  Spot Held: ${inv.spotInventoryBtc.toStringAsFixed(2)} BTC  •  0% Futures Heat',
                    style: const TextStyle(fontSize: 11, color: TerminalColors.muted),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),

          // 6. 9-Point Checklist Card
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '9-POINT FUTURES QUALIFICATION CHECKLIST',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: TerminalColors.muted,
                      letterSpacing: 0.6,
                    ),
                  ),
                  const SizedBox(height: 8),
                  for (final item in sig.checklist)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 5),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('${item.id}. ${item.rule}', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                                Text(item.detail, style: const TextStyle(color: TerminalColors.muted, fontSize: 11)),
                              ],
                            ),
                          ),
                          const SizedBox(width: 8),
                          _Pill(
                            label: item.passed ? 'PASS' : 'FAIL',
                            color: item.passed ? TerminalColors.up : TerminalColors.down,
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),

          // 7. Sizing & 5-Tier Circuit Breakers Card
          if (prop != null && prop.entryPrice > 0)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'PROPOSED SIZING & 5-TIER BREAKERS',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: TerminalColors.muted,
                        letterSpacing: 0.6,
                      ),
                    ),
                    const SizedBox(height: 8),
                    _kv('Direction / Entry', '${prop.direction} @ ${fmtUsd(prop.entryPrice, decimals: 1)}'),
                    _kv('Hard Stop', '${fmtUsd(prop.stopPrice, decimals: 1)} (${prop.stopDistancePct.toStringAsFixed(2)}% ≤ 2.2%)'),
                    _kv('Target 1 (45% @ 1.5R)', '${fmtUsd(prop.target1Price, decimals: 1)} (${prop.target1Label})'),
                    _kv('R:R (Raw / Adj)', '${prop.rawRr.toStringAsFixed(2)}:1 / ${prop.fundingAdjustedRr.toStringAsFixed(2)}:1'),
                    _kv('Size / Leverage', '${prop.sizeBtc} BTC (${prop.leverage.toStringAsFixed(2)}x / 2.00x)'),
                    _kv('Open Heat / Max', '${port.openHeatPct.toStringAsFixed(2)}% / ${port.maxHeatPct.toStringAsFixed(1)}%'),
                    _kv('Intraday / Daily / Wk', '${fmtSignedPct(port.intradayPnlPct)} / ${fmtSignedPct(port.dailyPnlPct)} / ${fmtSignedPct(port.weeklyPnlPct)}'),
                    _kv(
                      'Breakers',
                      port.breakers.activeLabels.isEmpty
                          ? 'ALL CLEAR (-1.2 / -2 / -4 / -6 / -10%)'
                          : port.breakers.activeLabels.join(', '),
                    ),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 12),
        ],
      ),
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(k, style: const TextStyle(color: TerminalColors.muted, fontSize: 12)),
            const SizedBox(width: 8),
            Flexible(
              child: Text(
                v,
                textAlign: TextAlign.right,
                style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12),
              ),
            ),
          ],
        ),
      );
}

class _Pill extends StatelessWidget {
  const _Pill({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.6)),
        color: color.withValues(alpha: 0.12),
      ),
      child: Text(
        label,
        style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: color),
      ),
    );
  }
}
