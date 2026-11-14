"""Inject Google AdMob App IDs, store launcher icons, Play Store API 35 SDK targets, signing config, and iOS ATT/SKAdNetwork."""
from __future__ import annotations

import os
import pathlib
import plistlib
import re
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
ANDROID_TEST_APP_ID = "ca-app-pub-3940256099942544~3347511713"
IOS_TEST_APP_ID = "ca-app-pub-3940256099942544~1458002511"

ANDROID_APP_ID = os.environ.get("ADMOB_ANDROID_APP_ID") or ANDROID_TEST_APP_ID
IOS_APP_ID = os.environ.get("ADMOB_IOS_APP_ID") or IOS_TEST_APP_ID


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
    for sf in ("settings.gradle.kts", "settings.gradle"):
        sp = ROOT / "android" / sf
        if not sp.exists():
            continue
        stxt = sp.read_text(encoding="utf-8")
        stxt = re.sub(
            r'(id\s*(?:\(\s*|\s+)["\']com\.android\.application["\']\s*\)?\s+version\s+["\'])8\.(?:0\.\d+|1\.0)(["\'])',
            r"\g<1>8.1.4\g<2>",
            stxt,
        )
        sp.write_text(stxt, encoding="utf-8")

    key_props = ROOT / "android" / "key.properties"

    gp_kts = ROOT / "android" / "app" / "build.gradle.kts"
    if gp_kts.exists():
        txt = gp_kts.read_text(encoding="utf-8")
        txt = re.sub(r"minSdk\s*=?\s*flutter\.minSdkVersion", "minSdk = 24", txt)
        txt = re.sub(r"compileSdk\s*=?\s*flutter\.compileSdkVersion", "compileSdk = 35", txt)
        txt = re.sub(r"targetSdk\s*=?\s*flutter\.targetSdkVersion", "targetSdk = 35", txt)

        if key_props.exists() and "keystorePropertiesFile" not in txt:
            header = (
                'import java.util.Properties\n'
                'import java.io.FileInputStream\n\n'
                'val keystoreProperties = Properties()\n'
                'val keystorePropertiesFile = rootProject.file("key.properties")\n'
                'if (keystorePropertiesFile.exists()) {\n'
                '    keystoreProperties.load(FileInputStream(keystorePropertiesFile))\n'
                '}\n'
            )
            txt = header + "\n" + txt
            signing_block = (
                '    signingConfigs {\n'
                '        create("release") {\n'
                '            keyAlias = keystoreProperties.getProperty("keyAlias")\n'
                '            keyPassword = keystoreProperties.getProperty("keyPassword")\n'
                '            storeFile = keystoreProperties.getProperty("storeFile")?.let { file(it) }\n'
                '            storePassword = keystoreProperties.getProperty("storePassword")\n'
                '        }\n'
                '    }\n'
                '    buildTypes {'
            )
            txt = txt.replace("    buildTypes {", signing_block, 1)
            txt = txt.replace(
                "signingConfig = signingConfigs.getByName(\"debug\")",
                'signingConfig = signingConfigs.getByName("release")',
            )
        gp_kts.write_text(txt, encoding="utf-8")

    gp_groovy = ROOT / "android" / "app" / "build.gradle"
    if gp_groovy.exists():
        txt = gp_groovy.read_text(encoding="utf-8")
        txt = re.sub(r"minSdkVersion\s+flutter\.minSdkVersion", "minSdkVersion 24", txt)
        txt = re.sub(r"targetSdkVersion\s+flutter\.targetSdkVersion", "targetSdkVersion 35", txt)
        gp_groovy.write_text(txt, encoding="utf-8")


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


def install_store_icons() -> None:
    icons_dir = ROOT / "assets" / "store_icons"
    android_src = icons_dir / "android"
    android_res = ROOT / "android" / "app" / "src" / "main" / "res"
    if android_src.exists() and android_res.exists():
        for mipmap in android_src.iterdir():
            src_png = mipmap / "ic_launcher.png"
            if mipmap.is_dir() and src_png.exists():
                dst_dir = android_res / mipmap.name
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_png, dst_dir / "ic_launcher.png")

    ios_src = icons_dir / "ios" / "AppIcon.appiconset"
    ios_dst = ROOT / "ios" / "Runner" / "Assets.xcassets" / "AppIcon.appiconset"
    if ios_src.exists() and ios_dst.exists():
        for png in ios_src.glob("*.png"):
            shutil.copy2(png, ios_dst / png.name)


if __name__ == "__main__":
    patch_android_manifest()
    patch_android_gradle()
    patch_ios_plist_and_podfile()
    install_store_icons()
    print("[OK] Configured Android & iOS store runners (icons, AdMob IDs, signing, ATT).")
