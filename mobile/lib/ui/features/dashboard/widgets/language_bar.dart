import 'package:flutter/material.dart';

import '../../../../l10n/app_strings.dart';
import '../../../core/theme.dart';

/// Compact IBM-grey single-row 7-flag PNG language selector bar:
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
        color: TerminalColors.panel,
        border: Border.all(color: TerminalColors.borderDark),
        boxShadow: const [
          BoxShadow(
            color: TerminalColors.shadow,
            offset: Offset(3, 3),
            blurRadius: 0,
          ),
        ],
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
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 3),
            decoration: BoxDecoration(
              color: active ? TerminalColors.upBg : TerminalColors.panelAlt,
              border: Border.all(
                color: active ? TerminalColors.up : TerminalColors.border,
                width: active ? 1.5 : 1.0,
              ),
            ),
            child: Image.asset(
              'assets/flags/${lang.code}.png',
              width: 18,
              height: 12,
              filterQuality: FilterQuality.medium,
            ),
          ),
        ),
      ),
    );
  }
}
