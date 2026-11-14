import 'package:flutter/material.dart';

import '../../../core/theme.dart';
import '../view_models/protocol_view_model.dart';
import '../widgets/price_chart_card.dart';

class RegimeTabView extends StatelessWidget {
  const RegimeTabView({super.key, required this.vm});

  final ProtocolViewModel vm;

  @override
  Widget build(BuildContext context) {
    final s = vm.state;
    if (s == null) return const Center(child: CircularProgressIndicator());

    final groups = s.regime.groups;
    const orderedKeys = [
      ('trend_structure', '1. Trend Structure (30%)'),
      ('momentum', '2. Momentum 4H (25%)'),
      ('volatility_liquidity', '3. Vol & Liquidity 4H (25%)'),
      ('session_context', '4. Session / Context (20%)'),
    ];

    return RefreshIndicator(
      onRefresh: vm.refreshAll,
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          for (final (k, title) in orderedKeys) ...[
            if (groups[k] != null)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(title, style: const TextStyle(color: TerminalColors.muted, fontSize: 12, fontWeight: FontWeight.w700)),
                          Text(
                            '${groups[k]!.score.toStringAsFixed(1)} / 100',
                            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(groups[k]!.summary, style: const TextStyle(fontSize: 12)),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 10),
          ],
          PriceChartCard(
            charts: s.charts,
            levels: s.signal.structuralLevels,
            proposal: s.signal.proposal,
          ),
          const SizedBox(height: 10),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'SCHEDULED MACRO RELEASES (≤ 60m BLACKOUT)',
                    style: TextStyle(color: TerminalColors.muted, fontSize: 11, fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 6),
                  if (s.macroCalendar.isEmpty)
                    const Text('No USD High-Impact events inside the upcoming window.', style: TextStyle(color: TerminalColors.muted, fontSize: 12))
                  else
                    for (final ev in s.macroCalendar)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Expanded(child: Text(ev.title, style: const TextStyle(fontSize: 12))),
                            Text(
                              'in ${ev.minutesAway.round()}m',
                              style: TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.w700,
                                color: ev.minutesAway >= 0 && ev.minutesAway <= 60 ? TerminalColors.down : TerminalColors.muted,
                              ),
                            ),
                          ],
                        ),
                      ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
