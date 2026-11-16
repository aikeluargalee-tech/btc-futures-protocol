import 'package:flutter/material.dart';

import '../../../../l10n/app_strings.dart';

/// Compact dark 7-flag language selector bar matching the retro switcher strip:
/// EN (US), ZH (CN), ID, KO (KR), JA (JP), FR, ES.
class LanguageBar extends StatelessWidget {
  const LanguageBar({
    super.key,
    required this.selected,
    required this.onSelected,
  });

  final AppLang selected;
  final ValueChanged<AppLang> onSelected;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
      decoration: BoxDecoration(
        color: const Color(0xFF10151E),
        border: Border.all(color: const Color(0xFF283244)),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: [
          for (final lang in AppLang.values)
            _FlagButton(
              lang: lang,
              active: lang == selected,
              onTap: () => onSelected(lang),
            ),
        ],
      ),
    );
  }
}

class _FlagButton extends StatelessWidget {
  const _FlagButton({
    required this.lang,
    required this.active,
    required this.onTap,
  });

  final AppLang lang;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: lang.nativeName,
      child: Semantics(
        button: true,
        selected: active,
        label: lang.nativeName,
        child: InkWell(
          key: Key('lang_btn_${lang.code}'),
          onTap: onTap,
          borderRadius: BorderRadius.circular(5),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 120),
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 3),
            decoration: BoxDecoration(
              color: active
                  ? const Color(0xFF143524)
                  : const Color(0xFF171E2B),
              borderRadius: BorderRadius.circular(5),
              border: Border.all(
                color: active
                    ? const Color(0xFF22C55E)
                    : const Color(0xFF2D3748),
                width: active ? 1.6 : 1.0,
              ),
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(1.5),
              child: CustomPaint(
                size: const Size(22, 14),
                painter: _FlagPainter(lang),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _FlagPainter extends CustomPainter {
  const _FlagPainter(this.lang);

  final AppLang lang;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    final paint = Paint()..style = PaintingStyle.fill;

    switch (lang) {
      case AppLang.en:
        // US flag: red/white stripes + blue canton
        paint.color = Colors.white;
        canvas.drawRect(Rect.fromLTWH(0, 0, w, h), paint);
        paint.color = const Color(0xFFB22234);
        final stripeH = h / 7.0;
        for (var i = 0; i < 7; i += 2) {
          canvas.drawRect(Rect.fromLTWH(0, i * stripeH, w, stripeH), paint);
        }
        paint.color = const Color(0xFF3C3B6E);
        canvas.drawRect(Rect.fromLTWH(0, 0, w * 0.44, h * 0.56), paint);
        paint.color = Colors.white;
        for (var r = 0; r < 3; r++) {
          for (var c = 0; c < 3; c++) {
            canvas.drawCircle(
              Offset(w * (0.09 + c * 0.12), h * (0.12 + r * 0.16)),
              0.8,
              paint,
            );
          }
        }

      case AppLang.zh:
        // China flag: red field + gold stars
        paint.color = const Color(0xFFDE2910);
        canvas.drawRect(Rect.fromLTWH(0, 0, w, h), paint);
        paint.color = const Color(0xFFFFDE00);
        canvas.drawCircle(Offset(w * 0.22, h * 0.34), 2.3, paint);
        canvas.drawCircle(Offset(w * 0.37, h * 0.18), 0.9, paint);
        canvas.drawCircle(Offset(w * 0.43, h * 0.30), 0.9, paint);
        canvas.drawCircle(Offset(w * 0.43, h * 0.45), 0.9, paint);
        canvas.drawCircle(Offset(w * 0.37, h * 0.56), 0.9, paint);

      case AppLang.id:
        // Indonesia flag: red top, white bottom
        paint.color = const Color(0xFFCE1126);
        canvas.drawRect(Rect.fromLTWH(0, 0, w, h * 0.5), paint);
        paint.color = Colors.white;
        canvas.drawRect(Rect.fromLTWH(0, h * 0.5, w, h * 0.5), paint);

      case AppLang.ko:
        // South Korea flag: white + red/blue Taegeuk + 4 dark corner bars
        paint.color = Colors.white;
        canvas.drawRect(Rect.fromLTWH(0, 0, w, h), paint);
        final cx = w * 0.5;
        final cy = h * 0.5;
        final r = h * 0.27;
        paint.color = const Color(0xFFCD2E3A);
        canvas.drawArc(
          Rect.fromCircle(center: Offset(cx, cy), radius: r),
          3.14159,
          3.14159,
          true,
          paint,
        );
        paint.color = const Color(0xFF0047A0);
        canvas.drawArc(
          Rect.fromCircle(center: Offset(cx, cy), radius: r),
          0,
          3.14159,
          true,
          paint,
        );
        paint.color = const Color(0xFF1A1A1A);
        for (final pos in [
          Offset(w * 0.20, h * 0.22),
          Offset(w * 0.80, h * 0.22),
          Offset(w * 0.20, h * 0.78),
          Offset(w * 0.80, h * 0.78),
        ]) {
          canvas.drawRect(
            Rect.fromCenter(center: pos, width: 3.2, height: 1.6),
            paint,
          );
        }

      case AppLang.ja:
        // Japan flag: white field + crimson sun disc
        paint.color = Colors.white;
        canvas.drawRect(Rect.fromLTWH(0, 0, w, h), paint);
        paint.color = const Color(0xFFBC002D);
        canvas.drawCircle(Offset(w * 0.5, h * 0.5), h * 0.30, paint);

      case AppLang.fr:
        // France flag: vertical blue, white, red
        paint.color = const Color(0xFF002395);
        canvas.drawRect(Rect.fromLTWH(0, 0, w / 3.0, h), paint);
        paint.color = Colors.white;
        canvas.drawRect(Rect.fromLTWH(w / 3.0, 0, w / 3.0, h), paint);
        paint.color = const Color(0xFFED2939);
        canvas.drawRect(Rect.fromLTWH((w * 2.0) / 3.0, 0, w / 3.0, h), paint);

      case AppLang.es:
        // Spain flag: red, gold, red + mini coat accent
        paint.color = const Color(0xFFAA151B);
        canvas.drawRect(Rect.fromLTWH(0, 0, w, h * 0.25), paint);
        paint.color = const Color(0xFFF1BF00);
        canvas.drawRect(Rect.fromLTWH(0, h * 0.25, w, h * 0.5), paint);
        paint.color = const Color(0xFFAA151B);
        canvas.drawRect(Rect.fromLTWH(0, h * 0.75, w, h * 0.25), paint);
        canvas.drawRect(Rect.fromLTWH(w * 0.26, h * 0.34, 2.4, h * 0.32), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _FlagPainter oldDelegate) =>
      oldDelegate.lang != lang;
}
