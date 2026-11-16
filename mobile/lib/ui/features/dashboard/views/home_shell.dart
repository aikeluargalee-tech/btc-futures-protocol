import 'package:flutter/material.dart';

import '../../../core/formatters.dart';
import '../../../core/theme.dart';
import '../view_models/protocol_view_model.dart';
import '../widgets/language_bar.dart';
import 'audit_tab_view.dart';
import 'ledger_tab_view.dart';
import 'regime_tab_view.dart';
import 'signal_tab_view.dart';

class HomeShell extends StatelessWidget {
  const HomeShell({
    super.key,
    required this.vm,
    this.enablePlatformPlugins = true,
  });

  final ProtocolViewModel vm;
  final bool enablePlatformPlugins;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: vm,
      builder: (context, _) {
        final s = vm.state;
        final age = vm.snapshotAgeLabel;
        final tr = vm.tr;
        final tabLabels = <String>[
          tr.t('tab_monitor'),
          tr.t('tab_regime'),
          tr.t('tab_calc'),
          tr.t('tab_audit'),
        ];
        final tabs = <Widget>[
          SignalTabView(vm: vm, enablePlatformPlugins: enablePlatformPlugins),
          RegimeTabView(
            vm: vm,
            enablePlatformPlugins: enablePlatformPlugins,
            loadBannerAd: vm.hasVisitedTab(1),
          ),
          LedgerTabView(vm: vm),
          AuditTabView(vm: vm),
        ];

        return Scaffold(
          backgroundColor: TerminalColors.bg,
          body: SafeArea(
            bottom: false,
            child: Column(
              children: [
                // Framed A1 Workstation Titlebar & Header Card
                Padding(
                  padding: const EdgeInsets.fromLTRB(10, 8, 10, 4),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      // Cobalt Workstation Bar with hard retro pixel shadow
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
                        decoration: BoxDecoration(
                          color: TerminalColors.accent,
                          border: Border.all(color: TerminalColors.borderDark),
                          boxShadow: const [
                            BoxShadow(
                              color: TerminalColors.shadow,
                              offset: Offset(3, 3),
                              blurRadius: 0,
                            ),
                          ],
                        ),
                        child: Wrap(
                          alignment: WrapAlignment.spaceBetween,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          spacing: 8,
                          runSpacing: 2,
                          children: [
                            const Text(
                              '■ QUANT-WORKSTATION // BTC-PROTOCOL REV 4.0',
                              style: TextStyle(
                                color: Colors.white,
                                fontSize: 9.5,
                                fontWeight: FontWeight.w700,
                                letterSpacing: 0.4,
                              ),
                            ),
                            Text(
                              tr.t('sys_banner'),
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 9.0,
                                fontWeight: FontWeight.w400,
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 6),
                      LanguageBar(
                        selected: vm.lang,
                        onSelected: vm.setLanguage,
                      ),
                      const SizedBox(height: 6),

                      // Framed Desk Header Window (zero ellipsis truncation)
                      IbmWindowCard(
                        child: Padding(
                          padding: const EdgeInsets.all(9),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  const Text(
                                    'BTC DESK v4',
                                    style: TextStyle(
                                      fontSize: 11.5,
                                      fontWeight: FontWeight.w700,
                                      letterSpacing: 0.4,
                                      color: TerminalColors.text,
                                    ),
                                  ),
                                  const SizedBox(width: 6),
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1.5),
                                    decoration: BoxDecoration(
                                      color: TerminalColors.panelAlt,
                                      border: Border.all(color: TerminalColors.borderDark),
                                    ),
                                    child: Text(
                                      tr.t('desk_badge'),
                                      style: const TextStyle(
                                        fontSize: 9,
                                        fontWeight: FontWeight.w700,
                                        color: TerminalColors.text,
                                      ),
                                    ),
                                  ),
                                  const Spacer(),
                                  InkWell(
                                    onTap: vm.isLoading ? null : vm.refreshAll,
                                    child: Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                                      decoration: BoxDecoration(
                                        color: TerminalColors.panelAlt,
                                        border: Border.all(color: TerminalColors.borderDark),
                                      ),
                                      child: vm.isLoading
                                          ? const SizedBox(
                                              width: 12,
                                              height: 12,
                                              child: CircularProgressIndicator(strokeWidth: 1.8),
                                            )
                                          : Row(
                                              mainAxisSize: MainAxisSize.min,
                                              children: [
                                                const Icon(Icons.refresh_sharp, size: 12, color: TerminalColors.text),
                                                const SizedBox(width: 3),
                                                Text(
                                                  tr.t('sync'),
                                                  style: const TextStyle(
                                                    fontSize: 8.5,
                                                    fontWeight: FontWeight.w700,
                                                    color: TerminalColors.text,
                                                  ),
                                                ),
                                              ],
                                            ),
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(
                                s != null
                                    ? '${tr.t('updated')} ${s.updatedAtUtc}${age != null ? " ($age)" : ""} · ${tr.t('close_4h')} ${s.last4hCloseUtc} · ${s.tickerSource}'
                                    : tr.t('connecting_feed'),
                                style: const TextStyle(fontSize: 9.0, color: TerminalColors.muted),
                              ),
                              const SizedBox(height: 6),

                              // Recessed A1-style live ticker bar
                              Container(
                                width: double.infinity,
                                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
                                decoration: BoxDecoration(
                                  color: TerminalColors.panelAlt,
                                  border: Border.all(color: TerminalColors.border),
                                ),
                                child: Wrap(
                                  alignment: WrapAlignment.spaceBetween,
                                  crossAxisAlignment: WrapCrossAlignment.center,
                                  spacing: 8,
                                  runSpacing: 3,
                                  children: [
                                    Row(
                                      mainAxisSize: MainAxisSize.min,
                                      children: [
                                        Container(
                                          width: 7,
                                          height: 7,
                                          color: vm.isLiveFeedFresh
                                              ? TerminalColors.up
                                              : (vm.isSnapshotStale
                                                  ? TerminalColors.warn
                                                  : TerminalColors.accent),
                                        ),
                                        const SizedBox(width: 6),
                                        Text(
                                          s != null
                                              ? vm.liveFeedDisplay
                                              : tr.t('connecting'),
                                          style: TextStyle(
                                            fontSize: 9.5,
                                            color: vm.isLiveFeedFresh
                                                ? TerminalColors.up
                                                : (vm.isSnapshotStale
                                                    ? TerminalColors.warn
                                                    : TerminalColors.muted),
                                            fontWeight: vm.isLiveFeedFresh ||
                                                    vm.isSnapshotStale
                                                ? FontWeight.w700
                                                : FontWeight.w400,
                                          ),
                                        ),
                                      ],
                                    ),
                                    Row(
                                      mainAxisSize: MainAxisSize.min,
                                      children: [
                                        Text(
                                          fmtUsd(vm.activePrice, decimals: 1),
                                          style: const TextStyle(
                                            fontSize: 12,
                                            fontWeight: FontWeight.w700,
                                            color: TerminalColors.text,
                                          ),
                                        ),
                                        if (s != null) ...[
                                          const SizedBox(width: 6),
                                          Text(
                                            '${fmtSignedPct(s.chg24Pct)} ${tr.t('chg_24h')}',
                                            style: TextStyle(
                                              fontSize: 9.5,
                                              fontWeight: FontWeight.w700,
                                              color: s.chg24Pct >= 0
                                                  ? TerminalColors.up
                                                  : TerminalColors.down,
                                            ),
                                          ),
                                        ],
                                      ],
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
                ),

                // Main Content Body
                Expanded(
                  child: vm.error != null && s == null
                      ? Center(
                          child: Padding(
                            padding: const EdgeInsets.all(20),
                            child: IbmWindowCard(
                              title: tr.t('conn_error'),
                              child: Padding(
                                padding: const EdgeInsets.all(14),
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Text(
                                      vm.error!,
                                      textAlign: TextAlign.center,
                                      style: const TextStyle(
                                        color: TerminalColors.down,
                                        fontSize: 10.5,
                                      ),
                                    ),
                                    const SizedBox(height: 10),
                                    OutlinedButton(
                                      onPressed: vm.refreshAll,
                                      style: OutlinedButton.styleFrom(
                                        shape: const RoundedRectangleBorder(
                                          borderRadius: BorderRadius.zero,
                                        ),
                                        side: const BorderSide(
                                          color: TerminalColors.borderDark,
                                        ),
                                      ),
                                      child: Text(
                                        tr.t('retry_sync'),
                                        style: const TextStyle(fontSize: 10.5),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                        )
                      : IndexedStack(index: vm.tabIndex, children: tabs),
                ),
              ],
            ),
          ),

          // Clean Unobstructed F1–F4 Navigation Bar (AdMob moved out to scrollable feed)
          bottomNavigationBar: SafeArea(
            top: false,
            child: Container(
              decoration: const BoxDecoration(
                color: TerminalColors.panel,
                border: Border(
                  top: BorderSide(color: TerminalColors.borderDark),
                ),
              ),
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              child: Row(
                children: List.generate(tabLabels.length, (i) {
                  final active = vm.tabIndex == i;
                  return Expanded(
                    child: Padding(
                      padding: EdgeInsets.only(right: i < tabLabels.length - 1 ? 5 : 0),
                      child: InkWell(
                        onTap: () => vm.setTab(i),
                        child: Container(
                          padding: const EdgeInsets.symmetric(vertical: 7),
                          decoration: BoxDecoration(
                            color: active ? TerminalColors.accent : TerminalColors.panelAlt,
                            border: Border.all(
                              color: active
                                  ? TerminalColors.borderDark
                                  : TerminalColors.border,
                            ),
                          ),
                          child: Center(
                            heightFactor: 1.0,
                            child: Text(
                              tabLabels[i],
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 9.5,
                                fontWeight: FontWeight.w700,
                                color: active ? Colors.white : TerminalColors.text,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  );
                }),
              ),
            ),
          ),
        );
      },
    );
  }
}
