# Testing

## What ran, and what did not

| Suite | Command | Result |
|---|---|---|
| Backend (pytest) | `cd backend && python -m pytest -q` | **340 passed, 10 skipped** (≈100 s) — the 10 skipped are the live-server suites, below |
| Backend, live servers reachable | `WENSDAY_LIVE_POSTGRES_URL=… WENSDAY_LIVE_REDIS_URL=… python -m pytest -q` | **350 passed** (≈117 s) |
| Web unit (vitest) | `cd web && npm test` | **25 passed** |
| Web E2E (Playwright, real Chromium) | `cd web && npm run test:e2e` | **5 passed**, against the real production build + real backend |
| Web types / build | `npm run typecheck`, `npm run build` | clean; 13 routes generated |
| Real-server smoke | uvicorn + HTTP client (health, ready, CORS preflight, auth, Tamil/Tanglish/English chat) | passed (manual, one-off) |
| Alembic migrations, SQLite | real `alembic` CLI: `upgrade head`, `downgrade base`, `check`, `--sql` against SQLite and a `postgresql://` URL | passed — `test_migrations.py` |
| **Alembic migrations, live PostgreSQL 16.4** | `alembic upgrade head` / `downgrade base` / `upgrade head` again, for real | **passed** — `test_live_postgres.py`, [phase-live-postgres.md](reports/phase-live-postgres.md) |
| Redis protocol & resilience, fakeredis | `RedisCache`/`EventHub` against fakeredis (a real in-process RESP-protocol server, not a mock) | passed — `test_redis_compat.py` |
| **Redis, live server (genuinely killed + restarted)** | real `redis-server` process, actually terminated and relaunched mid-test | **passed** — `test_live_redis.py`, [phase-live-redis.md](reports/phase-live-redis.md) — **found and fixed a real bug** |
| **Browser automation, real Chromium** | Playwright against the real production build | **passed** — [phase-browser.md](reports/phase-browser.md) — **found and fixed a real bug** |
| YAML validity | k8s manifests (incl. the migration Job and new `e2e` CI job), compose, CI workflow parsed | passed |
| **Flutter** | `cd mobile && flutter test` | **not run** — no Flutter SDK was available. ~25 Dart tests exist. |
| **Docker / k8s** | build & apply | **not run** — no Docker daemon or cluster available |
| **Browser voice (mic, speech synthesis)** | — | **not exercised** — no real microphone in any automatable environment; see [phase-browser.md](reports/phase-browser.md) |
| **Gmail / Google Calendar / Anthropic / Azure / Whisper** | — | **never contacted** — no credentials available; see [integration-validation-checklist.md](reports/integration-validation-checklist.md) for exactly what each needs |

## Backend suite (340 unconditional + 10 live-server)
| File | Tests | Covers |
|---|---:|---|
| `test_language.py` | 109 | detection (ta/en/tanglish, code-mixing, register), spelling variance, time parsing in 3 languages, every NLU intent, 42 English words/names that must *not* read as Tanglish |
| `test_conversation.py` | 34 | **the brief's exact examples end-to-end**, language mirroring & mid-conversation switching, multi-turn slot filling, email confirmation gate, calendar, tasks/notes/goals, learned name/language, offline fallback |
| `test_api.py` | 57 | auth & token security (rotation, replay ⇒ all sessions revoked, type confusion), **tenant isolation across every resource**, CRUD & validation, sync + tombstones, websocket push, plugin permission model, workflows, analytics, rate limiting, security response headers |
| `test_memory.py` | 41 | fact extraction ×3 languages, cross-language semantic recall, dedupe, importance, decay/prune, per-user isolation, Qdrant REST adapter, chunking, RAG, real on-disk persistence across a simulated process restart |
| `test_voice.py` | 32 | transliteration, language-run splitting, SSML validity, Whisper/Azure providers, full audio-in → transcript → reply → audio-out socket turn, barge-in, oversized-frame rejection, per-IP connection rate limiting, provider-misconfiguration warnings |
| `test_llm.py` | 15 | Anthropic & OpenAI-compatible wire formats, failover + circuit breaker, tool-calling loop, loop cap, LLM never sees `send_email` or un-enabled plugin tools |
| `test_integrations.py` | 14 | Google OAuth (state, scopes, linking, unverified email), tokens encrypted at rest, transparent refresh, Calendar sync idempotence, Gmail send only with a real address |
| `test_services.py` | 18 | recurrence (no month-drift, weekends), task ranking, meeting heuristics, conflicts, two workers racing on one reminder ⇒ fires once |
| `test_migrations.py` | 9 | `alembic upgrade head` produces exactly the ORM-declared schema, `downgrade base → upgrade head` round-trips, idempotent re-upgrade, `alembic check` shows zero drift, `--sql` offline emission compiles valid PostgreSQL DDL and is deterministic, `create_all` defers to a migration-managed database |
| `test_redis_compat.py` | 11 | `RedisCache`/`EventHub` against fakeredis: real INCR/EXPIRE/GET/SET/PUBLISH/SUBSCRIBE, two independent `EventHub`s fanning an event out like two API replicas, survival of a mid-session Redis outage, pubsub listener reconnection, **regression test pinning RESP2** (the real bug fakeredis alone couldn't have caught) |
| `test_live_postgres.py` | 6 | skip cleanly with no live server configured; against a real PostgreSQL 16.4: app boot + `/readyz`, a real UNIQUE-constraint 409, Tamil UTF-8 round-tripping through a real JSON column, a full chat turn, the sync endpoint, a real `ON DELETE CASCADE` |
| `test_live_redis.py` | 4 | skip cleanly with no live server configured; against a real `redis-server`: protocol correctness, cross-replica pubsub fan-out, **and two tests that spawn and then genuinely kill their own redis-server process** to prove the resilience logic under a real failure |

## Web suite (25 unit + 5 E2E)
| File | Tests | Covers |
|---|---:|---|
| `tests/api.test.ts` | 7 | single-flight token refresh incl. the parallel-401 case, sign-out on failed refresh, FastAPI validation-error surfacing |
| `tests/voice-utils.test.ts` | 18 | wake-word stripping incl. "Wednesday" mis-hearing, female-voice selection, recognition-locale choice, EN↔TA UI-string parity, chart geometry |
| `e2e/smoke.spec.ts` | 5 | real Chromium browser against the real production build + real backend: login renders cleanly, registration → chat turn → exact reply text, adding a task through the real UI, dashboard renders without console errors, a real wrong-password error |

## Approach
- **No network, ever, for the mocked suites.** Each test app runs on in-memory SQLite with the LLM chain set to `offline` and collaborators injected. External services are `httpx.MockTransport`s that assert the exact request shapes.
- **Real protocol/server implementations wherever practical.** fakeredis and SQLite-backed Alembic runs (always-on, no live server needed) sit alongside genuinely live PostgreSQL, live Redis, and a real Chromium browser (opt-in, used during this validation pass and reusable by anyone with the same portable binaries — no Docker or admin rights required; see each phase report's "Setup" section).
- **Behaviour through the public API** (`TestClient`, or a real browser for the E2E suite) wherever possible, so routing, auth, persistence and persona are all exercised together.
- **Red-then-green discipline for every bug fix**: the RedisCache resilience fix, the RESP2 fix, the websocket hardening, and the Chat.tsx crash fix were each confirmed to fail against the pre-fix code (via `git stash`, a temporary revert, or direct reproduction) before the fix was applied and the relevant suite re-confirmed green.
- **Regression tests for every bug found** — e.g. the CRUD factory losing its request bodies, "amma" (mother) matching "aama" (yes), the embedder discarding "meeting", "call me later" learned as a name, `RedisCache` propagating a Redis outage into 500s on every rate-limited route, the websocket route accepting unbounded text frames and unlimited connection attempts per IP, `redis-py`'s RESP3/HELLO handshake silently defeating all Redis operations against a pre-6.0 server, and an implicit-return `useEffect` crashing the web app on every chat message (a class of bug TypeScript's `void`-return typing cannot catch statically — only real browser execution found it).

## Gaps in coverage (known)
- Speech quality (Tamil accent, recognition accuracy of code-switched speech) and the Web Speech API paths (listening, wake word, hands-free, actual synthesis) can only be judged with real audio, a real microphone, and native speakers — no automated environment (this one included) can provide either.
- NLU coverage is broad but rule-based: unusual phrasings fall through to the LLM tier (or the offline message). A labelled evaluation set from real users is the next investment.
- No load, soak, or chaos tests. No mobile integration tests (no Flutter SDK available).
- **PostgreSQL and Redis** now have both compile/protocol-level verification (always-on, no server needed) *and* genuine live-server verification (opt-in, run during this pass — see the two `phase-live-*.md` reports for exactly what was and wasn't covered, e.g. no TLS/auth/clustering/load was tested against either).
- **Browser automation** now covers the non-voice UI end-to-end against a real browser and real production build (see [phase-browser.md](reports/phase-browser.md)); voice remains the one thing no CI-style environment can exercise.
- **Gmail, Google Calendar, Anthropic, Azure Speech, Whisper** remain covered only by mocked HTTP wire-format tests — none were reachable from this environment. See [integration-validation-checklist.md](reports/integration-validation-checklist.md) for exactly what credentials/access each would need.
