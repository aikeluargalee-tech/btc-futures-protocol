import 'dart:math' as math;
import 'package:flutter/material.dart';

import '../../../../domain/models/protocol_state.dart';
import '../../../core/theme.dart';

class PriceChartCard extends StatefulWidget {
  const PriceChartCard({
    super.key,
    required this.charts,
    required this.levels,
    required this.proposal,
  });

  final Map<String, List<ChartCandle>> charts;
  final List<StructuralLevel> levels;
  final OrderProposal? proposal;

  @override
  State<PriceChartCard> createState() => _PriceChartCardState();
}

class _PriceChartCardState extends State<PriceChartCard> {
  String _tf = 'h4';

  @override
  Widget build(BuildContext context) {
    final bars = (widget.charts[_tf] ?? const <ChartCandle>[]);
    final sliced = bars.length > 60 ? bars.sublist(bars.length - 60) : bars;

    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const IbmSectionTitle('STRUCTURAL PRICE MAP'),
          Padding(
            padding: const EdgeInsets.all(10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    SegmentedButton<String>(
                      segments: const [
                        ButtonSegment(value: 'h4', label: Text('4H', style: TextStyle(fontSize: 10))),
                        ButtonSegment(value: 'd1', label: Text('1D', style: TextStyle(fontSize: 10))),
                      ],
                      selected: {_tf},
                      onSelectionChanged: (s) => setState(() => _tf = s.first),
                      style: ButtonStyle(
                        visualDensity: VisualDensity.compact,
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        shape: WidgetStateProperty.all(
                          const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Container(
                  height: 170,
                  width: double.infinity,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    border: Border.all(color: TerminalColors.border),
                  ),
                  child: sliced.length < 2
                      ? const Center(
                          child: Text(
                            'Chart data unavailable',
                            style: TextStyle(color: TerminalColors.muted, fontSize: 10.5),
                          ),
                        )
                      : CustomPaint(
                          painter: _ChartPainter(
                            bars: sliced,
                            levels: widget.levels,
                            proposal: widget.proposal,
                          ),
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

class _ChartPainter extends CustomPainter {
  _ChartPainter({
    required this.bars,
    required this.levels,
    required this.proposal,
  });

  final List<ChartCandle> bars;
  final List<StructuralLevel> levels;
  final OrderProposal? proposal;

  @override
  void paint(Canvas canvas, Size size) {
    var lo = bars.map((b) => b.low).reduce(math.min);
    var hi = bars.map((b) => b.high).reduce(math.max);
    final pad = (hi - lo) * 0.08;
    lo -= pad > 0 ? pad : 200;
    hi += pad > 0 ? pad : 200;

    double yFor(double price) =>
        10 + ((hi - price) / math.max(hi - lo, 1.0)) * (size.height - 20);
    double xFor(int idx) => (idx / (bars.length - 1)) * (size.width - 12) + 6;

    for (final lv in levels) {
      if (lv.price < lo || lv.price > hi) continue;
      final y = yFor(lv.price);
      final paint = Paint()
        ..color = (lv.kind == 'resistance'
                ? TerminalColors.down
                : lv.kind == 'support'
                    ? TerminalColors.up
                    : TerminalColors.muted)
            .withValues(alpha: 0.35)
        ..strokeWidth = 1.0;
      canvas.drawLine(Offset(6, y), Offset(size.width - 6, y), paint);
    }

    if (proposal != null && proposal!.entryPrice > 0) {
      final marks = [
        (proposal!.entryPrice, TerminalColors.warn),
        (proposal!.stopPrice, TerminalColors.down),
        (proposal!.target1Price, TerminalColors.up),
      ];
      for (final (price, col) in marks) {
        if (price < lo || price > hi) continue;
        final y = yFor(price);
        canvas.drawLine(
          Offset(6, y),
          Offset(size.width - 6, y),
          Paint()
            ..color = col.withValues(alpha: 0.85)
            ..strokeWidth = 1.3,
        );
      }
    }

    final path = Path();
    for (var i = 0; i < bars.length; i++) {
      final x = xFor(i);
      final y = yFor(bars[i].close);
      if (i == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = TerminalColors.accent
        ..strokeWidth = 2.0
        ..style = PaintingStyle.stroke,
    );
  }

  @override
  bool shouldRepaint(covariant _ChartPainter oldDelegate) =>
      oldDelegate.bars != bars || oldDelegate.proposal != proposal;
}
