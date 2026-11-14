import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../../config/ad_config.dart';
import '../../../core/theme.dart';
import '../view_models/protocol_view_model.dart';

class AuditTabView extends StatefulWidget {
  const AuditTabView({super.key, required this.vm});

  final ProtocolViewModel vm;

  @override
  State<AuditTabView> createState() => _AuditTabViewState();
}

class _AuditTabViewState extends State<AuditTabView> {
  String _rawCopyMsg = 'Unopinionated raw JSON (OHLCV + derivatives + macro).';
  bool _copied = false;
  Timer? _timer;

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _copyRawJson() async {
    final jsonStr = widget.vm.buildCompactRawJson();
    await Clipboard.setData(ClipboardData(text: jsonStr));
    if (!mounted) return;
    _timer?.cancel();
    setState(() {
      _copied = true;
      _rawCopyMsg = 'Copied compact Raw JSON (${jsonStr.length} chars).';
    });
    _timer = Timer(const Duration(seconds: 3), () {
      if (!mounted) return;
      setState(() {
        _copied = false;
        _rawCopyMsg = 'Unopinionated raw JSON (OHLCV + derivatives + macro).';
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.vm.state;
    if (s == null) return const Center(child: CircularProgressIndicator());

    return RefreshIndicator(
      onRefresh: widget.vm.refreshAll,
      child: ListView(
        padding: const EdgeInsets.all(8),
        children: [
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const IbmSectionTitle('RAW TELEMETRY EXPORT'),
                Padding(
                  padding: const EdgeInsets.all(10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      InkWell(
                        onTap: _copyRawJson,
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
                          decoration: BoxDecoration(
                            color: TerminalColors.panelAlt,
                            border: Border.all(color: TerminalColors.borderDark),
                          ),
                          child: const Text(
                            '[COPY RAW JSON ONLY]',
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                              color: TerminalColors.text,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 5),
                      Text(
                        _rawCopyMsg,
                        style: TextStyle(
                          fontSize: 9.5,
                          color: _copied ? TerminalColors.up : TerminalColors.muted,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const IbmSectionTitle('SIGNAL & MANAGEMENT AUDIT LOG'),
                Padding(
                  padding: const EdgeInsets.all(10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (s.auditLogRecent.isEmpty)
                        const Text(
                          'No audit events recorded yet.',
                          style: TextStyle(color: TerminalColors.muted, fontSize: 10),
                        )
                      else
                        for (final item in s.auditLogRecent.take(25))
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 3),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '${item.event}  ·  ${item.ts}',
                                  style: const TextStyle(
                                    fontSize: 9.5,
                                    fontWeight: FontWeight.w700,
                                    color: TerminalColors.accent,
                                  ),
                                ),
                                Text(
                                  item.detail,
                                  style: const TextStyle(fontSize: 10, color: TerminalColors.text),
                                ),
                              ],
                            ),
                          ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const IbmSectionTitle('FEED DIAGNOSTICS & STORE NOTICE'),
                Padding(
                  padding: const EdgeInsets.all(10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        s.fetchErrors.isEmpty
                            ? 'All data feeds succeeded with zero errors.'
                            : 'Notes: ${s.fetchErrors.join(" | ")}',
                        style: const TextStyle(fontSize: 10),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'Disclaimer: Educational & paper-trading telemetry tool only. Not financial advice, brokerage execution, or investment solicitation.',
                        style: TextStyle(fontSize: 9.5, color: TerminalColors.muted),
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        'Privacy Policy: ${AppConfig.privacyPolicyUrl}',
                        style: TextStyle(fontSize: 9.5, color: TerminalColors.accent),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
