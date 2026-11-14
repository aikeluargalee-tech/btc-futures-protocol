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

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: vm,
      builder: (context, _) {
        final s = vm.state;
        final tabs = <Widget>[
          SignalTabView(vm: vm, enablePlatformPlugins: enablePlatformPlugins),
          RegimeTabView(vm: vm),
          LedgerTabView(vm: vm),
          AuditTabView(vm: vm),
        ];

        return Scaffold(
          appBar: AppBar(
            backgroundColor: TerminalColors.panel,
            surfaceTintColor: Colors.transparent,
            title: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'BTC PROTOCOL v4.0',
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, letterSpacing: 0.6),
                ),
                Text(
                  s != null
                      ? '${vm.liveFeedLabel} · 4H Close ${s.last4hCloseUtc}'
                      : 'Connecting…',
                  style: const TextStyle(fontSize: 11, color: TerminalColors.muted),
                ),
              ],
            ),
            actions: [
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: Center(
                  child: Text(
                    fmtUsd(vm.activePrice, decimals: 1),
                    style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: TerminalColors.accent),
                  ),
                ),
              ),
              IconButton(
                icon: vm.isLoading
                    ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.refresh_rounded),
                onPressed: vm.isLoading ? null : vm.refreshAll,
              ),
            ],
          ),
          body: vm.error != null && s == null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(vm.error!, textAlign: TextAlign.center, style: const TextStyle(color: TerminalColors.down)),
                        const SizedBox(height: 12),
                        FilledButton(onPressed: vm.refreshAll, child: const Text('Retry')),
                      ],
                    ),
                  ),
                )
              : IndexedStack(index: vm.tabIndex, children: tabs),
          bottomNavigationBar: SafeArea(
            top: false,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                AdMobBannerStrip(enablePlatformPlugins: enablePlatformPlugins),
                NavigationBar(
                  backgroundColor: TerminalColors.panel,
                  indicatorColor: TerminalColors.accent.withValues(alpha: 0.18),
                  selectedIndex: vm.tabIndex,
                  onDestinationSelected: vm.setTab,
                  destinations: const [
                    NavigationDestination(icon: Icon(Icons.bolt_rounded), label: 'Signal'),
                    NavigationDestination(icon: Icon(Icons.analytics_outlined), label: '4H Regime'),
                    NavigationDestination(icon: Icon(Icons.calculate_outlined), label: 'Risk & Calc'),
                    NavigationDestination(icon: Icon(Icons.receipt_long_outlined), label: 'Audit'),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
