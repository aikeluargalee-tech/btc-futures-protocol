import 'package:flutter/material.dart';

/// Whitish-grey IBM Retro Workstation palette mirroring the web HUD (`style.css`).
class TerminalColors {
  TerminalColors._();

  static const Color bg = Color(0xFFE4E4DF);
  static const Color panel = Color(0xFFF5F5F1);
  static const Color panelAlt = Color(0xFFDCDCD5);
  static const Color panelStripe = Color(0xFFECECE6);
  static const Color border = Color(0xFFA4A7A1);
  static const Color borderDark = Color(0xFF1B2026);
  static const Color shadow = Color(0xFFB6B6AE);

  static const Color text = Color(0xFF14181D);
  static const Color muted = Color(0xFF4F555D);

  static const Color up = Color(0xFF0E6027);
  static const Color upBg = Color(0xFFDEFBE6);
  static const Color down = Color(0xFFA2191F);
  static const Color downBg = Color(0xFFFFF1F1);
  static const Color warn = Color(0xFF8A4B08);
  static const Color warnBg = Color(0xFFFFF8E1);

  static const Color accent = Color(0xFF0043CE);
  static const Color accentBright = Color(0xFF0F62FE);
  static const Color accentSoft = Color(0xFFD6E4FF);
}

ThemeData buildTerminalTheme() {
  const monoFont = 'monospace';

  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.light,
    fontFamily: monoFont,
    scaffoldBackgroundColor: TerminalColors.bg,
    colorScheme: const ColorScheme.light(
      primary: TerminalColors.accent,
      onPrimary: Colors.white,
      surface: TerminalColors.panel,
      onSurface: TerminalColors.text,
      error: TerminalColors.down,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: TerminalColors.panel,
      foregroundColor: TerminalColors.text,
      elevation: 0,
      surfaceTintColor: Colors.transparent,
    ),
    cardTheme: const CardThemeData(
      color: TerminalColors.panel,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.zero,
        side: BorderSide(color: TerminalColors.borderDark, width: 1),
      ),
    ),
    dividerTheme: const DividerThemeData(
      color: TerminalColors.border,
      thickness: 1,
      space: 1,
    ),
    textTheme: const TextTheme(
      bodyLarge: TextStyle(color: TerminalColors.text, fontSize: 11.5, height: 1.35),
      bodyMedium: TextStyle(color: TerminalColors.text, fontSize: 11.0, height: 1.35),
      bodySmall: TextStyle(color: TerminalColors.muted, fontSize: 10.0, height: 1.3),
      labelSmall: TextStyle(color: TerminalColors.muted, fontSize: 9.5, fontWeight: FontWeight.w700),
    ),
    inputDecorationTheme: const InputDecorationTheme(
      isDense: true,
      filled: true,
      fillColor: Colors.white,
      contentPadding: EdgeInsets.symmetric(horizontal: 8, vertical: 7),
      labelStyle: TextStyle(fontSize: 10, color: TerminalColors.muted),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.zero,
        borderSide: BorderSide(color: TerminalColors.borderDark),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.zero,
        borderSide: BorderSide(color: TerminalColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.zero,
        borderSide: BorderSide(color: TerminalColors.accent, width: 1.5),
      ),
    ),
  );
}

/// Shared sharp-corner section header used inside IBM panels.
class IbmSectionTitle extends StatelessWidget {
  const IbmSectionTitle(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: const BoxDecoration(
        color: TerminalColors.panelAlt,
        border: Border(bottom: BorderSide(color: TerminalColors.border)),
      ),
      child: Text(
        '▪ $text',
        style: const TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.6,
          color: TerminalColors.text,
        ),
      ),
    );
  }
}

/// Sharp rectangular status badge with semantic fill & border.
class IbmBadge extends StatelessWidget {
  const IbmBadge({
    super.key,
    required this.label,
    required this.color,
    this.background,
  });

  final String label;
  final Color color;
  final Color? background;

  @override
  Widget build(BuildContext context) {
    final bg = background ??
        (color == TerminalColors.up
            ? TerminalColors.upBg
            : color == TerminalColors.down
                ? TerminalColors.downBg
                : color == TerminalColors.warn
                    ? TerminalColors.warnBg
                    : TerminalColors.accentSoft);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: bg,
        border: Border.all(color: color),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 9.5,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.4,
          color: color,
        ),
      ),
    );
  }
}
