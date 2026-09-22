# Phase 9 — Testing suite · **88 %**

**Delivered:** 339 backend tests + 25 web tests, all passing; ~25 Dart tests written but not run. Full breakdown, method and gaps: [testing.md](../testing.md). CI runs all suites ([ci.yml](../../.github/workflows/ci.yml)).

**Highlights**
- The brief's own utterances are asserted **verbatim end-to-end** (e.g. `"Sure Madesh, nalaiku morning 9:00 AM-ku meeting reminder set panniten."`, `"Mail draft ready. Review panna venduma illa direct send panna venduma?"`, `"Okay. Inniku schedule la important tasks mattum prioritize panren."`).
- Security properties are tests, not intentions: tenant isolation across every resource type, refresh-token replay revoking all sessions, token-type confusion, no account enumeration on login, OAuth `state` forgery, tokens encrypted at rest, plugin scope revocation, the LLM never being offered `send_email`, email never sent without confirmation.
- Concurrency: two workers racing on one reminder → exactly one fires; parallel 401s share one token refresh (web and Dart).
- Tests are hermetic (no network) and deterministic (fixed clock for NLU; mocked transports).

**Method note:** several failures were *test* bugs (wrong expectations, sloppy `or` assertions, a spy that only recorded the last message) and were fixed in the tests — but the tests also exposed **at least twelve real product bugs** (phases 3, 6, 7 list them): the CRUD body-annotation bug, unknown-intent dispatch, recurrence drift/catch-up, ranking, the fuzzy-match and skeleton collisions (`vilakku`/`ilakku`, `amma`/`aama`, `Jerry`/`seri`), English content words diluting Tanglish detection, the language-stickiness rule overriding real Tanglish, the lone "epdi" triggering how-are-you, template keyword collisions, the embedder's stop-word list, and "call me later" learned as a name.

**Gaps:** no browser E2E, load, soak or chaos tests · no live PostgreSQL/Redis/Qdrant integration tests (see the addendum for what upgraded from "no test at all" to "real protocol, no live server") · no mobile integration tests · no NLU accuracy benchmark on real user utterances · no speech-quality evaluation with native speakers · no coverage measurement configured.

---

## Addendum — Production Completion Mode

27 tests added (312 → 339), two of them closing gaps this report explicitly listed:

- **`tests/test_migrations.py`** (9) — real `alembic` CLI against scratch SQLite files: upgrade matches the ORM schema exactly, downgrade/upgrade round-trips, idempotent re-upgrade, `alembic check` proves zero model/migration drift, and `--sql` offline emission against a `postgresql://` URL proves the migration DDL is valid PostgreSQL with no live server involved.
- **`tests/test_redis_compat.py`** (10) — `fakeredis`, a real in-process RESP-protocol server (not a mock), exercising `RedisCache` and `EventHub`'s actual Redis calls: protocol correctness, two independent `EventHub`s fanning an event out like two API replicas, and — the two tests that mattered most — survival of a mid-session Redis outage (confirmed red against the pre-fix code via `git stash`, green after the fix) and pubsub listener reconnection after a dropped connection.
- **6 tests** across `test_voice.py` (websocket text-frame-size cap, per-IP connection-rate limiting, provider-misconfiguration warnings) and `test_api.py` (security response headers) for hardening found during this same audit pass — each confirmed red before its fix and green after.
- **2 tests** in `test_memory.py` prove real on-disk persistence across a simulated process restart, upgrading the "memory persistence" claim from "works with the connection open" (all prior tests used `:memory:`) to "survives closing and reopening the database."

This is still short of live-server integration testing (no PostgreSQL or Redis instance was available in this environment) — the honest characterization is *real protocol/DDL verification without a live server*, one step more rigorous than mocking but not equivalent to a staging deploy against actual infrastructure. `docs/testing.md` states this distinction explicitly for both.
