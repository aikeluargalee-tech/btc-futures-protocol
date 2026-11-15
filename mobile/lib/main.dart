import 'package:app_tracking_transparency/app_tracking_transparency.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

import 'config/ad_config.dart';
import 'data/repositories/protocol_repository.dart';
import 'data/services/protocol_api_service.dart';
import 'ui/core/theme.dart';
import 'ui/features/dashboard/view_models/protocol_view_model.dart';
import 'ui/features/dashboard/views/home_shell.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: TerminalColors.bg,
      statusBarIconBrightness: Brightness.dark,
      statusBarBrightness: Brightness.light,
      systemNavigationBarColor: TerminalColors.panel,
      systemNavigationBarIconBrightness: Brightness.dark,
    ),
  );

  if (AppConfig.isMobilePlatform) {
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      try {
        final status = await AppTrackingTransparency.trackingAuthorizationStatus;
        if (status == TrackingStatus.notDetermined) {
          await AppTrackingTransparency.requestTrackingAuthorization();
        }
      } catch (_) {}
    }
    try {
      await MobileAds.instance.initialize();
    } catch (_) {}
  }

  final api = ProtocolApiService();
  final repo = ProtocolRepository(apiService: api);
  final vm = ProtocolViewModel(repository: repo)..initialize();

  runApp(BtcProtocolApp(viewModel: vm));
}

class BtcProtocolApp extends StatelessWidget {
  const BtcProtocolApp({
    super.key,
    required this.viewModel,
    this.enablePlatformPlugins = true,
  });

  final ProtocolViewModel viewModel;
  final bool enablePlatformPlugins;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BTC Desk v4',
      debugShowCheckedModeBanner: false,
      theme: buildTerminalTheme(),
      builder: (context, child) {
        final mq = MediaQuery.of(context);
        return MediaQuery(
          data: mq.copyWith(
            textScaler: mq.textScaler.clamp(minScaleFactor: 0.95, maxScaleFactor: 1.05),
          ),
          child: child ?? const SizedBox.shrink(),
        );
      },
      home: HomeShell(
        vm: viewModel,
        enablePlatformPlugins: enablePlatformPlugins,
      ),
    );
  }
}
