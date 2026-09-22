# Phase 3 — Backend · **93 %**

**Delivered** (`backend/app`, ~6.3 k lines): app factory with dependency injection · JWT access/refresh with **rotation and replay detection** · scrypt password hashing · Google OAuth · generic per-user CRUD factory (tenant isolation in one place) for tasks, reminders, events, notes · goals with computed progress · conversation orchestrator with rule NLU → slot filling → confirmation gate → LLM tier → offline fallback · tool registry (20 built-in tools) · reminder worker + scheduled workflows · incremental sync with tombstones · realtime socket · analytics · rate limiting · request ids · `/healthz` `/readyz` `/metrics` · 54 documented endpoints ([api.md](../api.md), 21 tables in [database.md](../database.md)).

**Tests:** `test_api.py` 55 · `test_conversation.py` 34 · `test_services.py` 18 (+ language 109 in Phase 3's NLU).

**Real bugs the tests caught (all fixed, all regression-tested)**
| Bug | Impact if shipped |
|---|---|
| CRUD factory annotations were strings → FastAPI treated request bodies as query params | every generic POST/PATCH would have returned 422 |
| `_h_unknown` dispatched with wrong arguments | every unrecognised utterance → generic error |
| Recurrence stepped day-by-day with a bound; monthly drifted (Jan 31→Feb 28→Mar 28) | reminders overdue >11 y returned nothing; drift |
| Reminder firing ran in every replica | duplicate notifications under Kubernetes → made claim-based (atomic conditional UPDATE) + dedicated worker |
| Overdue task tied with merely-high-priority | wrong plan order |

*Also fixed in self-review before any test ran:* JWT `iat/exp` were computed from naive-UTC datetimes with `.timestamp()`, which reads them as local time — tokens would have had the wrong lifetime on any non-UTC host.

**Gaps / not done**
- ~~No database migrations~~ **Resolved — see the Production Completion Mode addendum below.**
- Tested only on SQLite; PostgreSQL DDL is generated ([database.md](../database.md)) and, as of the addendum below, verified to *compile* via Alembic's offline SQL emission — still never executed against a live server.
- Password reset, email verification and account deletion endpoints are not implemented.
- ~~Rate limiting is per IP and in-memory unless Redis is configured (and the Redis path is untested)~~ **The Redis path is now tested — see the addendum.** Rate limiting is still per-IP.
- "Email summarisation" is implemented for the Gmail inbox only (needs Google connected); there is no attachment handling.

---

## Addendum — Production Completion Mode audit

A full audit for TODOs/FIXMEs/stubs/hardcoded values found none in `backend/app` (the two textual hits from an automated grep were both false positives: `__missing__` in `persona.py` refers to `str.format` placeholders, and `"to-do"` in the lexicon's English word list matched the search pattern by coincidence). The two real gaps this phase had flagged — no migrations, untested Redis — were closed:

**Found: no database migrations existed**, explicitly blocking production readiness on every prior pass. **Changed:** initialized Alembic (`backend/alembic/`, async template), pointed `env.py` at `app.config.Settings.database_url` (one source of truth, no second copy in `alembic.ini`), and generated one baseline revision covering all 21 tables. `Database.create_all()` now detects an `alembic_version` table and refuses to run against a migration-managed database. **Tests added:** `tests/test_migrations.py` (9 tests) shells out to the real `alembic` CLI: upgrade produces exactly the ORM-declared schema (reflected column-by-column and index-by-index), downgrade/upgrade round-trips, idempotent re-upgrade, `alembic check` proves zero drift from `app/models.py`, and `--sql` offline emission against a `postgresql://` URL confirms the migration DDL is valid PostgreSQL (VARCHAR sizing, REFERENCES constraints) with no live server. **Risk remaining:** never run against an actual PostgreSQL server.

**Found: `RedisCache.incr_window/get/set` had zero exception handling.** Since `incr_window` backs the `rate_limit` dependency used on nearly every route, a Redis connectivity blip after startup would propagate an unhandled exception straight through the dependency and 500 the entire API — not a hypothetical, this is exactly the failure mode `docs/testing.md` had flagged as untested. `EventHub`'s pubsub listener also had no reconnect loop (a dropped connection silently killed the background task forever) and `stop()` could itself raise if Redis was unreachable during shutdown. **Changed:** `RedisCache` now falls back to a local per-replica `MemoryCache` on any Redis error, matching the resilience pattern `EventHub.publish` already had; `EventHub._listen` was split into a supervised reconnect loop with backoff; `stop()` guards its own `aclose()`. **Tests added:** `tests/test_redis_compat.py` (10 tests) against `fakeredis` — a real in-process RESP-protocol implementation, not a mock — confirmed red against the pre-fix code via `git stash`, green after. **Risk remaining:** fakeredis does not simulate a real TCP-level disconnect (verified experimentally), so the reconnect test injects a fault at the same seam a real `redis-py` `ConnectionError` would surface at, not an actual socket failure.

**Found: the websocket route had no cap on text-frame size and no per-IP connection-rate limit.** A client could send an arbitrarily large text frame into `json.loads()` on every message, and nothing limited how many `/ws` connections (each doing a DB lookup to validate the token) a single IP could open per minute. **Changed:** a 32 KiB text-frame cap (checked before parsing) and a per-IP connect-rate limit (`ws_connect_limit_per_minute`, default 30, reusing the same `Cache.incr_window` primitive as the HTTP rate limiter) rejecting with WS close code 4429. **Tests added:** both confirmed red against the pre-fix route, green after.

**Also added:** `X-Frame-Options`, `Referrer-Policy`, and conditional `Strict-Transport-Security` (only over TLS) response headers; a per-request INFO access log line (method, path, status, duration, request id — deliberately never the query string or body, which can carry the user's own message text); `build_stt`/`build_tts` now log a warning naming the exact missing setting instead of silently falling back to browser voice.

**Cleanup:** removed `qdrant-client` from the production dependency list — Qdrant is spoken over raw REST via `httpx` (`app/memory/vectorstore.py`); the client library was declared but never imported anywhere.

Full backend suite after this addendum: **339/339 passing** (was 312).
