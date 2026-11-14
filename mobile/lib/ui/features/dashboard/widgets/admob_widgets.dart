import 'package:flutter/material.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

import '../../../../config/ad_config.dart';
import '../../../core/theme.dart';

/// Sticky anchored Google AdMob Banner strip at the bottom of the app shell.
class AdMobBannerStrip extends StatefulWidget {
  const AdMobBannerStrip({
    super.key,
    this.enablePlatformPlugins = true,
  });

  final bool enablePlatformPlugins;

  @override
  State<AdMobBannerStrip> createState() => _AdMobBannerStripState();
}

class _AdMobBannerStripState extends State<AdMobBannerStrip> {
  BannerAd? _bannerAd;
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    if (widget.enablePlatformPlugins && AppConfig.isMobilePlatform) {
      _loadBanner();
    }
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
    if (_loaded && _bannerAd != null) {
      return Container(
        color: TerminalColors.bg,
        width: double.infinity,
        height: _bannerAd!.size.height.toDouble(),
        alignment: Alignment.center,
        child: SizedBox(
          width: _bannerAd!.size.width.toDouble(),
          height: _bannerAd!.size.height.toDouble(),
          child: AdWidget(ad: _bannerAd!),
        ),
      );
    }

    return Container(
      height: 50,
      width: double.infinity,
      alignment: Alignment.center,
      decoration: const BoxDecoration(
        color: TerminalColors.panelAlt,
        border: Border(top: BorderSide(color: TerminalColors.borderDark)),
      ),
      child: const Text(
        'AdMob Banner Slot (320x50 · Test Mode)',
        style: TextStyle(color: TerminalColors.muted, fontSize: 10),
      ),
    );
  }
}

/// Inline Google AdMob Native Advanced card rendered via Google cross-platform Native Templates.
class AdMobNativeAdCard extends StatefulWidget {
  const AdMobNativeAdCard({
    super.key,
    this.enablePlatformPlugins = true,
  });

  final bool enablePlatformPlugins;

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
    if (_loaded && _nativeAd != null) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(8),
          child: ConstrainedBox(
            constraints: const BoxConstraints(
              minWidth: 300,
              minHeight: 280,
              maxHeight: 360,
            ),
            child: AdWidget(ad: _nativeAd!),
          ),
        ),
      );
    }

    return Card(
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
              child: const Text(
                'SPONSORED',
                style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w700, color: TerminalColors.muted),
              ),
            ),
            const SizedBox(width: 8),
            const Expanded(
              child: Text(
                'AdMob Native Advanced Ad Slot (Medium Template · Test Mode)',
                style: TextStyle(fontSize: 10.5, color: TerminalColors.muted),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
