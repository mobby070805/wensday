# Testing

## What ran, and what did not

| Suite | Command | Result |
|---|---|---|
| Backend (pytest) | `cd backend && python -m pytest -q` | **339 passed** (≈110 s) |
| Web (vitest) | `cd web && npm test` | **25 passed** |
| Web types / build | `npm run typecheck`, `npm run build` | clean; 13 routes generated |
| Real-server smoke | uvicorn + HTTP client (health, ready, CORS preflight, auth, Tamil/Tanglish/English chat) | passed (manual, one-off) |
| Alembic migrations | real `alembic` CLI: `upgrade head`, `downgrade base`, `check`, `--sql` against SQLite and a `postgresql://` URL | passed — see `test_migrations.py` below |
| Redis protocol & resilience | `RedisCache`/`EventHub` against fakeredis (a real in-process RESP-protocol server, not a mock) | passed — see `test_redis_compat.py` below |
| YAML validity | k8s manifests (incl. the migration Job), compose, CI workflow parsed | passed |
| **Flutter** | `cd mobile && flutter test` | **not run** — no Flutter SDK was available. ~25 Dart tests exist. |
| **Docker / k8s** | build & apply | **not run** — no Docker daemon or cluster available |
| **Browser behaviour** | mic, speech synthesis, layout | **not exercised** — no browser automation was available |
| **Live PostgreSQL / Redis / Qdrant / Anthropic / Azure / Google** | — | **never contacted** — no live instances were available. PostgreSQL and Redis now have real *protocol-level* verification (below) that goes beyond the mocked-wire-format testing everything else uses; Anthropic/Azure/Whisper/Google/Qdrant remain covered only by `httpx.MockTransport`s asserting exact request shapes. |

## Backend suite (339)
| File | Tests | Covers |
|---|---:|---|
| `test_language.py` | 109 | detection (ta/en/tanglish, code-mixing, register), spelling variance, time parsing in 3 languages, every NLU intent, 42 English words/names that must *not* read as Tanglish |
| `test_conversation.py` | 34 | **the brief's exact examples end-to-end**, language mirroring & mid-conversation switching, multi-turn slot filling, email confirmation gate, calendar, tasks/notes/goals, learned name/language, offline fallback |
| `test_api.py` | 57 | auth & token security (rotation, replay ⇒ all sessions revoked, type confusion), **tenant isolation across every resource**, CRUD & validation, sync + tombstones, websocket push, plugin permission model, workflows, analytics, rate limiting, security response headers |
| `test_memory.py` | 41 | fact extraction ×3 languages, cross-language semantic recall, dedupe, importance, decay/prune, per-user isolation, Qdrant REST adapter, chunking, RAG, **real on-disk persistence across a simulated process restart** |
| `test_voice.py` | 32 | transliteration, language-run splitting, SSML validity, Whisper/Azure providers, full audio-in → transcript → reply → audio-out socket turn, barge-in, oversized-frame rejection, per-IP connection rate limiting, provider-misconfiguration warnings |
| `test_llm.py` | 15 | Anthropic & OpenAI-compatible wire formats, failover + circuit breaker, tool-calling loop, loop cap, LLM never sees `send_email` or un-enabled plugin tools |
| `test_integrations.py` | 14 | Google OAuth (state, scopes, linking, unverified email), tokens encrypted at rest, transparent refresh, Calendar sync idempotence, Gmail send only with a real address |
| `test_services.py` | 18 | recurrence (no month-drift, weekends), task ranking, meeting heuristics, conflicts, **two workers racing on one reminder ⇒ fires once** |
| `test_migrations.py` | 9 | `alembic upgrade head` produces exactly the ORM-declared schema (reflected column-by-column), `downgrade base → upgrade head` round-trips, idempotent re-upgrade, `alembic check` shows zero drift, `--sql` offline emission compiles valid PostgreSQL DDL and is deterministic, `create_all` defers to a migration-managed database |
| `test_redis_compat.py` | 10 | `RedisCache`/`EventHub` against fakeredis: real INCR/EXPIRE/GET/SET/PUBLISH/SUBSCRIBE, two independent `EventHub`s fanning an event out like two API replicas, **survival of a mid-session Redis outage at both the unit and HTTP-endpoint level**, pubsub listener reconnection after a dropped connection |

### Approach
- **No network, ever, for the mocked suites.** Each test app runs on in-memory SQLite with the LLM chain set to `offline` and collaborators injected (`create_app(llm=…, http=…, stt=…, tts=…, mailer=…)`). External services are `httpx.MockTransport`s that assert the exact request shapes.
- **Real protocol implementations where a faithful one exists and is practical without a live server.** `fakeredis` (Redis compat) and the real `alembic`/SQLAlchemy stack against SQLite files (migrations) run actual code paths rather than asserting mocked calls — this is a step up from mocking, though still short of a live `redis-server`/PostgreSQL cluster.
- **Behaviour through the public API** (`TestClient`) wherever possible, so routing, auth, persistence and persona are all exercised together.
- **Red-then-green discipline for bug fixes**: every regression test added during the Production Completion Mode pass (Redis resilience, websocket hardening) was first confirmed to fail against the pre-fix code (`git stash` for the Redis fix; direct execution for the websocket hardening) before the fix was applied and the suite re-confirmed green.
- **Regression tests for every bug found while building or hardening** — e.g. the CRUD factory losing its request bodies, "amma" (mother) matching "aama" (yes), the embedder discarding "meeting", "call me later" learned as a name, `RedisCache` propagating a Redis outage into 500s on every rate-limited route, the websocket route accepting unbounded text frames and unlimited connection attempts per IP.

## Gaps in coverage (known)
- Speech quality (Tamil accent, recognition accuracy of code-switched speech) can only be judged with real audio and native speakers — no automated test can.
- NLU coverage is broad but rule-based: unusual phrasings fall through to the LLM tier (or the offline message). A labelled evaluation set from real users is the next investment.
- No load or soak tests; no browser E2E (Playwright recommended next); no mobile integration tests.
- **PostgreSQL**: the migration DDL is now verified to compile correctly for the PostgreSQL dialect (`alembic upgrade head --sql` against a `postgresql://` URL, no live server needed — see `test_migrations.py`), and the ORM's own `CreateTable` output for every table is likewise dialect-checked. What is *still* unverified is running that DDL, or any ORM query, against an actual PostgreSQL server — no instance was available in this environment.
- **Redis**: `RedisCache` and `EventHub` are now exercised against fakeredis, a real in-process implementation of the RESP wire protocol — not a mock — covering normal operation, a mid-session outage (the app must degrade instead of 500ing), and pubsub reconnection. fakeredis does not simulate a real TCP-level disconnect (confirmed experimentally: disconnecting a fake connection silently resubscribes rather than raising), so the reconnect test injects a fault at the same seam a real `redis-py` `ConnectionError` would surface at, rather than triggering an actual socket failure. **Verify against a real `redis-server` on staging** before relying on this in a multi-replica production deployment.
