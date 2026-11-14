import '../../domain/models/protocol_state.dart';
import '../services/protocol_api_service.dart';

class ProtocolRepository {
  ProtocolRepository({required ProtocolApiService apiService}) : _api = apiService;

  final ProtocolApiService _api;
  ProtocolState? _cached;

  ProtocolState? get cachedState => _cached;

  Future<ProtocolState> refreshState() async {
    final state = await _api.fetchProtocolState();
    _cached = state;
    return state;
  }

  Future<LiveTicker?> refreshLivePrice() => _api.fetchLiveTicker();

  void dispose() => _api.dispose();
}
