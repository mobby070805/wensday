import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wensday/core/api_client.dart';
import 'package:wensday/core/offline_queue.dart';

ApiClient _api(Future<http.Response> Function(http.Request) h) =>
    ApiClient(baseUrl: 'http://api', store: MemoryTokenStore(const Tokens('A', 'R')), client: MockClient(h));

http.Response _chat(String cid) => http.Response(
      jsonEncode({'conversation_id': cid, 'reply': 'ok', 'intent': 'x', 'style': 'en', 'tier': 'rules', 'speech': [], 'data': {}}),
      200,
    );

void main() {
  test('keeps what the user said while offline, oldest dropped past the limit', () async {
    final q = OfflineQueue(MemoryKeyValueStore(), maxItems: 3);
    for (final t in ['a', 'b', 'c', 'd']) {
      await q.add(t);
    }
    expect((await q.items()).map((i) => i.text), ['b', 'c', 'd']);
  });

  test('replays in order and keeps the same conversation', () async {
    final q = OfflineQueue(MemoryKeyValueStore());
    await q.add('one');
    await q.add('two');
    final seen = <Map<String, dynamic>>[];
    final replies = await q.flush(_api((r) async {
      seen.add(jsonDecode(r.body) as Map<String, dynamic>);
      return _chat('conv-1');
    }));
    expect(seen.map((b) => b['text']), ['one', 'two']);
    expect(seen[1]['conversation_id'], 'conv-1');
    expect(replies, hasLength(2));
    expect(await q.items(), isEmpty);
  });

  test('stops at the first network failure and keeps the rest, in order', () async {
    final q = OfflineQueue(MemoryKeyValueStore());
    for (final t in ['one', 'two', 'three']) {
      await q.add(t);
    }
    var n = 0;
    await q.flush(_api((r) async {
      if (++n == 2) throw Exception('offline again');
      return _chat('c');
    }));
    expect((await q.items()).map((i) => i.text), ['two', 'three']);
  });

  test('a permanently rejected message (4xx) does not block the queue forever', () async {
    final q = OfflineQueue(MemoryKeyValueStore());
    await q.add('bad');
    await q.add('good');
    await q.flush(_api((r) async => (jsonDecode(r.body) as Map)['text'] == 'bad' ? http.Response(jsonEncode({'detail': 'invalid'}), 422) : _chat('c')));
    expect(await q.items(), isEmpty);
  });

  test('server trouble (5xx) keeps everything queued', () async {
    final q = OfflineQueue(MemoryKeyValueStore());
    await q.add('one');
    await q.flush(_api((r) async => http.Response('boom', 503)));
    expect(await q.items(), hasLength(1));
  });

  test('corrupt stored state never crashes the app', () async {
    final store = MemoryKeyValueStore();
    await store.setString('wensday.offline_queue', '{not json');
    expect(await OfflineQueue(store).items(), isEmpty);
  });
}
