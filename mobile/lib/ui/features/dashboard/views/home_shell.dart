import 'package:flutter/material.dart';

import '../../../core/formatters.dart';
import '../../../core/theme.dart';
import '../view_models/protocol_view_model.dart';
import '../widgets/admob_widgets.dart';
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

  static const _tabLabels = <String>[
    'F1 SIGNAL',
    'F2 REGIME',
    'F3 CALC',
    'F4 AUDIT',
  ];

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: vm,
      builder: (context, _) {
        final s = vm.state;
        final age = vm.snapshotAgeLabel;
        final tabs = <Widget>[
          SignalTabView(vm: vm, enablePlatformPlugins: enablePlatformPlugins),
          RegimeTabView(vm: vm),
          LedgerTabView(vm: vm),
          AuditTabView(vm: vm),
        ];

        return Scaffold(
          body: SafeArea(
            bottom: false,
            child: Column(
              children: [
                // IBM Workstation Titlebar
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: const BoxDecoration(
                    color: TerminalColors.accent,
                    border: Border(
                      bottom: BorderSide(color: TerminalColors.borderDark),
                    ),
                  ),
                  child: const Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Flexible(
                        child: Text(
                          '■ QUANT-WORKSTATION // BTC-PROTOCOL REV 4.0',
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 9.5,
                            fontWeight: FontWeight.w700,
                            letterSpacing: 0.5,
                          ),
                        ),
                      ),
                      Text(
                        '4H · MAX 1:2',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 9.5,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ),
                ),

                // Top Header Strip
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
                  decoration: const BoxDecoration(
                    color: TerminalColors.panel,
                    border: Border(
                      bottom: BorderSide(color: TerminalColors.borderDark),
                    ),
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'BTC PROTOCOL v4.0',
                              style: TextStyle(
                                fontSize: 11.5,
                                fontWeight: FontWeight.w700,
                                letterSpacing: 0.4,
                                color: TerminalColors.text,
                              ),
                            ),
                            Text(
                              s != null
                                  ? '${vm.liveFeedLabel}${age != null ? " · $age" : ""} · 4H ${s.last4hCloseUtc}'
                                  : 'Connecting…',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 9.5,
                                color: vm.isSnapshotStale
                                    ? TerminalColors.down
                                    : TerminalColors.muted,
                              ),
                            ),
                          ],
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
                        decoration: BoxDecoration(
                          color: TerminalColors.panelAlt,
                          border: Border.all(color: TerminalColors.border),
                        ),
                        child: Text(
                          fmtUsd(vm.activePrice, decimals: 1),
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                            color: TerminalColors.text,
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      InkWell(
                        onTap: vm.isLoading ? null : vm.refreshAll,
                        child: Container(
                          padding: const EdgeInsets.all(5),
                          decoration: BoxDecoration(
                            color: TerminalColors.panelAlt,
                            border: Border.all(color: TerminalColors.borderDark),
                          ),
                          child: vm.isLoading
                              ? const SizedBox(
                                  width: 14,
                                  height: 14,
                                  child: CircularProgressIndicator(strokeWidth: 1.8),
                                )
                              : const Icon(
                                  Icons.refresh_sharp,
                                  size: 14,
                                  color: TerminalColors.text,
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
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Text(
                                  vm.error!,
                                  textAlign: TextAlign.center,
                                  style: const TextStyle(
                                    color: TerminalColors.down,
                                    fontSize: 11,
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
                                  child: const Text(
                                    '[RETRY]',
                                    style: TextStyle(fontSize: 11),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        )
                      : IndexedStack(index: vm.tabIndex, children: tabs),
                ),
              ],
            ),
          ),
          bottomNavigationBar: SafeArea(
            top: false,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                AdMobBannerStrip(enablePlatformPlugins: enablePlatformPlugins),
                Container(
                  decoration: const BoxDecoration(
                    color: TerminalColors.panel,
                    border: Border(
                      top: BorderSide(color: TerminalColors.borderDark),
                    ),
                  ),
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 5),
                  child: Row(
                    children: List.generate(_tabLabels.length, (i) {
                      final active = vm.tabIndex == i;
                      return Expanded(
                        child: Padding(
                          padding: EdgeInsets.only(right: i < _tabLabels.length - 1 ? 4 : 0),
                          child: InkWell(
                            onTap: () => vm.setTab(i),
                            child: Container(
                              padding: const EdgeInsets.symmetric(vertical: 7),
                              alignment: Alignment.center,
                              decoration: BoxDecoration(
                                color: active ? TerminalColors.accent : TerminalColors.panelAlt,
                                border: Border.all(
                                  color: active
                                      ? TerminalColors.borderDark
                                      : TerminalColors.border,
                                ),
                              ),
                              child: Text(
                                _tabLabels[i],
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
                      );
                    }),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
