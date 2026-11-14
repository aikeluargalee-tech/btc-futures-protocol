String fmtUsd(double? v, {int decimals = 0}) {
  if (v == null || v.isNaN || v.isInfinite) return '—';
  final neg = v < 0;
  final fixed = v.abs().toStringAsFixed(decimals);
  final parts = fixed.split('.');
  final intPart = parts[0].replaceAllMapped(
    RegExp(r'(\d)(?=(\d{3})+(?!\d))'),
    (m) => '${m[1]},',
  );
  final formatted = parts.length > 1 ? '$intPart.${parts[1]}' : intPart;
  return '${neg ? '-' : ''}\$$formatted';
}

String fmtSignedPct(double? v, {int decimals = 2}) {
  if (v == null || v.isNaN || v.isInfinite) return '—';
  return '${v >= 0 ? '+' : ''}${v.toStringAsFixed(decimals)}%';
}
