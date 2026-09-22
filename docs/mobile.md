# Mobile app (Flutter)

> **Status: written, never compiled.** No Flutter SDK was available when this was built, so nothing here has been through `flutter analyze` or `flutter test`. Treat the first `flutter pub get && flutter analyze` as part of setup and expect to fix small API-drift issues in the plugin packages (`speech_to_text`, `flutter_tts`, `flutter_local_notifications`).

## One-time platform setup
The repo contains `lib/`, `test/`, `pubspec.yaml`. Generate the native projects, then add permissions:

```bash
cd mobile
flutter create . --platforms=android,ios --project-name wensday --org com.wensday
flutter pub get && flutter analyze && flutter test
```

**Android** — `android/app/src/main/AndroidManifest.xml`, inside `<manifest>`:
```xml
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.RECORD_AUDIO"/>
<uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>
<queries><intent><action android:name="android.speech.RecognitionService"/></intent></queries>
```
Set `minSdkVersion 21`. For plain-HTTP dev servers add `android:usesCleartextTraffic="true"` to `<application>` (dev only).

**iOS** — `ios/Runner/Info.plist`:
```xml
<key>NSMicrophoneUsageDescription</key><string>Wensday listens when you tap the mic.</string>
<key>NSSpeechRecognitionUsageDescription</key><string>Wensday turns your speech into text.</string>
```

## Run
```bash
flutter run --dart-define=API_URL=http://10.0.2.2:8000/api/v1     # Android emulator → host machine
flutter run --dart-define=API_URL=https://api.example.com/api/v1  # real device / production
```

## What it does
- Same account, same data: talks to the same REST API and realtime socket as the web app.
- **Voice:** OS speech recognition (real-time partial results; `en_IN` by default, `ta_IN` once you speak Tamil, or pick in code via `speechPref`) and OS text-to-speech with the best female voice per language run; tap the orb while it speaks to interrupt.
- **Reminders:** delivered over the socket and shown as local notifications while the app is running.
- **Offline queue:** if a message can't be sent, it is stored on the device and replayed in order when the socket reconnects (`lib/core/offline_queue.dart`, unit-tested).
- Tokens live in the platform keychain/keystore (`flutter_secure_storage`), never in plain preferences.

## Known gaps
- **No push notifications when the app is closed** — reminders arrive only while the socket is connected. FCM/APNs delivery (the `devices` table already stores push tokens) is the next step.
- **No on-device NLU**: while offline, commands are queued rather than understood. (The *server* has an offline rule engine for when only the LLM is down.)
- No Google sign-in button yet (email/password only); no wake-word listening on mobile; dashboard/plugins/settings screens are web-only for now.
- Tamil voice availability depends on the device (install a Tamil TTS voice in system settings).
