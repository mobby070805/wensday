import 'package:flutter/material.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'core/api_client.dart';
import 'core/offline_queue.dart';
import 'state/app_state.dart';
import 'ui/home_screen.dart';
import 'ui/login_screen.dart';
import 'voice/voice_service.dart';

/// Override at build time: flutter run --dart-define=API_URL=https://api.example.com/api/v1
/// (10.0.2.2 is the Android emulator's alias for the host machine.)
const apiUrl = String.fromEnvironment('API_URL', defaultValue: 'http://10.0.2.2:8000/api/v1');

class SecureTokenStore implements TokenStore {
  static const _s = FlutterSecureStorage();
  @override
  Future<Tokens?> read() async {
    final a = await _s.read(key: 'access'), r = await _s.read(key: 'refresh');
    return a == null || r == null ? null : Tokens(a, r);
  }

  @override
  Future<void> write(Tokens? t) async {
    if (t == null) {
      await _s.delete(key: 'access');
      await _s.delete(key: 'refresh');
    } else {
      await _s.write(key: 'access', value: t.access);
      await _s.write(key: 'refresh', value: t.refresh);
    }
  }
}

class PrefsStore implements KeyValueStore {
  PrefsStore(this._p);
  final SharedPreferences _p;
  @override
  Future<String?> getString(String key) async => _p.getString(key);
  @override
  Future<void> setString(String key, String value) => _p.setString(key, value);
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final notifications = FlutterLocalNotificationsPlugin();
  await notifications.initialize(const InitializationSettings(
    android: AndroidInitializationSettings('@mipmap/ic_launcher'),
    iOS: DarwinInitializationSettings(),
  ));
  final prefs = await SharedPreferences.getInstance();
  final state = AppState(
    api: ApiClient(baseUrl: apiUrl, store: SecureTokenStore()),
    voice: VoiceService(),
    queue: OfflineQueue(PrefsStore(prefs)),
    notifications: notifications,
  );
  runApp(ChangeNotifierProvider.value(value: state..bootstrap(), child: const WensdayApp()));
}

class WensdayApp extends StatelessWidget {
  const WensdayApp({super.key});

  @override
  Widget build(BuildContext context) {
    const teal = Color(0xFF38D9C8);
    return MaterialApp(
      title: 'Wensday',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(seedColor: teal, brightness: Brightness.dark, surface: const Color(0xFF0D1424)),
        scaffoldBackgroundColor: const Color(0xFF070B14),
        // Tamil glyphs need a font with Tamil coverage; the system font handles it, Noto Sans Tamil is the fallback
        fontFamilyFallback: const ['Noto Sans Tamil'],
      ),
      home: Consumer<AppState>(
        builder: (_, s, __) => s.loading
            ? const Scaffold(body: Center(child: CircularProgressIndicator()))
            : s.signedIn
                ? const HomeScreen()
                : const LoginScreen(),
      ),
    );
  }
}
