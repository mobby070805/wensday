# Phase 3 — Backend · **90 %**

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
- **No database migrations.** Schema is created with `create_all` only; introduce Alembic before the first production schema change.
- Tested only on SQLite; PostgreSQL DDL is generated ([database.md](../database.md)) but never executed.
- Password reset, email verification and account deletion endpoints are not implemented.
- Rate limiting is per IP and in-memory unless Redis is configured (and the Redis path is untested).
- "Email summarisation" is implemented for the Gmail inbox only (needs Google connected); there is no attachment handling.
