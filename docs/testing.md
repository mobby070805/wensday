# Testing

## What ran, and what did not

| Suite | Command | Result |
|---|---|---|
| Backend (pytest) | `cd backend && python -m pytest -q` | **312 passed** (≈70 s) |
| Web (vitest) | `cd web && npm test` | **25 passed** |
| Web types / build | `npm run typecheck`, `npm run build` | clean; 13 routes generated |
| Real-server smoke | uvicorn + HTTP client (health, ready, CORS preflight, auth, Tamil/Tanglish/English chat) | passed (manual, one-off) |
| YAML validity | k8s manifests, compose, CI workflow parsed | passed |
| **Flutter** | `cd mobile && flutter test` | **not run** — no Flutter SDK was available. ~25 Dart tests exist. |
| **Docker / k8s** | build & apply | **not run** — no Docker daemon or cluster available |
| **Browser behaviour** | mic, speech synthesis, layout | **not exercised** — no browser automation was available |
| **Real providers** | Anthropic, Azure, Whisper, Google, Qdrant, Postgres | **never contacted** — all covered by mocked HTTP transports (wire formats are asserted) |

## Backend suite (312)
| File | Tests | Covers |
|---|---:|---|
| `test_language.py` | 109 | detection (ta/en/tanglish, code-mixing, register), spelling variance, time parsing in 3 languages, every NLU intent, 42 English words/names that must *not* read as Tanglish |
| `test_conversation.py` | 34 | **the brief's exact examples end-to-end**, language mirroring & mid-conversation switching, multi-turn slot filling, email confirmation gate, calendar, tasks/notes/goals, learned name/language, offline fallback |
| `test_api.py` | 55 | auth & token security (rotation, replay ⇒ all sessions revoked, type confusion), **tenant isolation across every resource**, CRUD & validation, sync + tombstones, websocket push, plugin permission model, workflows, analytics, rate limiting |
| `test_memory.py` | 39 | fact extraction ×3 languages, cross-language semantic recall, dedupe, importance, decay/prune, per-user isolation, Qdrant REST adapter, chunking, RAG |
| `test_voice.py` | 28 | transliteration, language-run splitting, SSML validity, Whisper/Azure providers, full audio-in → transcript → reply → audio-out socket turn, barge-in |
| `test_llm.py` | 15 | Anthropic & OpenAI-compatible wire formats, failover + circuit breaker, tool-calling loop, loop cap, LLM never sees `send_email` or un-enabled plugin tools |
| `test_integrations.py` | 14 | Google OAuth (state, scopes, linking, unverified email), tokens encrypted at rest, transparent refresh, Calendar sync idempotence, Gmail send only with a real address |
| `test_services.py` | 18 | recurrence (no month-drift, weekends), task ranking, meeting heuristics, conflicts, **two workers racing on one reminder ⇒ fires once** |

### Approach
- **No network, ever.** Each test app runs on in-memory SQLite with the LLM chain set to `offline` and collaborators injected (`create_app(llm=…, http=…, stt=…, tts=…, mailer=…)`). External services are `httpx.MockTransport`s that assert the exact request shapes.
- **Behaviour through the public API** (`TestClient`) wherever possible, so routing, auth, persistence and persona are all exercised together.
- **Regression tests for every bug found while building** (listed in the phase reports) — e.g. the CRUD factory losing its request bodies, "amma" (mother) matching "aama" (yes), the embedder discarding "meeting", "call me later" learned as a name.

## Gaps in coverage (known)
- Speech quality (Tamil accent, recognition accuracy of code-switched speech) can only be judged with real audio and native speakers — no automated test can.
- NLU coverage is broad but rule-based: unusual phrasings fall through to the LLM tier (or the offline message). A labelled evaluation set from real users is the next investment.
- No load or soak tests; no browser E2E (Playwright recommended next); no mobile integration tests.
- PostgreSQL-specific behaviour is untested (tests use SQLite); the generated PostgreSQL DDL is in [database.md](database.md).
- **Redis code paths are untested**: `EventHub` pub/sub fan-out and `RedisCache` only run when `WENSDAY_REDIS_URL` is set and the `redis` package is installed; in every test they fall back to the in-process implementations. This matters for the multi-replica/worker topology (reminder pushes cross pods through Redis), so **verify it on staging** before relying on it. A failed Redis connection logs a warning and degrades to in-process delivery rather than crashing.
