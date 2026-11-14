import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../../config/ad_config.dart';
import '../../domain/models/protocol_state.dart';

class LiveTicker {
  final double price;
  final String source;

  const LiveTicker({required this.price, required this.source});
}

/// Stateless REST client consuming the GitHub Pages protocol snapshot and public BTC spot feeds.
class ProtocolApiService {
  ProtocolApiService({
    http.Client? client,
    this.parseInBackground = true,
  }) : _client = client ?? http.Client();

  final http.Client _client;
  final bool parseInBackground;

  Future<ProtocolState> fetchProtocolState() async {
    final uri = Uri.parse(
      '${AppConfig.protocolStateUrl}?t=${DateTime.now().millisecondsSinceEpoch}',
    );
    final response = await _client.get(uri, headers: {'Accept': 'application/json'}).timeout(
      const Duration(seconds: 12),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to load protocol state (HTTP ${response.statusCode})');
    }
    if (!parseInBackground) {
      return parseProtocolState(response.body);
    }
    return compute(parseProtocolState, response.body);
  }

  Future<LiveTicker?> fetchLiveTicker() async {
    try {
      final res = await _client
          .get(Uri.parse(AppConfig.binanceTickerUrl))
          .timeout(const Duration(seconds: 5));
      if (res.statusCode == 200) {
        final map = jsonDecode(res.body) as Map<String, dynamic>;
        final p = double.tryParse((map['price'] ?? '').toString());
        if (p != null && p > 0) return LiveTicker(price: p, source: 'BinanceVision');
      }
    } catch (_) {}

    try {
      final res = await _client
          .get(Uri.parse(AppConfig.coinbaseTickerUrl))
          .timeout(const Duration(seconds: 5));
      if (res.statusCode == 200) {
        final map = jsonDecode(res.body) as Map<String, dynamic>;
        final p = double.tryParse((map['price'] ?? '').toString());
        if (p != null && p > 0) return LiveTicker(price: p, source: 'Coinbase');
      }
    } catch (_) {}
    return null;
  }

  void dispose() => _client.close();
}
