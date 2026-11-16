import 'package:flutter/material.dart';

import '../../../core/theme.dart';
import '../view_models/protocol_view_model.dart';
import '../widgets/admob_widgets.dart';
import '../widgets/price_chart_card.dart';

class RegimeTabView extends StatelessWidget {
  const RegimeTabView({
    super.key,
    required this.vm,
    this.enablePlatformPlugins = true,
    this.loadBannerAd = false,
  });

  final ProtocolViewModel vm;
  final bool enablePlatformPlugins;
  final bool loadBannerAd;

  @override
  Widget build(BuildContext context) {
    final s = vm.state;
    if (s == null) return const Center(child: CircularProgressIndicator());

    final tr = vm.tr;
    final groups = s.regime.groups;
    final orderedKeys = [
      ('trend_structure', tr.t('grp_trend')),
      ('momentum', tr.t('grp_mom')),
      ('volatility_liquidity', tr.t('grp_vol')),
      ('session_context', tr.t('grp_session')),
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
            tr: tr,
          ),
          const SizedBox(height: 10),
          IbmWindowCard(
            title: tr.t('macro_title'),
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (s.macroCalendar.isEmpty)
                    Text(
                      tr.t('macro_empty'),
                      style: const TextStyle(color: TerminalColors.muted, fontSize: 10),
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
                              tr.inMinutes(ev.minutesAway.round()),
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
          const SizedBox(height: 10),
          AdMobBannerStrip(
            enablePlatformPlugins: enablePlatformPlugins,
            shouldLoad: loadBannerAd,
            tr: tr,
          ),
        ],
      ),
    );
  }
}
