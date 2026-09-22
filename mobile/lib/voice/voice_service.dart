import 'dart:async';

import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../core/models.dart';
import 'voice_utils.dart';

/// On-device speech: recognition via the OS engine (real-time partial results, works offline on
/// most devices) and synthesis via the OS TTS with a female voice per language run.
class VoiceService {
  final SpeechToText _stt = SpeechToText();
  final FlutterTts _tts = FlutterTts();
  bool _ready = false;
  List<VoiceInfo> _voices = const [];
  Map<String, List<String>> hints = const {};

  Future<bool> init() async {
    if (_ready) return true;
    _ready = await _stt.initialize();
    try {
      final raw = await _tts.getVoices as List<dynamic>?;
      _voices = [
        for (final v in raw ?? const [])
          if (v is Map) VoiceInfo('${v['name']}', '${v['locale']}'),
      ];
      await _tts.awaitSpeakCompletion(true);
    } catch (_) {
      _voices = const [];
    }
    return _ready;
  }

  bool get isListening => _stt.isListening;

  Future<void> listen({
    required String locale,
    required void Function(String partial) onPartial,
    required void Function(String text) onFinal,
  }) async {
    if (!await init()) return;
    await _stt.listen(
      localeId: locale.replaceAll('-', '_'),
      listenOptions: SpeechListenOptions(partialResults: true, cancelOnError: true),
      pauseFor: const Duration(seconds: 2),
      onResult: (r) => r.finalResult ? onFinal(r.recognizedWords) : onPartial(r.recognizedWords),
    );
  }

  Future<void> stopListening() => _stt.stop();

  /// Speak each language run with the right voice (Tamil script / Tanglish -> Tamil voice, English -> en-IN).
  Future<void> speak(List<SpeechSegment> segments, {double rate = 0.5}) async {
    for (final seg in segments) {
      final v = pickVoice(_voices, seg.lang, hints: hints[seg.lang == 'ta' ? 'ta-IN' : 'en-IN'] ?? const []);
      if (v != null) await _tts.setVoice({'name': v.name, 'locale': v.locale});
      await _tts.setLanguage(v?.locale ?? (seg.lang == 'ta' ? 'ta-IN' : 'en-IN'));
      await _tts.setSpeechRate(rateFor(seg.lang, rate));
      await _tts.setPitch(1.05);
      await _tts.speak(seg.text);
    }
  }

  /// Barge-in.
  Future<void> cancelSpeech() => _tts.stop();
}
