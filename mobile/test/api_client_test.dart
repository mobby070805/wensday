import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wensday/core/api_client.dart';

http.Response _json(int code, Object body) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), code, headers: {'content-type': 'application/json; charset=utf-8'});

void main() {
  test('sends the bearer token and a JSON body', () async {
    late http.Request seen;
    final api = ApiClient(
      baseUrl: 'http://api',
      store: MemoryTokenStore(const Tokens('A', 'R')),
      client: MockClient((r) async {
        seen = r;
        return _json(200, {'ok': true});
      }),
    );
    await api.post('/tasks', {'title': 'x'});
    expect(seen.url.toString(), 'http://api/tasks');
    expect(seen.headers['authorization'], 'Bearer A');
    expect(jsonDecode(seen.body), {'title': 'x'});
  });

  test('refreshes once on 401, stores the rotated pair and retries', () async {
    final store = MemoryTokenStore(const Tokens('old', 'R1'));
    final api = ApiClient(
      baseUrl: 'http://api',
      store: store,
      client: MockClient((r) async {
        if (r.url.path.endsWith('/auth/refresh')) return _json(200, {'access_token': 'new', 'refresh_token': 'R2'});
        return r.headers['authorization'] == 'Bearer new' ? _json(200, {'ok': 1}) : _json(401, {'detail': 'expired'});
      }),
    );
    expect(await api.get('/tasks'), {'ok': 1});
    expect(store.value?.access, 'new');
    expect(store.value?.refresh, 'R2');
  });

  test('parallel 401s share ONE refresh (a replayed refresh token would revoke every session)', () async {
    var refreshes = 0;
    final api = ApiClient(
      baseUrl: 'http://api',
      store: MemoryTokenStore(const Tokens('old', 'R1')),
      client: MockClient((r) async {
        if (r.url.path.endsWith('/auth/refresh')) {
          refreshes++;
          await Future<void>.delayed(const Duration(milliseconds: 20));
          return _json(200, {'access_token': 'new', 'refresh_token': 'R2'});
        }
        return r.headers['authorization'] == 'Bearer new' ? _json(200, <String>[]) : _json(401, {'detail': 'expired'});
      }),
    );
    await Future.wait([api.get('/tasks'), api.get('/notes'), api.get('/goals')]);
    expect(refreshes, 1);
  });

  test('signs out when the refresh fails', () async {
    var signedOut = false;
    final store = MemoryTokenStore(const Tokens('old', 'R1'));
    final api = ApiClient(
      baseUrl: 'http://api',
      store: store,
      onSignedOut: () => signedOut = true,
      client: MockClient((r) async => _json(401, {'detail': 'nope'})),
    );
    await expectLater(api.get('/tasks'), throwsA(isA<ApiException>()));
    expect(store.value, isNull);
    expect(signedOut, isTrue);
  });

  test('decodes Tamil text as UTF-8', () async {
    final api = ApiClient(
      baseUrl: 'http://api',
      store: MemoryTokenStore(const Tokens('A', 'R')),
      client: MockClient((r) async => _json(200, {'reply': 'சரி, நாளை காலை 9:00 மணிக்கு'})),
    );
    expect((await api.get('/x'))['reply'], 'சரி, நாளை காலை 9:00 மணிக்கு');
  });

  test('turns FastAPI errors into ApiException and handles 204', () async {
    final api = ApiClient(
      baseUrl: 'http://api',
      store: MemoryTokenStore(const Tokens('A', 'R')),
      client: MockClient((r) async => r.method == 'DELETE' ? http.Response('', 204) : _json(422, {'detail': 'title too short'})),
    );
    await expectLater(
      api.post('/tasks', {}),
      throwsA(isA<ApiException>().having((e) => e.status, 'status', 422).having((e) => e.message, 'message', 'title too short')),
    );
    expect(await api.delete('/tasks/1'), isNull);
  });

  test('builds the realtime URL', () async {
    final api = ApiClient(baseUrl: 'https://api.example.com/api/v1', store: MemoryTokenStore(const Tokens('a b', 'R')));
    expect((await api.wsUri()).toString(), 'wss://api.example.com/api/v1/ws?token=a+b');
    expect(await ApiClient(baseUrl: 'http://x', store: MemoryTokenStore()).wsUri(), isNull);
  });
}
