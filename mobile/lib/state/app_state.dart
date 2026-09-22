import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import '../core/api_client.dart';
import '../core/models.dart';
import '../core/offline_queue.dart';
import '../core/realtime.dart';
import '../voice/voice_service.dart';
import '../voice/voice_utils.dart';

enum VoiceState { idle, listening, thinking, speaking }

/// One ChangeNotifier for auth + assistant. Screens read it with Provider.
class AppState extends ChangeNotifier {
  AppState({required this.api, required this.voice, required this.queue, FlutterLocalNotificationsPlugin? notifications})
      : _notifications = notifications,
        realtime = Realtime(api);

  final ApiClient api;
  final VoiceService voice;
  final OfflineQueue queue;
  final Realtime realtime;
  final FlutterLocalNotificationsPlugin? _notifications;

  bool signedIn = false;
  bool loading = true;
  bool connected = false;
  Map<String, dynamic>? user;
  final List<ChatMessage> messages = [];
  VoiceState voiceState = VoiceState.idle;
  String partial = '';
  String? error;
  String speechPref = 'auto'; // auto | ta-IN | en-IN
  bool muted = false;
  int syncTick = 0; // bumped whenever data changed elsewhere
  int queued = 0;

  String? _conversationId;
  String? _lastStyle;
  StreamSubscription? _evSub, _stSub;

  Future<void> bootstrap() async {
    signedIn = await api.store.read() != null;
    if (signedIn) {
      try {
        user = (await api.get('/auth/me')) as Map<String, dynamic>;
        await _startSession();
      } catch (_) {
        signedIn = false;
      }
    }
    loading = false;
    notifyListeners();
  }

  Future<void> signIn(String email, String password) async {
    await api.login(email, password);
    await bootstrap();
  }

  Future<void> signUp(String email, String password, String name) async {
    await api.register(email, password, name);
    await bootstrap();
  }

  Future<void> signOut() async {
    await realtime.stop();
    await api.store.write(null);
    signedIn = false;
    user = null;
    messages.clear();
    _conversationId = null;
    notifyListeners();
  }

  Future<void> _startSession() async {
    queued = (await queue.items()).length;
    try {
      final cfg = await api.get('/voice/config') as Map<String, dynamic>;
      voice.hints = {for (final e in (cfg['preferred_voice_hints'] as Map).entries) e.key as String: List<String>.from(e.value as List)};
    } catch (_) {}
    await realtime.start();
    _stSub = realtime.status.listen((c) {
      connected = c;
      notifyListeners();
      if (c) unawaited(flushQueue());
    });
    _evSub = realtime.events.listen(_onEvent);
  }

  void _onEvent(Map<String, dynamic> e) {
    switch (e['type']) {
      case 'sync':
        syncTick++;
        notifyListeners();
      case 'reminder.due':
        syncTick++;
        final text = e['text'] as String;
        messages.add(ChatMessage('system', '⏰ $text', style: e['style'] as String?));
        _notify(text);
        if (!muted) {
          final ta = e['style'] == 'ta';
          unawaited(voice.speak([SpeechSegment(text, ta ? 'ta' : 'en', '')]));
        }
        notifyListeners();
    }
  }

  void _notify(String text) {
    _notifications?.show(
      DateTime.now().millisecondsSinceEpoch % 100000,
      'Wensday',
      text,
      const NotificationDetails(
        android: AndroidNotificationDetails('reminders', 'Reminders', importance: Importance.high, priority: Priority.high),
        iOS: DarwinNotificationDetails(),
      ),
    );
  }

  // ------------------------------------------------------------ chat + voice
  Future<void> send(String text) async {
    final t = text.trim();
    if (t.isEmpty) return;
    error = null;
    partial = '';
    messages.add(ChatMessage('user', t));
    voiceState = VoiceState.thinking;
    notifyListeners();
    try {
      final j = await api.post('/chat', {'text': t, 'conversation_id': _conversationId}) as Map<String, dynamic>;
      final r = ChatReply.fromJson(j);
      _conversationId = r.conversationId;
      _lastStyle = r.style;
      messages.add(ChatMessage('assistant', r.reply, style: r.style, tier: r.tier));
      if (!muted) {
        voiceState = VoiceState.speaking;
        notifyListeners();
        await voice.speak(r.speech);
      }
    } on ApiException catch (e) {
      error = e.message;
    } catch (_) {
      // no connectivity: keep it on the device and replay when we're back online
      queued = await queue.add(t);
      messages.add(const ChatMessage('system', "You're offline. I've saved that and will do it as soon as we're connected."));
    } finally {
      voiceState = VoiceState.idle;
      notifyListeners();
    }
  }

  Future<void> flushQueue() async {
    final replies = await queue.flush(api, conversationId: _conversationId);
    queued = (await queue.items()).length;
    for (final j in replies) {
      final r = ChatReply.fromJson(j);
      _conversationId = r.conversationId;
      messages.add(ChatMessage('assistant', r.reply, style: r.style, tier: r.tier));
    }
    if (replies.isNotEmpty) syncTick++;
    notifyListeners();
  }

  Future<void> toggleListening() async {
    if (voiceState == VoiceState.speaking) {
      await voice.cancelSpeech(); // barge-in
      voiceState = VoiceState.idle;
    } else if (voiceState == VoiceState.listening) {
      await voice.stopListening();
      voiceState = VoiceState.idle;
    } else if (voiceState == VoiceState.idle) {
      voiceState = VoiceState.listening;
      partial = '';
      notifyListeners();
      await voice.listen(
        locale: recognitionLocale(speechPref, _lastStyle),
        onPartial: (p) {
          partial = p;
          notifyListeners();
        },
        onFinal: (text) => unawaited(send(stripWakeWord(text))),
      );
      return;
    }
    notifyListeners();
  }

  void setSpeechPref(String v) {
    speechPref = v;
    notifyListeners();
  }

  void setMuted(bool v) {
    muted = v;
    notifyListeners();
  }

  @override
  void dispose() {
    _evSub?.cancel();
    _stSub?.cancel();
    realtime.stop();
    super.dispose();
  }
}
