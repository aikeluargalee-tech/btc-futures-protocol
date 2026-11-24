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
    final derivRaw = (s.rawState['derivatives'] as Map<String, dynamic>?) ?? const {};
    final cmc = (derivRaw['cmc_liquidations'] as Map<String, dynamic>?) ?? const {};
    final cmcCard = _buildCmcCard(cmc);
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
          if (cmcCard != null) ...[
            cmcCard,
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

  Widget? _buildCmcCard(Map<String, dynamic> cmc) {
    if (cmc.isEmpty) return null;
    final real = (cmc['realized'] as Map<String, dynamic>?) ?? const {};
    final fuel = (cmc['cumulative_fuel'] as Map<String, dynamic>?) ?? const {};
    final tacS = (cmc['tactical_short_clusters_within_8pct'] as List<dynamic>?) ?? const [];
    final tacL = (cmc['tactical_long_clusters_within_8pct'] as List<dynamic>?) ?? const [];
    final topS = tacS.isNotEmpty && tacS.first is Map<String, dynamic>
        ? tacS.first as Map<String, dynamic>
        : null;
    final topL = tacL.isNotEmpty && tacL.first is Map<String, dynamic>
        ? tacL.first as Map<String, dynamic>
        : null;

    Widget row(String k, String v) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(k, style: const TextStyle(color: TerminalColors.muted, fontSize: 9.5)),
              const SizedBox(width: 8),
              Flexible(
                child: Text(
                  v,
                  textAlign: TextAlign.right,
                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 9.5),
                ),
              ),
            ],
          ),
        );

    return IbmWindowCard(
      title: 'CMC LIQUIDATION CLUSTERS & 4H/24H FLUSH',
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (real['h4_total_usd_m'] != null)
              row(
                '4H Realized Liq',
                'L \$${real['h4_long_usd_m']}M / S \$${real['h4_short_usd_m']}M (${real['h4_long_flush_pct']}% L)',
              ),
            if (real['h24_total_usd_m'] != null)
              row(
                '24H Realized Liq',
                'L \$${real['h24_long_usd_m']}M / S \$${real['h24_short_usd_m']}M (\$${real['h24_total_usd_m']}M) · OI \$${real['global_btc_oi_usd_b']}B',
              ),
            if (topS != null)
              row(
                'Top Short Magnet (≤8%)',
                '\$${topS['price']} (\$${topS['usd_m']}M · ${topS['leverage']}x)',
              ),
            if (topL != null)
              row(
                'Top Long Magnet (≤8%)',
                '\$${topL['price']} (\$${topL['usd_m']}M · ${topL['leverage']}x)',
              ),
            if (fuel['shorts_within_2pct_usd_m'] != null)
              row(
                '±2% / ±5% Fuel',
                '2%: S \$${fuel['shorts_within_2pct_usd_m']}M vs L \$${fuel['longs_within_2pct_usd_m']}M · 5%: S \$${fuel['shorts_within_5pct_usd_m']}M vs L \$${fuel['longs_within_5pct_usd_m']}M',
              ),
          ],
        ),
      ),
    );
  }
}
