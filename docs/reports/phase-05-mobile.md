# Phase 5 — Mobile (Flutter) · **45 %** (written, unverified)

**Delivered** (`mobile/`, ~1.2 k lines Dart): API client with single-flight token refresh and UTF-8-safe decoding · secure token storage · realtime socket with backoff · on-device speech recognition and female-voice TTS with per-language runs and barge-in · assistant screen with mic orb, transcript, typed input · task/reminder/note/goal lists (add, complete, delete, pull-to-refresh, live refresh on sync events) · local notifications for reminders · **offline queue** (persist, replay in order, drop rejected 4xx, keep on 5xx, corrupt-state safe) · ~25 Dart tests.

**Why 45 %:** nothing has been compiled, analysed or run — there was no Flutter SDK in the build environment. The code follows current package APIs from memory of their docs and may need small fixes on first `flutter analyze`. Setup steps (native project generation, permissions) are in [mobile.md](../mobile.md).

**Not built yet:** push notifications when the app is closed (FCM/APNs) · on-device NLU for true offline understanding · Google sign-in button · dashboard/plugins/settings/memory/calendar screens · wake-word listening · widget/lock-screen surfaces · store packaging.
