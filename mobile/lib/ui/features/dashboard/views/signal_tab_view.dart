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
        padding: const EdgeInsets.all(8),
        children: [
          // 0. Single Primary AI Prompt Copy Bar
          _AiCopyActionBar(vm: vm),
          const SizedBox(height: 8),

          // 1. Collapsible Protocol Briefing Video Card (vGUZF.mp4)
          ProtocolVideoCard(
            expanded: vm.videoExpanded,
            onToggleExpanded: vm.toggleVideoExpanded,
            enablePlatformPlugins: enablePlatformPlugins,
          ),
          const SizedBox(height: 8),

          // 2. Active Signal & 4H Regime Score Cards
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const IbmSectionTitle('ACTIVE SIGNAL STATUS'),
                Padding(
                  padding: const EdgeInsets.all(10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Flexible(
                            child: Text(
                              sig.status,
                              style: TextStyle(
                                fontSize: 15,
                                fontWeight: FontWeight.w700,
                                color: statusColor,
                              ),
                            ),
                          ),
                          IbmBadge(
                            label: sig.status == 'FLAT'
                                ? 'NO FUTURES ENTRY'
                                : (prop?.entryMethod ?? 'ACTIVE'),
                            color: statusColor,
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      Text(
                        '1D Bias: ${reg.dailyBias}  ·  Open Futures: ${port.openPositions.length}/1  ·  Eq: ${fmtUsd(port.equityUsd, decimals: 2)}',
                        style: const TextStyle(color: TerminalColors.muted, fontSize: 10),
                      ),
                      if (reg.dominantFactors.isNotEmpty) ...[
                        const SizedBox(height: 4),
                        Text(
                          'Drivers: ${reg.dominantFactors.join(" · ")}',
                          style: const TextStyle(color: TerminalColors.text, fontSize: 10.5),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),

          // 3. 4H Multi-Factor Regime Score Gauge Card
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const IbmSectionTitle('4H MULTI-FACTOR REGIME SCORE (0-100)'),
                Padding(
                  padding: const EdgeInsets.all(10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            '${reg.score.toStringAsFixed(1)} / 100',
                            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
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
              ],
            ),
          ),
          const SizedBox(height: 8),

          // 4. Inline Google AdMob Native Advanced Ad Card
          AdMobNativeAdCard(enablePlatformPlugins: enablePlatformPlugins),
          const SizedBox(height: 8),

          // 5. 9-Point Checklist Card
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const IbmSectionTitle('9-POINT FUTURES QUALIFICATION CHECKLIST'),
                Padding(
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
                                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 10.5),
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
              ],
            ),
          ),
          const SizedBox(height: 8),

          // 6. Sizing & 5-Tier Circuit Breakers Card
          if (prop != null && prop.entryPrice > 0)
            Card(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const IbmSectionTitle('PROPOSED SIZING & 5-TIER BREAKERS'),
                  Padding(
                    padding: const EdgeInsets.all(10),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _kv('Direction / Entry', '${prop.direction} @ ${fmtUsd(prop.entryPrice, decimals: 1)}'),
                        _kv('Hard Stop', '${fmtUsd(prop.stopPrice, decimals: 1)} (${prop.stopDistancePct.toStringAsFixed(2)}% ≤ 2.2%)'),
                        _kv('Target 1 (45% @ 1.5R)', '${fmtUsd(prop.target1Price, decimals: 1)} (${prop.target1Label})'),
                        _kv('R:R (Raw / Adj)', '${prop.rawRr.toStringAsFixed(2)}:1 / ${prop.fundingAdjustedRr.toStringAsFixed(2)}:1'),
                        _kv('Size / Leverage', '${prop.sizeBtc} BTC (${prop.leverage.toStringAsFixed(2)}x / 2.00x)'),
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
                ],
              ),
            ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2.5),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(k, style: const TextStyle(color: TerminalColors.muted, fontSize: 10)),
            const SizedBox(width: 8),
            Flexible(
              child: Text(
                v,
                textAlign: TextAlign.right,
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 10),
              ),
            ),
          ],
        ),
      );
}

class _AiCopyActionBar extends StatefulWidget {
  const _AiCopyActionBar({required this.vm});

  final ProtocolViewModel vm;

  @override
  State<_AiCopyActionBar> createState() => _AiCopyActionBarState();
}

class _AiCopyActionBarState extends State<_AiCopyActionBar> {
  static const String _defaultHelper =
      'Paste into ChatGPT, Gemini, Claude, Grok, DeepSeek, Kimi, or any AI for direct verdict & Q&A.';

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
      _statusText = 'Copied! Paste into ChatGPT, Gemini, Claude, Grok, DeepSeek, or Kimi.';
    });
    _resetTimer = Timer(const Duration(seconds: 3), () {
      if (!mounted) return;
      setState(() {
        _copiedFlash = false;
        _statusText = _defaultHelper;
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        InkWell(
          onTap: _copyAiPrompt,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            decoration: BoxDecoration(
              color: TerminalColors.accent,
              border: Border.all(color: TerminalColors.borderDark),
            ),
            child: const Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.copy_all_sharp, size: 14, color: Colors.white),
                SizedBox(width: 6),
                Flexible(
                  child: Text(
                    '[COPY AI ANALYSIS PROMPT + JSON]',
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 10.5,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 0.4,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 4),
        Text(
          _statusText,
          style: TextStyle(
            fontSize: 9.5,
            fontWeight: _copiedFlash ? FontWeight.w700 : FontWeight.w400,
            color: _copiedFlash ? TerminalColors.up : TerminalColors.muted,
          ),
        ),
      ],
    );
  }
}
