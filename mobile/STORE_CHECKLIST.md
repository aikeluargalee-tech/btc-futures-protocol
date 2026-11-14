# Mobile App Store & Play Store Submission Checklist (`mobile/`)

## What Is Already Configured (Phase 1 & Phase 2 Complete)
- **Whitish-Grey IBM Retro UI (`lib/ui/`)**: Matches the web HUD with small typography, `[COPY AI ANALYSIS PROMPT + JSON]` in Signal Tab, and `[COPY RAW JSON ONLY]` in `F4 AUDIT`.
- **Live Feeds + Bundled Video**: Reads `https://aikeluargalee-tech.github.io/btc-futures-protocol/data/state.json` + live BTC spot tickers; bundles `assets/video/vGUZF.mp4` (`ProtocolVideoCard`).
- **Google AdMob Monetization**: Sticky anchored `BannerAd` (`AdMobBannerStrip`) + inline `NativeAd` (`AdMobNativeAdCard`), supporting CI `--dart-define` / env overrides with official Test IDs as safe defaults.
- **Custom Store Launcher Icons**: `assets/store_icons/` contains custom IBM Retro window icons (`play_store_512.png`, `app_icon_1024.png`, Android `mipmap-*`, iOS `AppIcon.appiconset`), installed automatically by `tool/configure_store_runners.py`.
- **Hosted Privacy Policy**: Published at `https://aikeluargalee-tech.github.io/btc-futures-protocol/privacy.html` (`privacy.html` in repo root).
- **Platform Compliance**: Apple ATT (`app_tracking_transparency` + `NSUserTrackingUsageDescription` + `SKAdNetworkItems` + `ITSAppUsesNonExemptEncryption = false`) and Android `minSdk = 24`, `compileSdk = 35`, `targetSdk = 35`, `INTERNET`, `AD_ID`.

## Phase 3 Manual Steps for Store Upload

### 1. Create Production AdMob Units & Add GitHub Secrets
In AdMob Console, create an Android app and an iOS app, each with one **Banner** and one **Native Advanced** ad unit, then set these **GitHub Repository Secrets**:
- `ADMOB_ANDROID_APP_ID` (`ca-app-pub-...~...`)
- `ADMOB_ANDROID_BANNER_ID` (`ca-app-pub-.../...`)
- `ADMOB_ANDROID_NATIVE_ID` (`ca-app-pub-.../...`)
- `ADMOB_IOS_APP_ID` (`ca-app-pub-...~...`)
- `ADMOB_IOS_BANNER_ID` (`ca-app-pub-.../...`)
- `ADMOB_IOS_NATIVE_ID` (`ca-app-pub-.../...`)

### 2. Android Play Store Upload Keystore (`.aab` Signing)
Generate your upload keystore locally (keep this file strictly private, outside Git):
```bash
keytool -genkey -v -keystore upload-keystore.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload
```
Encode `upload-keystore.jks` to base64 and add these **GitHub Repository Secrets** (CI `.github/workflows/mobile_build.yml` will automatically sign `app-release.aab`):
- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEY_ALIAS` (e.g. `upload`)
- `ANDROID_STORE_PASSWORD`
- `ANDROID_KEY_PASSWORD`

### 3. iOS App Store Signing (`.ipa`)
1. On macOS, run `flutter create --org io.github.aikeluargalee --project-name btc_futures_protocol --platforms=ios . && python3 tool/configure_store_runners.py` inside `mobile/`.
2. Open `mobile/ios/Runner.xcworkspace` in Xcode, select your Apple Developer Team signing certificate, archive, and upload to **TestFlight / App Store Connect**.

### 4. Store Listing Compliance Notes
- **Category**: Finance
- **Privacy Policy URL**: `https://aikeluargalee-tech.github.io/btc-futures-protocol/privacy.html`
- **Data Safety / App Privacy**: Declare Advertising ID / IDFA (Third-Party Advertising via AdMob).
- **Reviewer Notes**: Explicitly state the app is a read-only 4H telemetry monitor, position calculator, and AI prompt copier with no brokerage execution, wallets, or financial advice.
