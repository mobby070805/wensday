# Phase 1 — Requirements & architecture · **100 %**

**Delivered:** [requirements.md](../requirements.md) (20 functional requirements mapped 1:1 to the brief, 8 language requirements, voice, non-functional, assumptions) · [architecture.md](../architecture.md) (context diagram, 8 design decisions, layering, turn lifecycle, security model, topology).

**Key decisions taken without asking**
- D1 the language layer is *native* (lexicon of Tamil-script ≡ Tanglish ≡ English), not translate-then-understand — this is what enables offline mode.
- D2 two-tier understanding: deterministic NLU first, LLM for the rest, sharing one tool registry (D3).
- D5 confirmation gate for external side effects (email).
- D7 portable persistence (SQLite in dev/test, PostgreSQL in prod) so CI needs no services.

**Assumptions to confirm with the product owner:** default LLM provider (Anthropic) · browser-native STT/TTS as the default with server providers optional · "call pannu" hands off to the device dialer (no telephony) · smart-home/payments out of scope.

**Deviations from the original brief:** none. Note that "real-time STT/TTS" is delivered as client-side real-time (Web Speech / OS) plus utterance-based server providers, not server-side streaming recognition.
