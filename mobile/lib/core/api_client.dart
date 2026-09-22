import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.status, this.message);
  final int status;
  final String message;
  @override
  String toString() => message;
}

class Tokens {
  const Tokens(this.access, this.refresh);
  final String access;
  final String refresh;
}

/// Where tokens live. The app uses the platform keychain/keystore; tests use memory.
abstract class TokenStore {
  Future<Tokens?> read();
  Future<void> write(Tokens? tokens);
}

class MemoryTokenStore implements TokenStore {
  MemoryTokenStore([this.value]);
  Tokens? value;
  @override
  Future<Tokens?> read() async => value;
  @override
  Future<void> write(Tokens? tokens) async => value = tokens;
}

/// REST client with transparent, single-flight token refresh.
///
/// The server rotates refresh tokens and treats a replayed one as theft (revoking every session),
/// so parallel 401s must share ONE refresh call rather than each spending the refresh token.
class ApiClient {
  ApiClient({
    required this.baseUrl,
    required this.store,
    http.Client? client,
    this.onSignedOut,
  }) : _http = client ?? http.Client();

  final String baseUrl;
  final TokenStore store;
  final void Function()? onSignedOut;
  final http.Client _http;
  Future<bool>? _refreshing;

  Future<bool> _refresh() {
    return _refreshing ??= () async {
      try {
        final current = await store.read();
        if (current == null) return false;
        final res = await _http.post(
          Uri.parse('$baseUrl/auth/refresh'),
          headers: {'content-type': 'application/json'},
          body: jsonEncode({'refresh_token': current.refresh}),
        );
        if (res.statusCode != 200) return false;
        final j = jsonDecode(res.body) as Map<String, dynamic>;
        await store.write(Tokens(j['access_token'] as String, j['refresh_token'] as String));
        return true;
      } catch (_) {
        return false;
      } finally {
        _refreshing = null;
      }
    }();
  }

  Future<http.Response> _send(String method, String path, Object? body, bool auth) async {
    final headers = <String, String>{};
    if (body != null) headers['content-type'] = 'application/json';
    if (auth) {
      final t = await store.read();
      if (t != null) headers['authorization'] = 'Bearer ${t.access}';
    }
    final req = http.Request(method, Uri.parse('$baseUrl$path'))..headers.addAll(headers);
    if (body != null) req.body = jsonEncode(body);
    return http.Response.fromStream(await _http.send(req));
  }

  Future<dynamic> request(String method, String path, {Object? body, bool auth = true}) async {
    var res = await _send(method, path, body, auth);
    if (res.statusCode == 401 && auth) {
      if (await _refresh()) {
        res = await _send(method, path, body, auth);
      } else {
        await store.write(null);
        onSignedOut?.call();
      }
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      var detail = res.reasonPhrase ?? 'Request failed';
      try {
        final j = jsonDecode(utf8.decode(res.bodyBytes));
        final d = j is Map ? j['detail'] : null;
        detail = d is String ? d : jsonEncode(d ?? j);
      } catch (_) {}
      throw ApiException(res.statusCode, detail);
    }
    if (res.statusCode == 204 || res.bodyBytes.isEmpty) return null;
    return jsonDecode(utf8.decode(res.bodyBytes)); // utf8 explicitly: Tamil text must not be decoded as latin-1
  }

  Future<dynamic> get(String path) => request('GET', path);
  Future<dynamic> post(String path, [Object? body]) => request('POST', path, body: body ?? {});
  Future<dynamic> patch(String path, Object body) => request('PATCH', path, body: body);
  Future<dynamic> delete(String path) => request('DELETE', path);

  Future<Tokens> login(String email, String password) async {
    final j = await request('POST', '/auth/login', body: {'email': email, 'password': password}, auth: false);
    final t = Tokens(j['access_token'] as String, j['refresh_token'] as String);
    await store.write(t);
    return t;
  }

  Future<Tokens> register(String email, String password, String name) async {
    final j = await request('POST', '/auth/register', body: {'email': email, 'password': password, 'name': name}, auth: false);
    final t = Tokens(j['access_token'] as String, j['refresh_token'] as String);
    await store.write(t);
    return t;
  }

  Future<Uri?> wsUri() async {
    final t = await store.read();
    if (t == null) return null;
    final base = baseUrl.replaceFirst(RegExp('^http'), 'ws');
    return Uri.parse('$base/ws').replace(queryParameters: {'token': t.access});
  }
}
