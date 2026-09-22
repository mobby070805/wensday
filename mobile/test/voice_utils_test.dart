import 'package:flutter_test/flutter_test.dart';
import 'package:wensday/voice/voice_utils.dart';

void main() {
  group('wake word', () {
    const cases = {
      'Wensday, nalaiku 9 mani meeting remind pannu': 'nalaiku 9 mani meeting remind pannu',
      'wednesday remind me at 5': 'remind me at 5', // recognisers hear "Wednesday"
      'Hey Wensday: saptiya?': 'saptiya?',
      'வென்ஸ்டே நாளை மீட்டிங்': 'நாளை மீட்டிங்',
      'nalaiku meeting': 'nalaiku meeting',
    };
    cases.forEach((input, expected) => test('strips "$input"', () => expect(stripWakeWord(input), expected)));

    test('detects only when addressed', () {
      expect(hasWakeWord('Wensday, hello'), isTrue);
      expect(hasWakeWord('ok so wensday what time is it'), isTrue);
      expect(hasWakeWord('we talked on a rainy day'), isFalse);
      expect(hasWakeWord(''), isFalse);
    });
  });

  group('voice selection', () {
    const voices = [
      VoiceInfo('Valluvar', 'ta-IN'),
      VoiceInfo('Pallavi', 'ta-IN'),
      VoiceInfo('David', 'en-US'),
      VoiceInfo('Neerja', 'en-IN'),
      VoiceInfo('Google UK English Female', 'en-GB'),
    ];
    test('prefers the female Tamil voice', () => expect(pickVoice(voices, 'ta')?.name, 'Pallavi'));
    test('prefers en-IN for English', () => expect(pickVoice(voices, 'en')?.name, 'Neerja'));
    test('accepts underscore locales from Android', () => expect(pickVoice(const [VoiceInfo('X', 'ta_IN')], 'ta')?.name, 'X'));
    test('null when no voice for the language', () => expect(pickVoice(const [VoiceInfo('x', 'fr-FR')], 'ta'), isNull));
    test('Tamil is spoken slightly slower', () => expect(rateFor('ta'), lessThan(rateFor('en'))));
  });

  test('recognition locale', () {
    expect(recognitionLocale('auto', null), 'en-IN');
    expect(recognitionLocale('auto', 'tg'), 'en-IN');
    expect(recognitionLocale('auto', 'ta'), 'ta-IN');
    expect(recognitionLocale('ta-IN', 'en'), 'ta-IN');
  });
}
