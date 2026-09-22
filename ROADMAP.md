# Wensday — Product Roadmap

**Legend:** ✅ built and verified here · 🟡 built, only partly verifiable here · 🟠 written but never executed

Completion % is an honest estimate of *shippable* work in each phase, not lines written. Details, bugs found and gaps per phase are in [docs/reports/](docs/reports).

| # | Phase | Status | % | Verified by |
|---|---|:-:|--:|---|
| 1 | Requirements & architecture | ✅ | 100 | reviewed docs |
| 2 | Repository layout | ✅ | 100 | — |
| 3 | Backend (API, DB, auth, agent, services) | ✅ | 90 | 312 backend tests; real uvicorn smoke test |
| 4 | Web frontend (Next.js) | 🟡 | 80 | typecheck, 25 unit tests, production build — **never opened in a browser** |
| 5 | Mobile app (Flutter) | 🟠 | 45 | ~25 Dart tests written — **never compiled** (no SDK) |
| 6 | Memory engine | ✅ | 90 | 39 tests (hashing embedder; real embeddings/Qdrant untested) |
| 7 | Voice system | 🟡 | 70 | mocked providers + socket round-trip — **no real audio** |
| 8 | Integrations & plugins | 🟡 | 75 | mocked Google — **never contacted real services** |
| 9 | Testing suite | ✅ | 85 | see [testing.md](docs/testing.md) |
| 10 | Deployment | 🟠 | 60 | YAML parsed — **never built or applied** (no Docker/cluster) |

**Overall ≈ 80 %.** The core product — the trilingual conversation engine, memory, API — is solid and heavily tested. What remains is mostly *contact with reality*: real browsers, real phones, real audio, real providers, real clusters, and native-speaker review of the Tamil.

## Before the first user (must-do)
1. **Native Tamil review** of `backend/app/i18n/persona.py` (all `ta` replies), `backend/app/voice/translit.py` and the Tanglish phrasings; adjust the lexicon from real utterances.
2. **Try it in a browser with a microphone** (Chrome/Edge): voice loop, barge-in, hands-free, reminder push.
3. **Run the Flutter app** (`flutter create .`, analyze, test, run on a device) and fix API drift.
4. **Introduce Alembic migrations** and run against PostgreSQL; set `AUTO_CREATE_TABLES=false`.
5. **Stand up staging**: build the images, apply `deploy/k8s`, verify Redis fan-out (worker → API pods → sockets).
6. **Point at real providers** with keys: Anthropic, Azure Speech (or Whisper), Google OAuth — and listen to the result.
7. `git init`, root `.gitignore`, commit `web/package-lock.json`.

## Next (v1.1 — hardening)
- Playwright browser E2E and a mobile integration test.
- httpOnly-cookie sessions for the web app; password reset, email verification, account deletion.
- Real embedding model + Qdrant in CI (service containers); PostgreSQL in CI.
- FCM/APNs push for reminders when the app is closed; mobile: dialer hand-off (`url_launcher`), Google sign-in, remaining screens.
- Web UI for documents, meeting summaries, inbox summary and workflow editor.
- Prometheus alert rules, structured JSON logging, tracing.

## Future enhancement roadmap
| Version | Theme | Items |
|---|---|---|
| **v1.2** | Proactive & personal | Proactive suggestions (commute, meeting prep, gentle nudges from the coaching service); on-device wake word (openWakeWord/Porcupine); NLU labelled-data benchmark and active learning from corrections; Chennai-dialect fine-tuned ASR; richer Tamil time/number grammar |
| **v1.3** | Reach | WhatsApp and Slack channels; telephony/dialer plugin; smart-home plugins; Outlook/Microsoft 365; shared family/team workspaces |
| **v2.0** | Autonomy | On-device small LLM + on-device NLU port for full offline reasoning on mobile; multi-step agents/workflows with human-in-the-loop approvals; sandboxed, signed plugin marketplace (process isolation); custom-trained female Tamil–English voice |
