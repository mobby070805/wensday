import 'dart:convert';

import 'api_client.dart';

/// Minimal async key-value store (SharedPreferences in the app, a map in tests).
abstract class KeyValueStore {
  Future<String?> getString(String key);
  Future<void> setString(String key, String value);
}

class MemoryKeyValueStore implements KeyValueStore {
  final Map<String, String> _m = {};
  @override
  Future<String?> getString(String key) async => _m[key];
  @override
  Future<void> setString(String key, String value) async => _m[key] = value;
}

class QueuedUtterance {
  const QueuedUtterance(this.text, this.at);
  final String text;
  final DateTime at;
  Map<String, dynamic> toJson() => {'text': text, 'at': at.toIso8601String()};
  factory QueuedUtterance.fromJson(Map<String, dynamic> j) => QueuedUtterance(j['text'] as String, DateTime.parse(j['at'] as String));
}

/// Offline fallback for the phone: when there is no connectivity, what the user said is kept on
/// the device and replayed, in order, once the connection returns — nothing is silently lost.
///
/// (Full on-device understanding without any server is on the roadmap; today the *server* also has
/// an offline rule-based engine for when only the LLM is unreachable.)
class OfflineQueue {
  OfflineQueue(this._store, {this.maxItems = 50});
  final KeyValueStore _store;
  final int maxItems;
  static const _key = 'wensday.offline_queue';

  Future<List<QueuedUtterance>> items() async {
    final raw = await _store.getString(_key);
    if (raw == null || raw.isEmpty) return [];
    try {
      return [for (final j in jsonDecode(raw) as List) QueuedUtterance.fromJson(j as Map<String, dynamic>)];
    } catch (_) {
      return []; // corrupt state must never crash the app
    }
  }

  Future<void> _save(List<QueuedUtterance> list) => _store.setString(_key, jsonEncode([for (final q in list) q.toJson()]));

  Future<int> add(String text, {DateTime? now}) async {
    final list = await items();
    list.add(QueuedUtterance(text, now ?? DateTime.now()));
    final trimmed = list.length > maxItems ? list.sublist(list.length - maxItems) : list; // drop oldest
    await _save(trimmed);
    return trimmed.length;
  }

  /// Replay in order. Stops at the first failure so ordering is preserved; returns replies for what was sent.
  Future<List<Map<String, dynamic>>> flush(ApiClient api, {String? conversationId}) async {
    final list = await items();
    final replies = <Map<String, dynamic>>[];
    var sent = 0;
    for (final q in list) {
      try {
        final r = await api.post('/chat', {'text': q.text, 'conversation_id': conversationId}) as Map<String, dynamic>;
        replies.add(r);
        conversationId = r['conversation_id'] as String?;
        sent++;
      } on ApiException catch (e) {
        if (e.status >= 500 || e.status == 429) break; // server trouble: keep the rest queued
        sent++; // a 4xx will never succeed on retry: drop it instead of blocking the queue forever
      } catch (_) {
        break; // still offline
      }
    }
    await _save(list.sublist(sent));
    return replies;
  }
}
