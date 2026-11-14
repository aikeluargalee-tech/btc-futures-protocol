import 'package:flutter/material.dart';

class TerminalColors {
  TerminalColors._();

  static const Color bg = Color(0xFF080B0F);
  static const Color panel = Color(0xFF0F141B);
  static const Color panelAlt = Color(0xFF131A23);
  static const Color border = Color(0xFF1D2733);
  static const Color text = Color(0xFFDCE5EF);
  static const Color muted = Color(0xFF7C8C9E);
  static const Color up = Color(0xFF26D07C);
  static const Color down = Color(0xFFFF5466);
  static const Color warn = Color(0xFFFFB020);
  static const Color accent = Color(0xFF3FA9FF);
}

ThemeData buildTerminalTheme() {
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    scaffoldBackgroundColor: TerminalColors.bg,
    colorScheme: const ColorScheme.dark(
      primary: TerminalColors.accent,
      surface: TerminalColors.panel,
      onSurface: TerminalColors.text,
      error: TerminalColors.down,
    ),
    cardTheme: CardThemeData(
      color: TerminalColors.panel,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: TerminalColors.border),
      ),
    ),
    textTheme: const TextTheme(
      bodyMedium: TextStyle(color: TerminalColors.text, fontSize: 13),
      bodySmall: TextStyle(color: TerminalColors.muted, fontSize: 12),
    ),
  );
}
