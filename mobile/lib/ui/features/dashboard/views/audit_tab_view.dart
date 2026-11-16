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
  bool _copied = false;
  int _copiedChars = 0;
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
      _copiedChars = jsonStr.length;
    });
    _timer = Timer(const Duration(seconds: 3), () {
      if (!mounted) return;
      setState(() {
        _copied = false;
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.vm.state;
    if (s == null) return const Center(child: CircularProgressIndicator());
    final tr = widget.vm.tr;

    return RefreshIndicator(
      onRefresh: widget.vm.refreshAll,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(10, 6, 10, 14),
        children: [
          IbmWindowCard(
            title: tr.t('raw_export_title'),
            child: Padding(
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
                      child: Text(
                        tr.t('raw_export_btn'),
                        style: const TextStyle(
                          fontSize: 9.5,
                          fontWeight: FontWeight.w700,
                          color: TerminalColors.text,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 5),
                  Text(
                    _copied ? tr.rawJsonCopied(_copiedChars) : tr.t('raw_export_helper'),
                    style: TextStyle(
                      fontSize: 9.5,
                      color: _copied ? TerminalColors.up : TerminalColors.muted,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),
          IbmWindowCard(
            title: tr.t('audit_log_title'),
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (s.auditLogRecent.isEmpty)
                    Text(
                      tr.t('audit_empty'),
                      style: const TextStyle(color: TerminalColors.muted, fontSize: 10),
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
                              style: const TextStyle(fontSize: 9.5, color: TerminalColors.text),
                            ),
                          ],
                        ),
                      ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),
          IbmWindowCard(
            title: tr.t('diag_title'),
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    s.fetchErrors.isEmpty
                        ? tr.t('diag_ok')
                        : '${tr.t('diag_notes')}: ${s.fetchErrors.join(" | ")}',
                    style: const TextStyle(fontSize: 9.5),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    tr.t('diag_disclaimer'),
                    style: const TextStyle(fontSize: 9.5, color: TerminalColors.muted),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${tr.t('diag_privacy')}: ${AppConfig.privacyPolicyUrl}',
                    style: const TextStyle(fontSize: 9.5, color: TerminalColors.accent),
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
