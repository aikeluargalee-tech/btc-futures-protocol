import 'package:flutter/material.dart';

import '../../../core/formatters.dart';
import '../../../core/theme.dart';
import '../view_models/protocol_view_model.dart';

class LedgerTabView extends StatefulWidget {
  const LedgerTabView({super.key, required this.vm});

  final ProtocolViewModel vm;

  @override
  State<LedgerTabView> createState() => _LedgerTabViewState();
}

class _LedgerTabViewState extends State<LedgerTabView> {
  final _eqCtrl = TextEditingController(text: '100000');
  final _entryCtrl = TextEditingController();
  final _stopCtrl = TextEditingController();
  final _tpCtrl = TextEditingController();
  String _dir = 'LONG';
  bool _weekendHalf = false;
  bool _seeded = false;

  @override
  void dispose() {
    _eqCtrl.dispose();
    _entryCtrl.dispose();
    _stopCtrl.dispose();
    _tpCtrl.dispose();
    super.dispose();
  }

  void _seedIfNeeded() {
    if (_seeded) return;
    final s = widget.vm.state;
    final prop = s?.signal.proposal;
    if (s == null || prop == null || prop.entryPrice <= 0) return;
    _eqCtrl.text = s.portfolio.equityUsd.round().toString();
    _entryCtrl.text = prop.entryPrice.toStringAsFixed(1);
    _stopCtrl.text = prop.stopPrice.toStringAsFixed(1);
    _tpCtrl.text = prop.target1Price.toStringAsFixed(1);
    _dir = prop.direction == 'SHORT' ? 'SHORT' : 'LONG';
    _weekendHalf = s.regime.isWeekendUtc;
    _seeded = true;
  }

  @override
  Widget build(BuildContext context) {
    _seedIfNeeded();
    final s = widget.vm.state;
    if (s == null) return const Center(child: CircularProgressIndicator());
    final port = s.portfolio;

    final calc = ProtocolViewModel.computeV4Sizing(
      equityUsd: double.tryParse(_eqCtrl.text) ?? 100000,
      direction: _dir,
      weekendExtremeHalf: _weekendHalf,
      ddTier1Active: port.breakers.ddTier1Active,
      entry: double.tryParse(_entryCtrl.text) ?? 0,
      stop: double.tryParse(_stopCtrl.text) ?? 0,
      target1: double.tryParse(_tpCtrl.text) ?? 0,
    );

    return RefreshIndicator(
      onRefresh: widget.vm.refreshAll,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(10, 6, 10, 14),
        children: [
          IbmWindowCard(
            title: 'v4.0 POSITION SIZING CALCULATOR',
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _numField('Equity USD', _eqCtrl),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: DropdownButtonFormField<String>(
                          value: _dir,
                          style: const TextStyle(color: TerminalColors.text, fontSize: 10),
                          decoration: const InputDecoration(labelText: 'Direction'),
                          items: const [
                            DropdownMenuItem(value: 'LONG', child: Text('LONG')),
                            DropdownMenuItem(value: 'SHORT', child: Text('SHORT')),
                          ],
                          onChanged: (v) => setState(() => _dir = v ?? 'LONG'),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          dense: true,
                          title: const Text('Weekend 0.5x', style: TextStyle(fontSize: 9.5)),
                          value: _weekendHalf,
                          onChanged: (v) => setState(() => _weekendHalf = v),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(child: _numField('Entry', _entryCtrl)),
                      const SizedBox(width: 6),
                      Expanded(child: _numField('Stop', _stopCtrl)),
                      const SizedBox(width: 6),
                      Expanded(child: _numField('Target 1', _tpCtrl)),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    calc.valid ? 'VALID v4.0 PAPER SIZING (MAX 2.0x CAP)' : 'INVALID: ${calc.issues.join("; ")}',
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      color: calc.valid ? TerminalColors.up : TerminalColors.down,
                      fontSize: 10,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    'Size: ${calc.sizeBtc.toStringAsFixed(5)} BTC (${fmtUsd(calc.notionalUsd)}) · Lev: ${calc.leverage.toStringAsFixed(2)}x/2.0x${calc.leverageCapped ? " CLAMPED" : ""}',
                    style: const TextStyle(fontSize: 10),
                  ),
                  Text(
                    'Risk: ${calc.actualRiskPct.toStringAsFixed(3)}% (${fmtUsd(calc.actualRiskUsd, decimals: 2)}) · Stop: ${calc.stopDistPct.toStringAsFixed(2)}% · R:R: ${calc.rawRr.toStringAsFixed(2)}:1',
                    style: const TextStyle(fontSize: 9.5, color: TerminalColors.muted),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),
          IbmWindowCard(
            title: 'PAPER LEDGER SUMMARY (SIMULATED)',
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Equity: ${fmtUsd(port.equityUsd, decimals: 2)}  ·  HWM: ${fmtUsd(port.highWaterMarkUsd)}  ·  DD: ${port.drawdownPct.toStringAsFixed(2)}%',
                    style: const TextStyle(fontSize: 10),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    'Closed Legs: ${port.totalClosedLegs}  ·  WR: ${port.winRatePct.toStringAsFixed(1)}%  ·  PF: ${port.profitFactor.toStringAsFixed(2)}  ·  Exp: ${port.expectancyR.toStringAsFixed(2)}R',
                    style: const TextStyle(fontSize: 9.5, color: TerminalColors.muted),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _numField(String label, TextEditingController ctrl) => TextField(
        controller: ctrl,
        style: const TextStyle(fontSize: 10, color: TerminalColors.text),
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(labelText: label),
        onChanged: (_) => setState(() {}),
      );
}
