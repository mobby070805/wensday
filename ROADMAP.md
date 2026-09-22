# Wensday — Product Roadmap

**Legend:** ✅ built and verified here · 🟡 built, only partly verifiable here · 🟠 written but never executed

Completion % is an honest estimate of *shippable* work in each phase, not lines written, and moves only when new work in that phase was actually run and verified in this environment. Details, bugs found and gaps per phase are in [docs/reports/](docs/reports).

| # | Phase | Status | % | Verified by |
|---|---|:-:|--:|---|
| 1 | Requirements & architecture | ✅ | 100 | reviewed docs |
| 2 | Repository layout | ✅ | 100 | — |
| 3 | Backend (API, DB, auth, agent, services) | ✅ | 93 | 339 backend tests; real uvicorn smoke test; Alembic migrations (real CLI, SQLite + PostgreSQL DDL); Redis resilience (real protocol via fakeredis); websocket hardening (frame-size cap, per-IP connect limit); security response headers |
| 4 | Web frontend (Next.js) | 🟡 | 80 | typecheck, 25 unit tests, production build — **never opened in a browser** |
| 5 | Mobile app (Flutter) | 🟠 | 45 | ~25 Dart tests written — **never compiled** (no SDK) |
| 6 | Memory engine | ✅ | 92 | 41 tests, including **real on-disk persistence across a simulated process restart** (file-backed SQLite, not `:memory:`) |
| 7 | Voice system | 🟡 | 70 | mocked providers + socket round-trip — **no real audio** |
| 8 | Integrations & plugins | 🟡 | 75 | mocked Google — **never contacted real services** |
| 9 | Testing suite | ✅ | 88 | 339 backend + 25 web tests; see [testing.md](docs/testing.md) |
| 10 | Deployment | 🟠 | 64 | Alembic migration Job authored and wired into CI's deploy step; migration DDL verified to compile for PostgreSQL — **still never built or applied against a live Docker/cluster/database** |

**Overall ≈ 81 %.** The core product — the trilingual conversation engine, memory, API — is solid and heavily tested, and this pass closed the two most concrete, repeatedly-flagged gaps (no migrations, untested Redis paths) with real regression tests, plus fixed two production-impact bugs those tests found along the way (a Redis outage would have 500'd the whole API; the websocket route had no size/connection caps at all). What remains is still mostly *contact with reality*: real browsers, real phones, real audio, real cloud providers, a real cluster and a real PostgreSQL/Redis server.

## Before the first user (must-do)
1. **Native Tamil review** of `backend/app/i18n/persona.py` and `voice/translit.py`. A structured self-review pass (Production Completion Mode) checked every reply template and the full Tamil lexicon for grammatical correctness and found no errors — see [language-system.md](docs/language-system.md#known-limitations) — but that is not a substitute for a native speaker actually reading it aloud, which is still recommended before shipping.
2. **Try it in a browser with a microphone** (Chrome/Edge): voice loop, barge-in, hands-free, reminder push.
3. **Run the Flutter app** (`flutter create .`, analyze, test, run on a device) and fix API drift.
4. ~~Introduce Alembic migrations~~ **Done this pass** (`backend/alembic/`, 9 passing tests). Remaining: run `alembic upgrade head` against an actual PostgreSQL server at least once — only compile-level (offline `--sql`) verification was possible here.
5. **Stand up staging**: build the images, apply `deploy/k8s` (including `25-migrate-job.yaml`), and specifically confirm Redis fan-out (worker → API pods → sockets) against a real `redis-server` — the fakeredis-based tests prove the code path and the resilience logic, not an actual server.
6. **Point at real providers** with keys: Anthropic, Azure Speech (or Whisper), Google OAuth — and listen to the result.
7. Root `.gitignore` and git init are done; the repo is on GitHub. Commit `web/package-lock.json` if it isn't already tracked.

## Next (v1.1 — hardening)
- Playwright browser E2E and a mobile integration test.
- httpOnly-cookie sessions for the web app; password reset, email verification, account deletion.
- Real embedding model + Qdrant in CI (service containers); PostgreSQL + Redis service containers in CI (currently only exercised via SQLite files and fakeredis).
- FCM/APNs push for reminders when the app is closed; mobile: dialer hand-off (`url_launcher`), Google sign-in, remaining screens.
- Web UI for documents, meeting summaries, inbox summary and workflow editor.
- Prometheus alert rules, log aggregation/tracing (structured per-request access logging landed this pass; still text-line, not JSON).

## Future enhancement roadmap
| Version | Theme | Items |
|---|---|---|
| **v1.2** | Proactive & personal | Proactive suggestions (commute, meeting prep, gentle nudges from the coaching service); on-device wake word (openWakeWord/Porcupine); NLU labelled-data benchmark and active learning from corrections; Chennai-dialect fine-tuned ASR; richer Tamil time/number grammar |
| **v1.3** | Reach | WhatsApp and Slack channels; telephony/dialer plugin; smart-home plugins; Outlook/Microsoft 365; shared family/team workspaces |
| **v2.0** | Autonomy | On-device small LLM + on-device NLU port for full offline reasoning on mobile; multi-step agents/workflows with human-in-the-loop approvals; sandboxed, signed plugin marketplace (process isolation); custom-trained female Tamil–English voice |
