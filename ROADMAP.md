# Wensday — Product Roadmap

**Legend:** ✅ built and verified here · 🟡 built, only partly verifiable here · 🟠 written but never executed

Completion % is an honest estimate of *shippable* work in each phase, not lines written, and moves only when new work in that phase was actually run and verified in this environment. Details, bugs found and gaps per phase are in [docs/reports/](docs/reports).

| # | Phase | Status | % | Verified by |
|---|---|:-:|--:|---|
| 1 | Requirements & architecture | ✅ | 100 | reviewed docs |
| 2 | Repository layout | ✅ | 100 | — |
| 3 | Backend (API, DB, auth, agent, services) | ✅ | 95 | 340 backend tests (350 with live Postgres+Redis reachable); real uvicorn smoke test; **Alembic migrations run against a real PostgreSQL 16.4 server** (not just SQLite/offline SQL); **Redis resilience proven against a real, genuinely killed-and-restarted `redis-server`** — found and fixed a real RESP3/HELLO compatibility bug; websocket hardening; security response headers |
| 4 | Web frontend (Next.js) | ✅ | 85 | typecheck, 25 unit tests, production build, **and now 5 real-Chromium Playwright E2E tests against the real production build + real backend** — found and fixed a real crash-on-chat-send bug. Voice/microphone remains unverified (no real mic in any automated environment). |
| 5 | Mobile app (Flutter) | 🟠 | 45 | ~25 Dart tests written — **never compiled** (no SDK) |
| 6 | Memory engine | ✅ | 92 | 41 tests, including **real on-disk persistence across a simulated process restart** (file-backed SQLite, not `:memory:`) |
| 7 | Voice system | 🟡 | 70 | mocked providers + socket round-trip — **no real audio, no real STT/TTS provider credentials available** |
| 8 | Integrations & plugins | 🟡 | 75 | mocked Google — **never contacted real services** (needs a Google Cloud OAuth client + human consent; not obtainable in a non-interactive sandbox — see [integration-validation-checklist.md](docs/reports/integration-validation-checklist.md)) |
| 9 | Testing suite | ✅ | 91 | 340 backend + 25 web unit + 5 browser E2E tests, all passing; 10 additional live-server tests pass when real Postgres/Redis are reachable; see [testing.md](docs/testing.md) |
| 10 | Deployment | 🟠 | 68 | Alembic migration Job authored, wired into CI, **and the migration itself has now actually run successfully against a live PostgreSQL server** (previously only offline-SQL-verified) — **still never built or applied against a live Docker/Kubernetes cluster** |

**Overall ≈ 88 %.** This pass ("Real World Validation") replaced several "should work" claims with real, executed proof: a live PostgreSQL server ran the actual migration and the actual app's CRUD/constraints/cascades; a live Redis server was genuinely killed and restarted mid-session to prove the resilience logic; a real Chromium browser drove the real production web build through registration, chat, and task creation. Two real bugs were found and fixed this pass (a Redis RESP3/HELLO incompatibility that silently defeated all Redis usage; a React effect crash on every chat message), both now guarded by permanent regression tests. What remains unverified is now narrower and mostly structural: mobile compilation (no SDK), voice/microphone (no real mic anywhere automatable), and Gmail/Calendar/Anthropic/Azure (all need real credentials and, for Google, a human clicking through an OAuth consent screen).

## Before the first user (must-do)
1. **Native Tamil review** of `backend/app/i18n/persona.py` and `voice/translit.py`. A structured self-review pass checked every reply template and the full Tamil lexicon for grammatical correctness and found no errors — see [language-system.md](docs/language-system.md#known-limitations) — but that is not a substitute for a native speaker actually reading it aloud, which is still recommended before shipping.
2. **Try it in a browser with a microphone** (Chrome/Edge): the non-voice UI is now proven end-to-end by real Playwright tests; voice specifically (listening, wake word, hands-free, actual speech synthesis) still needs a human with a real microphone.
3. **Run the Flutter app** (`flutter create .`, analyze, test, run on a device) and fix API drift.
4. ~~Introduce Alembic migrations~~ ~~run against an actual PostgreSQL server~~ **Both done.** See [phase-live-postgres.md](docs/reports/phase-live-postgres.md).
5. ~~Confirm Redis fan-out against a real `redis-server`~~ **Done** — including killing the real process mid-session. See [phase-live-redis.md](docs/reports/phase-live-redis.md). Remaining: staging should still confirm this against Redis 7.x on Linux (validated here against 5.0.14.1 on Windows — RESP2 compatibility is protocol-universal, but the exact production version hasn't been re-checked).
6. **Point at real providers** with keys: Anthropic, Azure Speech (or Whisper), Google OAuth — see [integration-validation-checklist.md](docs/reports/integration-validation-checklist.md) for exactly what each needs and why none could be obtained in this environment.
7. **Stand up a real Docker/Kubernetes cluster** and apply `deploy/k8s` — still the single largest completely-unexecuted piece of the deployment story.

## Next (v1.1 — hardening)
- Mobile integration tests (Flutter, once an SDK is available).
- httpOnly-cookie sessions for the web app; password reset, email verification, account deletion.
- Real embedding model + Qdrant against a live server (validated here for Postgres/Redis but not yet Qdrant).
- PostgreSQL + Redis as CI service containers, so the live-server validation added this pass runs on every CI push rather than requiring a human to run it locally (`tests/test_live_postgres.py` / `test_live_redis.py` are already written to support this — they just need `WENSDAY_LIVE_POSTGRES_URL`/`WENSDAY_LIVE_REDIS_URL` set in the CI job).
- FCM/APNs push for reminders when the app is closed; mobile: dialer hand-off (`url_launcher`), Google sign-in, remaining screens.
- Web UI for documents, meeting summaries, inbox summary and workflow editor; E2E coverage for calendar/notes/goals/memory/plugins/settings pages.
- Prometheus alert rules, log aggregation/tracing (structured per-request access logging landed last pass; still text-line, not JSON).

## Future enhancement roadmap
| Version | Theme | Items |
|---|---|---|
| **v1.2** | Proactive & personal | Proactive suggestions (commute, meeting prep, gentle nudges from the coaching service); on-device wake word (openWakeWord/Porcupine); NLU labelled-data benchmark and active learning from corrections; Chennai-dialect fine-tuned ASR; richer Tamil time/number grammar |
| **v1.3** | Reach | WhatsApp and Slack channels; telephony/dialer plugin; smart-home plugins; Outlook/Microsoft 365; shared family/team workspaces |
| **v2.0** | Autonomy | On-device small LLM + on-device NLU port for full offline reasoning on mobile; multi-step agents/workflows with human-in-the-loop approvals; sandboxed, signed plugin marketplace (process isolation); custom-trained female Tamil–English voice |
