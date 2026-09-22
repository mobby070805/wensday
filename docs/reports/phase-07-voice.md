# Phase 7 — Voice system · **70 %**

**Delivered:** female-voice selection per language (Pallavi/Neerja hints, en-IN preferred, known-male voices avoided) · **mixed-language voice output** (Tamil script → Tamil voice; Tanglish words → transliterated to Tamil script → Tamil voice; English → en-IN voice; numbers stay with neighbours) · SSML generation with per-run `<voice>`/`<lang>` · provider abstraction with `browser` (client-side, default), Whisper-compatible and Azure implementations · Azure STT recognises `ta-IN` and `en-IN` in parallel and keeps the more confident result (an answer to code-switching without the streaming SDK) · Whisper biased with a Tanglish prompt · realtime socket voice turn (audio frames → transcript → reply → streamed audio, 16 KiB chunks) with **barge-in** cancel · wake word "Wensday" incl. common mis-hearings ("Wednesday", Tamil-script forms) on web and mobile · voice-command grammar = the deterministic NLU (works offline).

**Tests:** `test_voice.py` 28 (transliteration properties, run splitting, SSML validity, provider request shapes, a full audio-in → audio-out socket round-trip with fake STT/TTS, cancel/error paths) + web/Dart wake-word and voice-picking tests.

**Bug found:** English names ("Jerry") were transliterated into Tamil because their phonetic skeleton collided with the Tanglish word "seri".

**Why 70 %:** no real audio has ever passed through the system.
- STT/TTS providers are verified only against mocked HTTP (request/response shapes), not real Azure/Whisper.
- The Tanglish→Tamil transliterator is **approximate by design** and has not been heard by a Tamil speaker; pronunciation quality is unknown.
- "Real-time" recognition is real-time only on the client (Web Speech / OS). Server-side STT is utterance-based (client-side silence detection, then upload), not streaming.
- Wake word is text-matching on recogniser output while listening, not an acoustic keyword spotter (higher battery use, misses when the recogniser mishears). A proper on-device wake-word engine is on the roadmap.
- A "natural South-Indian accent" depends entirely on the voices installed on the device or configured at the provider.
