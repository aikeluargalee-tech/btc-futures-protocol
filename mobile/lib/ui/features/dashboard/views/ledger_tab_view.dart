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
    widget.vm.setCustomEquityUsd(s.portfolio.equityUsd);
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
    final tr = widget.vm.tr;

    final calc = ProtocolViewModel.computeV4Sizing(
      equityUsd: double.tryParse(_eqCtrl.text) ?? 100000,
      direction: _dir,
      weekendExtremeHalf: _weekendHalf,
      ddTier1Active: port.breakers.ddTier1Active,
      entry: double.tryParse(_entryCtrl.text) ?? 0,
      stop: double.tryParse(_stopCtrl.text) ?? 0,
      target1: double.tryParse(_tpCtrl.text) ?? 0,
      tr: tr,
    );

    return RefreshIndicator(
      onRefresh: widget.vm.refreshAll,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(10, 6, 10, 14),
        children: [
          IbmWindowCard(
            title: tr.t('calc_title'),
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _numField(tr.t('calc_equity'), _eqCtrl),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: DropdownButtonFormField<String>(
                          value: _dir,
                          style: const TextStyle(color: TerminalColors.text, fontSize: 10),
                          decoration: InputDecoration(labelText: tr.t('calc_direction')),
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
                          title: Text(tr.t('calc_weekend'), style: const TextStyle(fontSize: 9.5)),
                          value: _weekendHalf,
                          onChanged: (v) => setState(() => _weekendHalf = v),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(child: _numField(tr.t('calc_entry'), _entryCtrl)),
                      const SizedBox(width: 6),
                      Expanded(child: _numField(tr.t('calc_stop'), _stopCtrl)),
                      const SizedBox(width: 6),
                      Expanded(child: _numField(tr.t('calc_target1'), _tpCtrl)),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    calc.valid
                        ? tr.t('calc_valid')
                        : '${tr.t('calc_invalid')}: ${calc.issues.join("; ")}',
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      color: calc.valid ? TerminalColors.up : TerminalColors.down,
                      fontSize: 10,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    '${tr.t('calc_size')}: ${calc.sizeBtc.toStringAsFixed(5)} BTC (${fmtUsd(calc.notionalUsd)}) · ${tr.t('calc_lev')}: ${calc.leverage.toStringAsFixed(2)}x/2.0x${calc.leverageCapped ? " ${tr.t('calc_clamped')}" : ""}',
                    style: const TextStyle(fontSize: 10),
                  ),
                  Text(
                    '${tr.t('calc_risk')}: ${calc.actualRiskPct.toStringAsFixed(3)}% (${fmtUsd(calc.actualRiskUsd, decimals: 2)}) · ${tr.t('calc_stop_lbl')}: ${calc.stopDistPct.toStringAsFixed(2)}% · ${tr.t('calc_rr')}: ${calc.rawRr.toStringAsFixed(2)}:1',
                    style: const TextStyle(fontSize: 9.5, color: TerminalColors.muted),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),
          IbmWindowCard(
            title: tr.t('ledger_title'),
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${tr.t('ledger_eq')}: ${fmtUsd(port.equityUsd, decimals: 2)}  ·  ${tr.t('ledger_hwm')}: ${fmtUsd(port.highWaterMarkUsd)}  ·  ${tr.t('ledger_dd')}: ${port.drawdownPct.toStringAsFixed(2)}%',
                    style: const TextStyle(fontSize: 10),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    '${tr.t('ledger_legs')}: ${port.totalClosedLegs}  ·  ${tr.t('ledger_wr')}: ${port.winRatePct.toStringAsFixed(1)}%  ·  ${tr.t('ledger_pf')}: ${port.profitFactor.toStringAsFixed(2)}  ·  ${tr.t('ledger_exp')}: ${port.expectancyR.toStringAsFixed(2)}R',
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
        onChanged: (v) {
          if (ctrl == _eqCtrl) {
            widget.vm.setCustomEquityUsd(double.tryParse(v));
          }
          setState(() {});
        },
      );
}
