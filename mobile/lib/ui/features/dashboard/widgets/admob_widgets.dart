import 'package:flutter/material.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

import '../../../../config/ad_config.dart';
import '../../../../l10n/app_strings.dart';
import '../../../core/theme.dart';

/// Google AdMob Banner strip placed cleanly at the bottom of scrollable tab feeds.
class AdMobBannerStrip extends StatefulWidget {
  const AdMobBannerStrip({
    super.key,
    this.enablePlatformPlugins = true,
    this.shouldLoad = true,
    this.tr,
  });

  final bool enablePlatformPlugins;
  final bool shouldLoad;
  final AppStrings? tr;

  @override
  State<AdMobBannerStrip> createState() => _AdMobBannerStripState();
}

class _AdMobBannerStripState extends State<AdMobBannerStrip> {
  BannerAd? _bannerAd;
  bool _loaded = false;
  bool _loadStarted = false;

  @override
  void initState() {
    super.initState();
    _maybeLoadBanner();
  }

  @override
  void didUpdateWidget(covariant AdMobBannerStrip oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.shouldLoad && !oldWidget.shouldLoad) {
      _maybeLoadBanner();
    }
  }

  void _maybeLoadBanner() {
    if (_loadStarted ||
        !widget.shouldLoad ||
        !widget.enablePlatformPlugins ||
        !AppConfig.isMobilePlatform) {
      return;
    }
    _loadStarted = true;
    _loadBanner();
  }

  void _loadBanner() {
    final ad = BannerAd(
      adUnitId: AppConfig.bannerAdUnitId,
      size: AdSize.banner,
      request: const AdRequest(),
      listener: BannerAdListener(
        onAdLoaded: (ad) {
          if (!mounted) {
            ad.dispose();
            return;
          }
          setState(() => _loaded = true);
        },
        onAdFailedToLoad: (ad, _) {
          ad.dispose();
        },
      ),
    )..load();
    _bannerAd = ad;
  }

  @override
  void dispose() {
    _bannerAd?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tr = widget.tr ?? AppStrings.of(AppLang.en);
    if (_loaded && _bannerAd != null) {
      return IbmWindowCard(
        title: tr.t('sponsored_banner'),
        child: Container(
          color: TerminalColors.panel,
          width: double.infinity,
          height: _bannerAd!.size.height.toDouble(),
          alignment: Alignment.center,
          child: SizedBox(
            width: _bannerAd!.size.width.toDouble(),
            height: _bannerAd!.size.height.toDouble(),
            child: AdWidget(ad: _bannerAd!),
          ),
        ),
      );
    }

    return IbmWindowCard(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
        child: Center(
          child: Text(
            tr.t('admob_banner_test'),
            style: const TextStyle(color: TerminalColors.muted, fontSize: 9.5),
          ),
        ),
      ),
    );
  }
}

/// Inline Google AdMob Native Advanced card rendered via Google cross-platform Native Templates.
class AdMobNativeAdCard extends StatefulWidget {
  const AdMobNativeAdCard({
    super.key,
    this.enablePlatformPlugins = true,
    this.tr,
  });

  final bool enablePlatformPlugins;
  final AppStrings? tr;

  @override
  State<AdMobNativeAdCard> createState() => _AdMobNativeAdCardState();
}

class _AdMobNativeAdCardState extends State<AdMobNativeAdCard> {
  NativeAd? _nativeAd;
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    if (widget.enablePlatformPlugins && AppConfig.isMobilePlatform) {
      _loadNative();
    }
  }

  void _loadNative() {
    final ad = NativeAd(
      adUnitId: AppConfig.nativeAdUnitId,
      request: const AdRequest(),
      nativeTemplateStyle: NativeTemplateStyle(
        templateType: TemplateType.medium,
        mainBackgroundColor: TerminalColors.panel,
        cornerRadius: 0.0,
        callToActionTextStyle: NativeTemplateTextStyle(
          textColor: Colors.white,
          backgroundColor: TerminalColors.accent,
          style: NativeTemplateFontStyle.bold,
          size: 12.0,
        ),
        primaryTextStyle: NativeTemplateTextStyle(
          textColor: TerminalColors.text,
          backgroundColor: TerminalColors.panel,
          style: NativeTemplateFontStyle.bold,
          size: 12.0,
        ),
        secondaryTextStyle: NativeTemplateTextStyle(
          textColor: TerminalColors.muted,
          backgroundColor: TerminalColors.panel,
          style: NativeTemplateFontStyle.normal,
          size: 11.0,
        ),
        tertiaryTextStyle: NativeTemplateTextStyle(
          textColor: TerminalColors.muted,
          backgroundColor: TerminalColors.panel,
          style: NativeTemplateFontStyle.normal,
          size: 10.0,
        ),
      ),
      listener: NativeAdListener(
        onAdLoaded: (ad) {
          if (!mounted) {
            ad.dispose();
            return;
          }
          setState(() => _loaded = true);
        },
        onAdFailedToLoad: (ad, _) {
          ad.dispose();
        },
      ),
    )..load();
    _nativeAd = ad;
  }

  @override
  void dispose() {
    _nativeAd?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tr = widget.tr ?? AppStrings.of(AppLang.en);
    if (_loaded && _nativeAd != null) {
      return IbmWindowCard(
        title: tr.t('sponsored_ad'),
        child: Padding(
          padding: const EdgeInsets.all(8),
          child: ConstrainedBox(
            constraints: const BoxConstraints(
              minWidth: 280,
              minHeight: 260,
              maxHeight: 340,
            ),
            child: AdWidget(ad: _nativeAd!),
          ),
        ),
      );
    }

    return IbmWindowCard(
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
              decoration: BoxDecoration(
                color: TerminalColors.panelAlt,
                border: Border.all(color: TerminalColors.border),
              ),
              child: Text(
                tr.t('sponsored_ad'),
                style: const TextStyle(fontSize: 9.0, fontWeight: FontWeight.w700, color: TerminalColors.muted),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                tr.t('admob_native_test'),
                style: const TextStyle(fontSize: 9.5, color: TerminalColors.muted),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
