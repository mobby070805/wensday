# Real World Validation — PostgreSQL

**Setup:** official PostgreSQL 16.4 Windows binaries (EDB's no-install zip distribution — no Docker, no admin rights needed), extracted to a scratch directory, `initdb` run with a fresh data directory, `pg_ctl` started on `localhost:55432`. Genuine PostgreSQL server process, not a mock, not SQLite.

## What was tested

1. **`alembic upgrade head` against a live server, for the first time ever.** Previously only verified via offline SQL emission (`--sql`, no connection) and execution against SQLite.
2. **`alembic downgrade base` → `alembic upgrade head` again**, a full round trip against the live server.
3. **The real FastAPI app** (`create_app`), not a script, performing:
   - `/readyz` reporting ready via a real `SELECT 1` against the live connection.
   - User registration, then a duplicate-email registration.
   - Creating a task with a JSON `tags` array containing Tamil script (`["urgent", "தமிழ்"]`).
   - Creating a reminder with a full Tamil-script title.
   - A complete chat turn through the real NLU → agent → persona pipeline.
   - The incremental `/sync` endpoint.
   - Deleting a user via the ORM and confirming their tasks are gone.
4. **`Database.create_all()`'s migration-awareness guard**, added last session and previously only verified against SQLite, explicitly confirmed via log output against the live server.

## What failed

Nothing, on the first attempt at each step above. (The Python validation *scripts* used to drive these checks needed two fixes unrelated to the app: a `PYTHONUTF8` console-encoding issue printing Tamil to the terminal, and using `asyncio.run()` instead of `TestClient`'s own event loop — see "Risk / method notes" below. Neither is an app defect.)

## What was fixed

Nothing in the application code — every check passed against a real, live PostgreSQL server without modification. This session's PostgreSQL work is entirely *validation*, not *repair* (contrast with the Redis validation, which found and fixed a real bug — see [phase-live-redis.md](phase-live-redis.md)).

## What evidence proves it works

```
$ alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> d218219847e0, initial schema

$ psql -c "\dt"                                    -- 22 tables: all 21 app tables + alembic_version
$ psql -c "\d users"                                -- correct types, PK, UNIQUE index, 17 CASCADE FKs referencing it

$ alembic downgrade base   →  \dt shows only alembic_version (all 21 app tables dropped)
$ alembic upgrade head     →  22 tables again

register            -> 201
duplicate email      -> 409  (real UNIQUE constraint, caught cleanly)
task with Tamil tags -> 201, tags == ["urgent", "தமிழ்"]      (real JSON column, real UTF-8)
reminder Tamil title -> 201, title == "நாளை மீட்டிங்"
chat turn             -> 200, "Sure Madesh, nalaiku morning 9:00 AM-ku meeting reminder set panniten."
sync                   -> tasks=1 reminders=2  (correct incremental count)
cascade delete         -> tasks before=1 after=0   (real ON DELETE CASCADE, not simulated)

log: "database is migration-managed (alembic_version present); skipping create_all"
```

`tests/test_live_postgres.py` — 6 tests formalizing the above, skip cleanly (`6 skipped`) when `WENSDAY_LIVE_POSTGRES_URL` is unset, all pass (`6 passed`) when it is. Full backend suite with this file included and a live Postgres reachable: still 100% pass.

## What risk remains

- Tested on Windows against a local, unauthenticated (`trust`-mode local connections) single-node PostgreSQL 16.4. Production will typically run PostgreSQL on Linux with password/SCRAM authentication, TLS, and possibly a connection pooler (PgBouncer) in front of it — none of those specifics were exercised.
- No load, concurrency, or long-running-connection behavior was tested (a handful of sequential requests only).
- No backup/restore, replication, or failover scenario was tested.
- The `asyncpg` driver was exercised for real for the first time; no other PostgreSQL-specific driver behavior (e.g. prepared statement caching under connection pooling, `SET search_path`) was probed beyond what the app's normal query patterns already touch.
