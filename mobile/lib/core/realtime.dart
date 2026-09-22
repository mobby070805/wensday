import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:web_socket_channel/web_socket_channel.dart';

import 'api_client.dart';

/// The single realtime socket: reminder pushes and cross-device sync events, with reconnect + backoff.
class Realtime {
  Realtime(this._api);
  final ApiClient _api;
  final _events = StreamController<Map<String, dynamic>>.broadcast();
  final _status = StreamController<bool>.broadcast();
  WebSocketChannel? _ch;
  StreamSubscription? _sub;
  Timer? _retry;
  int _attempt = 0;
  bool _stopped = true;

  Stream<Map<String, dynamic>> get events => _events.stream;
  Stream<bool> get status => _status.stream;

  Future<void> start() async {
    _stopped = false;
    await _open();
  }

  Future<void> stop() async {
    _stopped = true;
    _retry?.cancel();
    await _sub?.cancel();
    await _ch?.sink.close();
    _ch = null;
  }

  Future<void> _open() async {
    final uri = await _api.wsUri();
    if (uri == null || _stopped) return;
    try {
      final ch = WebSocketChannel.connect(uri);
      _ch = ch;
      await ch.ready;
      _attempt = 0;
      _status.add(true);
      _sub = ch.stream.listen(
        (data) {
          if (data is String) {
            try {
              _events.add(jsonDecode(data) as Map<String, dynamic>);
            } catch (_) {/* ignore malformed frame */}
          }
        },
        onDone: _lost,
        onError: (_) => _lost(),
      );
    } catch (_) {
      _lost();
    }
  }

  Future<void> _lost() async {
    _status.add(false);
    if (_stopped) return;
    // an expired access token closes the socket with 4401: one authenticated call refreshes it
    try {
      await _api.get('/auth/me');
    } catch (_) {}
    final delay = Duration(milliseconds: min(15000, 500 * pow(2, _attempt++).toInt()) + Random().nextInt(300));
    _retry = Timer(delay, _open);
  }
}
