import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/formatters.dart';
import '../../../core/theme.dart';
import '../view_models/protocol_view_model.dart';
import '../widgets/admob_widgets.dart';
import '../widgets/protocol_video_card.dart';

class SignalTabView extends StatelessWidget {
  const SignalTabView({
    super.key,
    required this.vm,
    this.enablePlatformPlugins = true,
  });

  final ProtocolViewModel vm;
  final bool enablePlatformPlugins;

  @override
  Widget build(BuildContext context) {
    final s = vm.state;
    if (s == null) {
      return const Center(child: CircularProgressIndicator());
    }

    final sig = s.signal;
    final reg = s.regime;
    final port = s.portfolio;
    final prop = sig.proposal;

    final statusColor = sig.status == 'LONG'
        ? TerminalColors.up
        : sig.status == 'SHORT'
            ? TerminalColors.down
            : TerminalColors.warn;

    return RefreshIndicator(
      onRefresh: vm.refreshAll,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(10, 6, 10, 14),
        children: [
          // 0. Compact Collapsible Purpose Card (Spot & Futures Scope)
          _PurposeOverviewCard(vm: vm),
          const SizedBox(height: 10),

          // 1. STANDOUT HERO SECTION: AI Analysis Engine (Core Workflow)
          _AiCopilotHeroCard(vm: vm),
          const SizedBox(height: 10),

          // 2. Model Regime Status Window
          IbmWindowCard(
            title: 'MODEL REGIME STATUS',
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Flexible(
                        child: Text(
                          sig.status == 'FLAT' ? 'STANDBY (NEUTRAL)' : sig.status,
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                            color: statusColor,
                          ),
                        ),
                      ),
                      IbmBadge(
                        label: sig.status == 'FLAT'
                            ? 'CONDITIONS UNMET'
                            : (prop?.entryMethod ?? 'ACTIVE'),
                        color: statusColor,
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    '1D Bias: ${reg.dailyBias}  ·  Paper Pos: ${port.openPositions.length}/1  ·  Sim Eq: ${fmtUsd(port.equityUsd, decimals: 2)}',
                    style: const TextStyle(color: TerminalColors.muted, fontSize: 10),
                  ),
                  if (reg.dominantFactors.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      'Drivers: ${reg.dominantFactors.join(" · ")}',
                      style: const TextStyle(color: TerminalColors.text, fontSize: 10),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),

          // 3. 4H Multi-Factor Regime Score Gauge Window
          IbmWindowCard(
            title: '4H MULTI-FACTOR REGIME SCORE (0-100)',
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        '${reg.score.toStringAsFixed(1)} / 100',
                        style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
                      ),
                      IbmBadge(
                        label: reg.bias,
                        color: reg.bias == 'LONG'
                            ? TerminalColors.up
                            : reg.bias == 'SHORT'
                                ? TerminalColors.down
                                : TerminalColors.warn,
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Container(
                    decoration: BoxDecoration(
                      border: Border.all(color: TerminalColors.borderDark),
                    ),
                    child: LinearProgressIndicator(
                      value: (reg.score / 100.0).clamp(0.0, 1.0),
                      minHeight: 7,
                      backgroundColor: TerminalColors.panelAlt,
                      valueColor: AlwaysStoppedAnimation(
                        reg.bias == 'LONG'
                            ? TerminalColors.up
                            : reg.bias == 'SHORT'
                                ? TerminalColors.down
                                : TerminalColors.accent,
                      ),
                    ),
                  ),
                  const SizedBox(height: 5),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        'Short ≤ ${reg.shortThreshold.toInt()}',
                        style: const TextStyle(fontSize: 9.5, color: TerminalColors.muted),
                      ),
                      Text(
                        'Flat ${reg.shortThreshold.toInt() + 1}–${reg.longThreshold.toInt() - 1}',
                        style: const TextStyle(fontSize: 9.5, color: TerminalColors.muted),
                      ),
                      Text(
                        'Long ≥ ${reg.longThreshold.toInt()}',
                        style: const TextStyle(fontSize: 9.5, color: TerminalColors.muted),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),

          // 4. 9-Point Checklist Window
          IbmWindowCard(
            title: '9-POINT MODEL REGIME CHECKLIST',
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (final item in sig.checklist)
                    Container(
                      padding: const EdgeInsets.symmetric(vertical: 5),
                      decoration: const BoxDecoration(
                        border: Border(bottom: BorderSide(color: TerminalColors.panelAlt)),
                      ),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '${item.id}. ${item.rule}',
                                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 10),
                                ),
                                Text(
                                  item.detail,
                                  style: const TextStyle(color: TerminalColors.muted, fontSize: 9.5),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(width: 6),
                          IbmBadge(
                            label: item.passed ? 'PASS' : 'FAIL',
                            color: item.passed ? TerminalColors.up : TerminalColors.down,
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),

          // 5. Sizing & 5-Tier Circuit Breakers Window
          if (prop != null && prop.entryPrice > 0) ...[
            IbmWindowCard(
              title: 'MODEL RISK SIZING (SIMULATION) & BREAKERS',
              child: Padding(
                padding: const EdgeInsets.all(10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _kv('Scenario / Reference', '${prop.direction} @ ${fmtUsd(prop.entryPrice, decimals: 1)}'),
                    _kv('Invalidation Ref', '${fmtUsd(prop.stopPrice, decimals: 1)} (${prop.stopDistancePct.toStringAsFixed(2)}% ≤ 2.2%)'),
                    _kv('Target 1 (45% @ 1.5R)', '${fmtUsd(prop.target1Price, decimals: 1)} (${prop.target1Label})'),
                    _kv('R:R (Raw / Adj)', '${prop.rawRr.toStringAsFixed(2)}:1 / ${prop.fundingAdjustedRr.toStringAsFixed(2)}:1'),
                    _kv('Sim Size / Ratio', '${prop.sizeBtc} BTC (${prop.leverage.toStringAsFixed(2)}x / 2.00x)'),
                    _kv('Open Heat / Max', '${port.openHeatPct.toStringAsFixed(2)}% / ${port.maxHeatPct.toStringAsFixed(1)}%'),
                    _kv('Intraday / Daily / Wk', '${fmtSignedPct(port.intradayPnlPct)} / ${fmtSignedPct(port.dailyPnlPct)} / ${fmtSignedPct(port.weeklyPnlPct)}'),
                    _kv(
                      'Breakers',
                      port.breakers.activeLabels.isEmpty
                          ? 'ALL CLEAR (-1.2 / -2 / -4 / -6 / -10%)'
                          : port.breakers.activeLabels.join(', '),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 10),
          ],

          // 6. Collapsible Protocol Briefing Video Card (vGUZF.mp4)
          ProtocolVideoCard(
            expanded: vm.videoExpanded,
            onToggleExpanded: vm.toggleVideoExpanded,
            enablePlatformPlugins: enablePlatformPlugins,
          ),
          const SizedBox(height: 10),

          // 7. Non-intrusive Native + Banner Ads placed cleanly at bottom of scroll feed
          AdMobNativeAdCard(enablePlatformPlugins: enablePlatformPlugins),
          const SizedBox(height: 10),
          AdMobBannerStrip(enablePlatformPlugins: enablePlatformPlugins),
        ],
      ),
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2.5),
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
}

/// Compact collapsible Purpose card clarifying read-only research scope & paper simulation framing.
class _PurposeOverviewCard extends StatelessWidget {
  const _PurposeOverviewCard({required this.vm});

  final ProtocolViewModel vm;

  @override
  Widget build(BuildContext context) {
    final expanded = vm.purposeExpanded;
    return IbmWindowCard(
      title: 'PURPOSE // READ-ONLY TELEMETRY & RESEARCH DESK',
      trailing: InkWell(
        onTap: vm.togglePurposeExpanded,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(
            color: TerminalColors.panel,
            border: Border.all(color: TerminalColors.borderDark),
          ),
          child: Text(
            expanded ? '[HIDE]' : '[SHOW]',
            style: const TextStyle(
              fontSize: 8.5,
              fontWeight: FontWeight.w700,
              color: TerminalColors.accent,
            ),
          ),
        ),
      ),
      child: expanded
          ? const Padding(
              padding: EdgeInsets.fromLTRB(10, 8, 10, 9),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '• Read-Only Market Telemetry: No exchange login, wallet, order execution, or financial advice.',
                    style: TextStyle(fontSize: 9.5, color: TerminalColors.text, height: 1.35),
                  ),
                  SizedBox(height: 3),
                  Text(
                    '• Spot & Paper Risk Modeling: Uses 4H regime metrics, key levels & \$100K paper simulation (max 2.0x model cap) for research.',
                    style: TextStyle(fontSize: 9.5, color: TerminalColors.text, height: 1.35),
                  ),
                  SizedBox(height: 3),
                  Text(
                    '• AI Workflow: Copy the raw telemetry packet below into any AI assistant for objective research & Q&A.',
                    style: TextStyle(fontSize: 9.0, color: TerminalColors.muted, height: 1.35),
                  ),
                ],
              ),
            )
          : const SizedBox.shrink(),
    );
  }
}

/// Standout Hero Card making AI Prompt + Compact Telemetry Copy the unmistakable center of the app.
class _AiCopilotHeroCard extends StatefulWidget {
  const _AiCopilotHeroCard({required this.vm});

  final ProtocolViewModel vm;

  @override
  State<_AiCopilotHeroCard> createState() => _AiCopilotHeroCardState();
}

class _AiCopilotHeroCardState extends State<_AiCopilotHeroCard> {
  static const String _defaultHelper =
      'Paste into ChatGPT, Gemini, Claude, Grok, DeepSeek, Kimi, or any AI for direct verdict & follow-up Q&A.';

  String _statusText = _defaultHelper;
  bool _copiedFlash = false;
  Timer? _resetTimer;

  @override
  void dispose() {
    _resetTimer?.cancel();
    super.dispose();
  }

  Future<void> _copyAiPrompt() async {
    final payload = widget.vm.buildAiAnalysisPrompt();
    if (payload.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: payload));
    if (!mounted) return;
    _resetTimer?.cancel();
    setState(() {
      _copiedFlash = true;
      _statusText = 'Copied (${payload.length} chars)! Paste into ChatGPT, Gemini, Claude, Grok, DeepSeek, or Kimi.';
    });
    _resetTimer = Timer(const Duration(seconds: 4), () {
      if (!mounted) return;
      setState(() {
        _copiedFlash = false;
        _statusText = _defaultHelper;
      });
    });
  }

  void _previewPrompt() {
    final payload = widget.vm.buildAiAnalysisPrompt();
    if (payload.isEmpty) return;
    showDialog<void>(
      context: context,
      builder: (ctx) => Dialog(
        backgroundColor: TerminalColors.panel,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.zero,
          side: BorderSide(color: TerminalColors.borderDark, width: 1.5),
        ),
        child: SizedBox(
          width: double.maxFinite,
          height: MediaQuery.of(ctx).size.height * 0.72,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              IbmSectionTitle(
                'AI PROMPT + COMPACT TELEMETRY (${payload.length} CHARS)',
                backgroundColor: TerminalColors.accent,
                textColor: Colors.white,
                trailing: InkWell(
                  onTap: () => Navigator.of(ctx).pop(),
                  child: const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 4),
                    child: Text(
                      '[X]',
                      style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w700),
                    ),
                  ),
                ),
              ),
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(10),
                  child: SelectableText(
                    payload,
                    style: const TextStyle(fontSize: 9.5, color: TerminalColors.text, height: 1.35),
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.all(8),
                decoration: const BoxDecoration(
                  color: TerminalColors.panelAlt,
                  border: Border(top: BorderSide(color: TerminalColors.border)),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    InkWell(
                      onTap: () {
                        Navigator.of(ctx).pop();
                        _copyAiPrompt();
                      },
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                        decoration: BoxDecoration(
                          color: TerminalColors.accent,
                          border: Border.all(color: TerminalColors.borderDark),
                        ),
                        child: const Text(
                          '[COPY ALL & CLOSE]',
                          style: TextStyle(color: Colors.white, fontSize: 9.5, fontWeight: FontWeight.w700),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final liveFresh = widget.vm.isLiveFeedFresh;
    final stale = widget.vm.isSnapshotStale;
    final rawLen = widget.vm.buildCompactRawJson().length;
    final kStr = (rawLen / 1000.0).toStringAsFixed(1);

    return IbmWindowCard(
      title: 'AI ANALYSIS ENGINE (CORE WORKFLOW)',
      headerColor: TerminalColors.accent,
      headerTextColor: Colors.white,
      borderWidth: 1.5,
      trailing: IbmBadge(
        label: liveFresh || !stale ? 'LIVE · READY' : 'CACHED · SYNC',
        color: liveFresh || !stale ? TerminalColors.up : TerminalColors.accent,
      ),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Compact packet telemetry strip
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
              decoration: BoxDecoration(
                color: TerminalColors.panelStripe,
                border: Border.all(color: TerminalColors.border),
              ),
              child: Wrap(
                spacing: 8,
                runSpacing: 2,
                alignment: WrapAlignment.spaceBetween,
                children: [
                  Text(
                    'RAW PACKET: ~${kStr}K chars (compact OHLCV)',
                    style: const TextStyle(fontSize: 9.5, fontWeight: FontWeight.w700, color: TerminalColors.text),
                  ),
                  const Text(
                    'UNBIASED · Q&A GROUNDED',
                    style: TextStyle(fontSize: 9.0, fontWeight: FontWeight.w700, color: TerminalColors.accent),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 8),

            // Standout full-text Primary CTA (never truncated with ellipsis)
            InkWell(
              onTap: _copyAiPrompt,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
                decoration: BoxDecoration(
                  color: _copiedFlash ? TerminalColors.up : TerminalColors.accent,
                  border: Border.all(color: TerminalColors.borderDark, width: 1.2),
                  boxShadow: const [
                    BoxShadow(
                      color: TerminalColors.shadow,
                      offset: Offset(2, 2),
                      blurRadius: 0,
                    ),
                  ],
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(
                      _copiedFlash ? Icons.check_sharp : Icons.copy_all_sharp,
                      size: 14,
                      color: Colors.white,
                    ),
                    const SizedBox(width: 6),
                    Flexible(
                      child: Text(
                        _copiedFlash
                            ? 'COPIED — READY TO PASTE IN ANY AI APP'
                            : '[COPY AI ANALYSIS PROMPT + JSON]',
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 10.5,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 0.3,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 7),

            // Preview button + supported AI model tags
            Row(
              children: [
                InkWell(
                  onTap: _previewPrompt,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
                    decoration: BoxDecoration(
                      color: TerminalColors.panelAlt,
                      border: Border.all(color: TerminalColors.borderDark),
                    ),
                    child: const Text(
                      '[PREVIEW]',
                      style: TextStyle(fontSize: 9, fontWeight: FontWeight.w700, color: TerminalColors.text),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    'ChatGPT · Gemini · Claude · Grok · DeepSeek · Kimi',
                    style: TextStyle(fontSize: 9.0, color: TerminalColors.muted),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),

            // Status / Helper text
            Text(
              _statusText,
              style: TextStyle(
                fontSize: 9.5,
                fontWeight: _copiedFlash ? FontWeight.w700 : FontWeight.w400,
                color: _copiedFlash ? TerminalColors.up : TerminalColors.muted,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
