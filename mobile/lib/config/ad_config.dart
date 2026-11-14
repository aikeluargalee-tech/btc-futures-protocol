import 'package:flutter/foundation.dart';

/// Centralized endpoints and Google AdMob identifiers.
///
/// NOTE: Defaults below use Google's official AdMob TEST App & Unit IDs so builds,
/// simulators, and internal QA work safely without invalid-traffic policy violations.
/// Replace both App IDs (in AndroidManifest.xml / Info.plist) and Unit IDs here before
/// submitting production releases to Google Play Store or Apple App Store.
class AppConfig {
  AppConfig._();

  static const String protocolStateUrl =
      'https://aikeluargalee-tech.github.io/btc-futures-protocol/data/state.json';

  static const String binanceTickerUrl =
      'https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT';

  static const String coinbaseTickerUrl =
      'https://api.exchange.coinbase.com/products/BTC-USD/ticker';

  static const String privacyPolicyUrl =
      'https://aikeluargalee-tech.github.io/btc-futures-protocol/privacy.html';

  static const String briefingVideoAsset = 'assets/video/vGUZF.mp4';

  // Official Google AdMob Test App IDs (also mirrored in AndroidManifest.xml & Info.plist)
  static const String androidTestAppId = 'ca-app-pub-3940256099942544~3347511713';
  static const String iosTestAppId = 'ca-app-pub-3940256099942544~1458002511';

  // Ad Unit IDs support CI --dart-define injection, defaulting to official Google AdMob Test IDs
  static const String _androidBannerUnitId = String.fromEnvironment(
    'ADMOB_ANDROID_BANNER_ID',
    defaultValue: 'ca-app-pub-3940256099942544/6300978111',
  );
  static const String _iosBannerUnitId = String.fromEnvironment(
    'ADMOB_IOS_BANNER_ID',
    defaultValue: 'ca-app-pub-3940256099942544/2934735716',
  );

  static const String _androidNativeUnitId = String.fromEnvironment(
    'ADMOB_ANDROID_NATIVE_ID',
    defaultValue: 'ca-app-pub-3940256099942544/2247696110',
  );
  static const String _iosNativeUnitId = String.fromEnvironment(
    'ADMOB_IOS_NATIVE_ID',
    defaultValue: 'ca-app-pub-3940256099942544/3986624511',
  );

  static String get bannerAdUnitId {
    if (defaultTargetPlatform == TargetPlatform.iOS) return _iosBannerUnitId;
    return _androidBannerUnitId;
  }

  static String get nativeAdUnitId {
    if (defaultTargetPlatform == TargetPlatform.iOS) return _iosNativeUnitId;
    return _androidNativeUnitId;
  }

  static bool get isMobilePlatform =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.android ||
          defaultTargetPlatform == TargetPlatform.iOS);
}
