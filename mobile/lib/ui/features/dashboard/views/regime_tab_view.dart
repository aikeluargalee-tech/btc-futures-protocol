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
      ('trend_structure', '1. TREND STRUCTURE (30%)'),
      ('momentum', '2. MOMENTUM 4H (25%)'),
      ('volatility_liquidity', '3. VOL & LIQUIDITY 4H (25%)'),
      ('session_context', '4. SESSION / CONTEXT (20%)'),
    ];

    return RefreshIndicator(
      onRefresh: vm.refreshAll,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(10, 6, 10, 14),
        children: [
          for (final (k, title) in orderedKeys)
            if (groups[k] != null) ...[
              IbmWindowCard(
                title: title,
                child: Padding(
                  padding: const EdgeInsets.all(10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${groups[k]!.score.toStringAsFixed(1)} / 100',
                        style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(height: 3),
                      Text(groups[k]!.summary, style: const TextStyle(fontSize: 10)),
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
          IbmWindowCard(
            title: 'SCHEDULED MACRO RELEASES (≤ 60M BLACKOUT)',
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (s.macroCalendar.isEmpty)
                    const Text(
                      'No USD High-Impact events inside the upcoming window.',
                      style: TextStyle(color: TerminalColors.muted, fontSize: 10),
                    )
                  else
                    for (final ev in s.macroCalendar)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 3),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Expanded(
                              child: Text(ev.title, style: const TextStyle(fontSize: 10)),
                            ),
                            Text(
                              'in ${ev.minutesAway.round()}m',
                              style: TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.w700,
                                color: ev.minutesAway >= 0 && ev.minutesAway <= 60
                                    ? TerminalColors.down
                                    : TerminalColors.muted,
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
