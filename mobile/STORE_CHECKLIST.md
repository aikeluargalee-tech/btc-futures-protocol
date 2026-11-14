# Mobile App Store & Play Store Submission Checklist (`mobile/`)

## What Is Already Configured
- Native Flutter app (`lib/`) reading `https://aikeluargalee-tech.github.io/btc-futures-protocol/data/state.json` + live BTC spot feed.
- Bundled briefing video asset at `assets/video/vGUZF.mp4` rendered in a collapsible top card on the Signal Tab.
- Google AdMob monetization using `google_mobile_ads`:
  - Anchored bottom `BannerAd` (`AdMobBannerStrip`)
  - Inline `NativeAd` (`AdMobNativeAdCard` via Google Native Templates)
- Apple App Tracking Transparency (`app_tracking_transparency`) + `NSUserTrackingUsageDescription` + `SKAdNetworkItems` (`cstr6suwn9.skadnetwork`) + `ITSAppUsesNonExemptEncryption = false`.
- Android `minSdk = 24`, `compileSdk = 35`, `targetSdk = 35`, `INTERNET` and `AD_ID` permissions.
- Cloud CI workflow (`.github/workflows/mobile_build.yml`) running `flutter analyze`, `flutter test`, Android `.apk` / `.aab`, and iOS `--no-codesign` `.app` builds.

## Required Manual Steps Before Store Upload
1. **Replace Test AdMob IDs with Your Production AdMob IDs**:
   - In AdMob Console, register an Android app and an iOS app, then create one **Banner** and one **Native Advanced** Ad Unit per platform.
   - Update `mobile/lib/config/ad_config.dart` (`_androidBannerUnitId`, `_iosBannerUnitId`, `_androidNativeUnitId`, `_iosNativeUnitId`) and `mobile/tool/configure_store_runners.py` (`ANDROID_APP_ID`, `IOS_APP_ID`), then re-run `configure_store_runners.py` / push to trigger CI.
2. **Android Play Store Signing (`.aab`)**:
   - Generate an upload keystore (`keytool -genkey -v -keystore upload-keystore.jks ...`).
   - Add signing config in `android/app/build.gradle.kts` or GitHub Actions secrets (`ANDROID_KEYSTORE_BASE64`, `KEY_ALIAS`, `KEY_PASSWORD`, `STORE_PASSWORD`).
3. **iOS App Store Signing (`.ipa`)**:
   - Open `mobile/ios/Runner.xcworkspace` in Xcode on macOS (or configure Fastlane Match / App Store Connect API key in `mobile_build.yml`), select your Apple Developer Team, and archive/upload to TestFlight & App Store Connect.
4. **Store Listing Compliance**:
   - Set **App Category**: Finance (note explicitly in App Review notes & description that the app is a paper-trading telemetry & educational protocol monitor, not live order execution or investment advice).
   - Provide a Privacy Policy URL covering AdMob advertising identifiers & non-personalized ad consent if applicable.
