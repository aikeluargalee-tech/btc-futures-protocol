"""Inject Google AdMob App IDs, Play Store API 35 SDK targets, and iOS ATT/SKAdNetwork into generated Flutter runners."""
from __future__ import annotations

import pathlib
import plistlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
ANDROID_APP_ID = "ca-app-pub-3940256099942544~3347511713"
IOS_APP_ID = "ca-app-pub-3940256099942544~1458002511"


def patch_android_manifest() -> None:
    manifest = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    if not manifest.exists():
        return
    txt = manifest.read_text(encoding="utf-8")

    for perm in (
        '<uses-permission android:name="android.permission.INTERNET"/>',
        '<uses-permission android:name="com.google.android.gms.permission.AD_ID"/>',
    ):
        if perm.split('name="')[1].split('"')[0] not in txt:
            txt = txt.replace("<application", f"    {perm}\n    <application", 1)

    meta = (
        f'        <meta-data\n'
        f'            android:name="com.google.android.gms.ads.APPLICATION_ID"\n'
        f'            android:value="{ANDROID_APP_ID}"/>'
    )
    if "com.google.android.gms.ads.APPLICATION_ID" not in txt:
        txt = txt.replace("</application>", f"{meta}\n    </application>", 1)

    txt = re.sub(r'android:label="[^"]+"', 'android:label="BTC Protocol v4"', txt, count=1)
    manifest.write_text(txt, encoding="utf-8")


def patch_android_gradle() -> None:
    for fname in ("build.gradle.kts", "build.gradle"):
        gp = ROOT / "android" / "app" / fname
        if not gp.exists():
            continue
        txt = gp.read_text(encoding="utf-8")
        txt = re.sub(r"minSdk\s*=?\s*flutter\.minSdkVersion", "minSdk = 24", txt)
        txt = re.sub(r"minSdkVersion\s+flutter\.minSdkVersion", "minSdkVersion 24", txt)
        txt = re.sub(r"compileSdk\s*=?\s*flutter\.compileSdkVersion", "compileSdk = 35", txt)
        txt = re.sub(r"targetSdk\s*=?\s*flutter\.targetSdkVersion", "targetSdk = 35", txt)
        txt = re.sub(r"targetSdkVersion\s+flutter\.targetSdkVersion", "targetSdkVersion 35", txt)
        gp.write_text(txt, encoding="utf-8")


def patch_ios_plist_and_podfile() -> None:
    plist_path = ROOT / "ios" / "Runner" / "Info.plist"
    if plist_path.exists():
        with plist_path.open("rb") as f:
            plist = plistlib.load(f)
        plist["CFBundleDisplayName"] = "BTC Protocol v4"
        plist["GADApplicationIdentifier"] = IOS_APP_ID
        plist["NSUserTrackingUsageDescription"] = (
            "This identifier is used to deliver relevant advertising without selling personal data."
        )
        plist["ITSAppUsesNonExemptEncryption"] = False
        sk = list(plist.get("SKAdNetworkItems") or [])
        if not any(isinstance(x, dict) and x.get("SKAdNetworkIdentifier") == "cstr6suwn9.skadnetwork" for x in sk):
            sk.append({"SKAdNetworkIdentifier": "cstr6suwn9.skadnetwork"})
        plist["SKAdNetworkItems"] = sk
        with plist_path.open("wb") as f:
            plistlib.dump(plist, f)

    podfile = ROOT / "ios" / "Podfile"
    if podfile.exists():
        txt = podfile.read_text(encoding="utf-8")
        txt = re.sub(r"#\s*platform\s*:ios,\s*'[^']+'", "platform :ios, '13.0'", txt)
        txt = re.sub(r"platform\s*:ios,\s*'1[0-2]\.\d+'", "platform :ios, '13.0'", txt)
        podfile.write_text(txt, encoding="utf-8")

    pbx = ROOT / "ios" / "Runner.xcodeproj" / "project.pbxproj"
    if pbx.exists():
        txt = pbx.read_text(encoding="utf-8")
        txt = re.sub(r"IPHONEOS_DEPLOYMENT_TARGET = 1[0-2]\.\d+;", "IPHONEOS_DEPLOYMENT_TARGET = 13.0;", txt)
        pbx.write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    patch_android_manifest()
    patch_android_gradle()
    patch_ios_plist_and_podfile()
    print("[OK] Configured Android & iOS store runners for AdMob + Play Store / App Store.")
