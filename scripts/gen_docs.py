"""Generate docs/api.md, docs/openapi.json and docs/database.md from the code itself.

    cd backend && .venv/Scripts/python ../scripts/gen_docs.py

The API reference comes from the FastAPI OpenAPI schema and the database reference from the
SQLAlchemy models compiled for PostgreSQL, so neither can drift from the implementation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402

DOCS = ROOT / "docs"

GROUPS = [
    ("Auth", "/auth"), ("Assistant", "/chat", "/conversations", "/memories", "/export", "/documents", "/knowledge", "/meetings"),
    ("Tasks", "/tasks"), ("Reminders", "/reminders"), ("Calendar", "/events"), ("Notes", "/notes"), ("Goals", "/goals"),
    ("Voice & realtime", "/voice", "/ws"), ("Plugins", "/plugins"), ("Workflows", "/workflows"),
    ("Analytics", "/analytics"), ("Sync", "/sync"), ("Preferences & devices", "/preferences", "/devices"), ("Integrations", "/integrations"),
]


def group_of(path: str) -> str:
    rel = path.removeprefix("/api/v1")
    for name, *prefixes in [(g[0], *g[1:]) for g in GROUPS]:
        if any(rel == p or rel.startswith(p + "/") for p in prefixes):
            return name
    return "Ops" if not path.startswith("/api/v1") else "Other"


def api_md(spec: dict) -> str:
    rows: dict[str, list[str]] = {}
    for path, item in sorted(spec["paths"].items()):
        for method, op in item.items():
            secured = any(p.get("name") == "credentials" for p in op.get("parameters", [])) or "security" in op
            auth = "🔒" if secured or path.startswith("/api/v1") and not path.startswith("/api/v1/auth/") else ""
            if path in ("/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout", "/api/v1/auth/google/callback"):
                auth = ""
            summary = (op.get("summary") or "").replace("|", "\\|")
            rows.setdefault(group_of(path), []).append(f"| `{method.upper()}` | `{path}` | {auth} | {summary} |")
    out = [
        "# Wensday — API reference",
        "",
        "> Generated from the FastAPI OpenAPI schema by `scripts/gen_docs.py` — do not edit by hand.",
        "> Interactive docs: `GET /docs` (Swagger) and `GET /redoc` on a running server. Machine-readable: [openapi.json](openapi.json).",
        "",
        "**Base URL** `/api/v1` · **Auth** `Authorization: Bearer <access token>` (🔒 = required) · **Times** ISO-8601, stored and returned as UTC with a trailing `Z`.",
        "",
        "## Conventions",
        "",
        "| | |",
        "|---|---|",
        "| Errors | `{ \"detail\": \"…\" }` — 401 auth, 404 not found (also returned for another user's data), 409 conflict, 422 validation, 429 rate limit, 501 feature not configured |",
        "| Rate limit | `WENSDAY_RATE_LIMIT_PER_MINUTE` per client IP (default 120) |",
        "| Tokens | Access JWT 15 min; refresh JWT 30 days, **rotated on every use**. Replaying an already-used refresh token revokes all of the user's sessions. |",
        "| Sync | `GET /sync?since=<server_time>` returns rows changed since the cursor; deletions come back as `{id, deleted: true}` tombstones. |",
        "| Soft delete | `DELETE` tombstones the row so other devices learn about it. |",
        "",
        "## Chat",
        "",
        "```http",
        "POST /api/v1/chat",
        '{ "text": "Wensday, nalaiku 9 mani meeting remind pannu.", "conversation_id": null, "lang_hint": "auto" }',
        "```",
        "```json",
        '{ "conversation_id": "…", "reply": "Sure Madesh, nalaiku morning 9:00 AM-ku meeting reminder set panniten.",',
        '  "intent": "reminder_create", "lang": "tanglish", "style": "tg", "tier": "rules", "data": {…},',
        '  "speech": [ { "text": "Sure Madesh,", "lang": "en", "voice": "en-IN-NeerjaNeural" }, { "text": "னலைகு …", "lang": "ta", "voice": "ta-IN-PallaviNeural" } ] }',
        "```",
        "`style`: `en` | `tg` (Tanglish) | `ta`. `tier`: `rules` (deterministic NLU) · `llm` · `offline` (fallback message). "
        "`speech` is the reply pre-split into language runs for per-voice text-to-speech.",
        "",
        "## Realtime socket — `GET /api/v1/ws?token=<access token>` (WebSocket)",
        "",
        "| Direction | Message |",
        "|---|---|",
        '| → server | `{"type":"text","text":"…","conversation_id"?,"speak"?:bool}` — a typed turn |',
        '| → server | binary audio frames, then `{"type":"audio_end","mime":"audio/webm","lang_hint"?}` — a spoken turn (needs a server STT provider) |',
        '| → server | `{"type":"cancel"}` — barge-in: stop speaking · `{"type":"ping"}` |',
        '| ← client | `{"type":"ready"}` · `{"type":"transcript","text"}` · `{"type":"reply", …ChatOut}` |',
        '| ← client | `{"type":"audio_start","mime"}`, binary chunks (16 KiB), `{"type":"audio_end"}` (only with a server TTS provider) |',
        '| ← client | `{"type":"reminder.due","id","title","text","style"}` — pushed by the worker |',
        '| ← client | `{"type":"sync","kind","op","id"}` — another device (or a voice command) changed data |',
        '| ← client | `{"type":"error","message"}` · `{"type":"pong"}` · `{"type":"audio_cancelled"}` |',
        "Close code `4401` = the access token is invalid or expired.",
        "",
    ]
    for name in [g[0] for g in GROUPS] + ["Ops", "Other"]:
        if name in rows:
            out += [f"## {name}", "", "| Method | Path | Auth | Summary |", "|---|---|:-:|---|", *rows[name], ""]
    return "\n".join(out)


def database_md() -> str:
    dialect = postgresql.dialect()
    out = [
        "# Wensday — Database reference",
        "",
        "> Generated from the SQLAlchemy models (compiled for PostgreSQL) by `scripts/gen_docs.py` — do not edit by hand.",
        "",
        "**Engines** PostgreSQL in production (`postgresql+asyncpg://…`), SQLite in development and tests (`sqlite+aiosqlite:///…`). "
        "Models use only portable types: 32-char hex string ids, `JSON` columns, naive-UTC `DateTime`.",
        "",
        "**Conventions**",
        "- Every user-owned row has `user_id` (FK → `users`, `ON DELETE CASCADE`); **every query is filtered by it** — there is no cross-user endpoint.",
        "- Syncable tables carry `updated_at` (indexed) and `deleted_at` (tombstone). `DELETE` sets `deleted_at`; it never removes the row, so other devices can learn about the deletion.",
        "- Timestamps are stored as **naive UTC**; the API converts to/from the user's timezone at the edge.",
        "- Vector search: `memories.embedding` / `document_chunks.embedding` / `notes.embedding` hold JSON float arrays (source of truth, so the index can be rebuilt); "
        "Qdrant (collection `memories`, payload `{user_id}`) is the production index when `WENSDAY_QDRANT_URL` is set.",
        "",
        "## Tables",
        "",
        "| Table | Purpose |",
        "|---|---|",
    ]
    purposes = {
        "users": "Accounts (email, name, timezone, language preference)", "oauth_accounts": "Linked Google accounts; tokens **encrypted at rest** (Fernet)",
        "refresh_tokens": "Refresh-token registry for rotation, logout and reuse detection", "devices": "Registered devices / push tokens",
        "preferences": "Structured key→value preferences (name, language, wake word…)", "memories": "Long-term + episodic memory with embeddings and importance",
        "conversations": "Conversation threads", "messages": "Messages (role, text, detected language, intent)", "goals": "Goals", "milestones": "Goal milestones",
        "tasks": "To-dos", "reminders": "One-off and recurring reminders", "events": "Calendar events (local + Google-synced)", "notes": "Notes, meeting notes, summaries",
        "documents": "Uploaded documents for analysis / Q&A", "document_chunks": "Embedded chunks for retrieval", "email_drafts": "Drafts and their send status (draft/sent/queued/discarded)",
        "workflows": "Custom workflows (trigger + steps JSON)", "workflow_runs": "Workflow execution logs", "plugin_settings": "Per-user plugin enablement, granted scopes, config",
        "pending_actions": "Confirmation gate + multi-turn slot state (email send, 'when?' questions)",
    }
    for t in Base.metadata.sorted_tables:
        out.append(f"| `{t.name}` | {purposes.get(t.name, '')} |")
    out += ["", "## DDL (PostgreSQL)", "", "```sql"]
    for t in Base.metadata.sorted_tables:
        out.append(str(CreateTable(t).compile(dialect=dialect)).strip() + ";")
        for ix in sorted(t.indexes, key=lambda i: i.name or ""):
            out.append(str(CreateIndex(ix).compile(dialect=dialect)).strip() + ";")
        out.append("")
    out.append("```")
    return "\n".join(out) + "\n"


def main() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", reminder_worker=False, jwt_secret="x" * 40)
    spec = create_app(settings).openapi()
    DOCS.mkdir(exist_ok=True)
    (DOCS / "openapi.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    (DOCS / "api.md").write_text(api_md(spec), encoding="utf-8")
    (DOCS / "database.md").write_text(database_md(), encoding="utf-8")
    print(f"wrote api.md ({len(spec['paths'])} paths), openapi.json, database.md ({len(Base.metadata.tables)} tables)")


if __name__ == "__main__":
    main()
