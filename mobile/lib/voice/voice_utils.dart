/// Pure voice helpers (no platform plugins) so they are unit-testable. Mirrors web/src/lib/voice-utils.ts.
library;

const _wakeForms = <String>[
  'hey wensday', 'ok wensday', 'wensday', 'wednesday', 'vensday', 'wendsday', 'winsday', 'wenzday',
  'வென்ஸ்டே', 'வெனஸ்டே', 'வெட்னஸ்டே',
];

bool hasWakeWord(String text) {
  final t = text.toLowerCase().trim();
  return _wakeForms.any((w) => t.startsWith(w) || t.contains(' $w'));
}

/// "Wensday, nalaiku 9 mani…" -> "nalaiku 9 mani…". Recognisers often hear "Wednesday".
String stripWakeWord(String text) {
  final t = text.trim();
  final low = t.toLowerCase();
  final forms = [..._wakeForms]..sort((a, b) => b.length.compareTo(a.length));
  for (final w in forms) {
    if (low.startsWith(w)) return t.substring(w.length).replaceFirst(RegExp(r'^[\s,.:;!-]+'), '');
  }
  return t;
}

/// Speech-recognition locale for the next utterance.
String recognitionLocale(String pref, String? lastStyle) {
  if (pref != 'auto') return pref;
  return lastStyle == 'ta' ? 'ta-IN' : 'en-IN'; // en-IN copes best with Tanglish
}

class VoiceInfo {
  const VoiceInfo(this.name, this.locale);
  final String name;
  final String locale;
}

const _female = ['female', 'pallavi', 'neerja', 'heera', 'priya', 'kalpana', 'veena', 'lekha', 'samantha', 'zira'];
const _male = ['male', 'valluvar', 'prabhat', 'hemant', 'ravi', 'rishi', 'david', 'mark'];

/// Most suitable *female* voice for [lang] ('ta' | 'en'): hints > known female names > not-known-male > any.
VoiceInfo? pickVoice(List<VoiceInfo> voices, String lang, {List<String> hints = const []}) {
  var pool = voices.where((v) => v.locale.toLowerCase().replaceAll('_', '-').startsWith(lang)).toList();
  if (lang == 'en') {
    final inIndia = pool.where((v) => v.locale.toLowerCase().replaceAll('_', '-') == 'en-in').toList();
    if (inIndia.isNotEmpty) pool = inIndia;
  }
  if (pool.isEmpty) return null;
  bool has(VoiceInfo v, List<String> list) => list.any((h) => v.name.toLowerCase().contains(h.toLowerCase()));
  for (final test in <bool Function(VoiceInfo)>[(v) => has(v, hints), (v) => has(v, _female), (v) => !has(v, _male)]) {
    for (final v in pool) {
      if (test(v)) return v;
    }
  }
  return pool.first;
}

double rateFor(String lang, [double base = 0.5]) => (lang == 'ta' ? base * 0.95 : base).clamp(0.1, 1.0).toDouble();
