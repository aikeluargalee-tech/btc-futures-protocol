import 'package:flutter/material.dart';

import '../../../core/theme.dart';
import '../view_models/protocol_view_model.dart';

class AuditTabView extends StatelessWidget {
  const AuditTabView({super.key, required this.vm});

  final ProtocolViewModel vm;

  @override
  Widget build(BuildContext context) {
    final s = vm.state;
    if (s == null) return const Center(child: CircularProgressIndicator());

    return RefreshIndicator(
      onRefresh: vm.refreshAll,
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'SIGNAL & MANAGEMENT AUDIT LOG',
                    style: TextStyle(color: TerminalColors.muted, fontSize: 11, fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 8),
                  if (s.auditLogRecent.isEmpty)
                    const Text('No audit events recorded yet.', style: TextStyle(color: TerminalColors.muted, fontSize: 12))
                  else
                    for (final item in s.auditLogRecent.take(25))
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('${item.event}  •  ${item.ts}', style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: TerminalColors.accent)),
                            Text(item.detail, style: const TextStyle(fontSize: 12, color: TerminalColors.text)),
                          ],
                        ),
                      ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'FEED DIAGNOSTICS & STORE NOTICE',
                    style: TextStyle(color: TerminalColors.muted, fontSize: 11, fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    s.fetchErrors.isEmpty
                        ? 'All data feeds succeeded with zero errors.'
                        : 'Notes: ${s.fetchErrors.join(" | ")}',
                    style: const TextStyle(fontSize: 12),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Disclaimer: Educational & paper-trading telemetry tool only. Not financial advice, brokerage execution, or investment solicitation.',
                    style: TextStyle(fontSize: 11, color: TerminalColors.muted),
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
