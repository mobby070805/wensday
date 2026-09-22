# Wensday — API reference

> Generated from the FastAPI OpenAPI schema by `scripts/gen_docs.py` — do not edit by hand.
> Interactive docs: `GET /docs` (Swagger) and `GET /redoc` on a running server. Machine-readable: [openapi.json](openapi.json).

**Base URL** `/api/v1` · **Auth** `Authorization: Bearer <access token>` (🔒 = required) · **Times** ISO-8601, stored and returned as UTC with a trailing `Z`.

## Conventions

| | |
|---|---|
| Errors | `{ "detail": "…" }` — 401 auth, 404 not found (also returned for another user's data), 409 conflict, 422 validation, 429 rate limit, 501 feature not configured |
| Rate limit | `WENSDAY_RATE_LIMIT_PER_MINUTE` per client IP (default 120) |
| Tokens | Access JWT 15 min; refresh JWT 30 days, **rotated on every use**. Replaying an already-used refresh token revokes all of the user's sessions. |
| Sync | `GET /sync?since=<server_time>` returns rows changed since the cursor; deletions come back as `{id, deleted: true}` tombstones. |
| Soft delete | `DELETE` tombstones the row so other devices learn about it. |

## Chat

```http
POST /api/v1/chat
{ "text": "Wensday, nalaiku 9 mani meeting remind pannu.", "conversation_id": null, "lang_hint": "auto" }
```
```json
{ "conversation_id": "…", "reply": "Sure Madesh, nalaiku morning 9:00 AM-ku meeting reminder set panniten.",
  "intent": "reminder_create", "lang": "tanglish", "style": "tg", "tier": "rules", "data": {…},
  "speech": [ { "text": "Sure Madesh,", "lang": "en", "voice": "en-IN-NeerjaNeural" }, { "text": "னலைகு …", "lang": "ta", "voice": "ta-IN-PallaviNeural" } ] }
```
`style`: `en` | `tg` (Tanglish) | `ta`. `tier`: `rules` (deterministic NLU) · `llm` · `offline` (fallback message). `speech` is the reply pre-split into language runs for per-voice text-to-speech.

## Realtime socket — `GET /api/v1/ws?token=<access token>` (WebSocket)

| Direction | Message |
|---|---|
| → server | `{"type":"text","text":"…","conversation_id"?,"speak"?:bool}` — a typed turn |
| → server | binary audio frames, then `{"type":"audio_end","mime":"audio/webm","lang_hint"?}` — a spoken turn (needs a server STT provider) |
| → server | `{"type":"cancel"}` — barge-in: stop speaking · `{"type":"ping"}` |
| ← client | `{"type":"ready"}` · `{"type":"transcript","text"}` · `{"type":"reply", …ChatOut}` |
| ← client | `{"type":"audio_start","mime"}`, binary chunks (16 KiB), `{"type":"audio_end"}` (only with a server TTS provider) |
| ← client | `{"type":"reminder.due","id","title","text","style"}` — pushed by the worker |
| ← client | `{"type":"sync","kind","op","id"}` — another device (or a voice command) changed data |
| ← client | `{"type":"error","message"}` · `{"type":"pong"}` · `{"type":"audio_cancelled"}` |
Close code `4401` = the access token is invalid or expired.

## Auth

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/auth/google/callback` |  | Google Callback |
| `GET` | `/api/v1/auth/google/login` | 🔒 | Google Login |
| `POST` | `/api/v1/auth/login` |  | Login |
| `POST` | `/api/v1/auth/logout` |  | Logout |
| `GET` | `/api/v1/auth/me` | 🔒 | Me |
| `PATCH` | `/api/v1/auth/me` | 🔒 | Update Me |
| `POST` | `/api/v1/auth/refresh` |  | Refresh |
| `POST` | `/api/v1/auth/register` |  | Register |

## Assistant

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `POST` | `/api/v1/chat` | 🔒 | Chat |
| `GET` | `/api/v1/conversations` | 🔒 | List Conversations |
| `DELETE` | `/api/v1/conversations/{cid}` | 🔒 | Delete Conversation |
| `GET` | `/api/v1/conversations/{cid}/messages` | 🔒 | Conversation Messages |
| `GET` | `/api/v1/documents` | 🔒 | List Documents |
| `POST` | `/api/v1/documents` | 🔒 | Add Document |
| `DELETE` | `/api/v1/documents/{did}` | 🔒 | Delete Document |
| `GET` | `/api/v1/export` | 🔒 | Export My Data |
| `POST` | `/api/v1/knowledge/ask` | 🔒 | Ask |
| `POST` | `/api/v1/meetings/summarize` | 🔒 | Summarize Meeting |
| `GET` | `/api/v1/memories` | 🔒 | List Memories |
| `POST` | `/api/v1/memories` | 🔒 | Add Memory |
| `DELETE` | `/api/v1/memories` | 🔒 | Forget All |
| `POST` | `/api/v1/memories/reindex` | 🔒 | Reindex |
| `GET` | `/api/v1/memories/search` | 🔒 | Search Memories |
| `DELETE` | `/api/v1/memories/{mid}` | 🔒 | Forget |

## Tasks

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/tasks` | 🔒 | List  |
| `POST` | `/api/v1/tasks` | 🔒 | Create |
| `GET` | `/api/v1/tasks/{id}` | 🔒 | Read |
| `PATCH` | `/api/v1/tasks/{id}` | 🔒 | Update |
| `DELETE` | `/api/v1/tasks/{id}` | 🔒 | Delete |

## Reminders

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/reminders` | 🔒 | List  |
| `POST` | `/api/v1/reminders` | 🔒 | Create |
| `GET` | `/api/v1/reminders/{id}` | 🔒 | Read |
| `PATCH` | `/api/v1/reminders/{id}` | 🔒 | Update |
| `DELETE` | `/api/v1/reminders/{id}` | 🔒 | Delete |

## Calendar

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/events` | 🔒 | List  |
| `POST` | `/api/v1/events` | 🔒 | Create |
| `GET` | `/api/v1/events/{id}` | 🔒 | Read |
| `PATCH` | `/api/v1/events/{id}` | 🔒 | Update |
| `DELETE` | `/api/v1/events/{id}` | 🔒 | Delete |

## Notes

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/notes` | 🔒 | List  |
| `POST` | `/api/v1/notes` | 🔒 | Create |
| `GET` | `/api/v1/notes/{id}` | 🔒 | Read |
| `PATCH` | `/api/v1/notes/{id}` | 🔒 | Update |
| `DELETE` | `/api/v1/notes/{id}` | 🔒 | Delete |

## Goals

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/goals` | 🔒 | List Goals |
| `POST` | `/api/v1/goals` | 🔒 | Create Goal |
| `GET` | `/api/v1/goals/{id}` | 🔒 | Read Goal |
| `PATCH` | `/api/v1/goals/{id}` | 🔒 | Update Goal |
| `DELETE` | `/api/v1/goals/{id}` | 🔒 | Delete Goal |
| `POST` | `/api/v1/goals/{id}/milestones` | 🔒 | Add Milestone |
| `POST` | `/api/v1/goals/{id}/milestones/{mid}/toggle` | 🔒 | Toggle Milestone |

## Voice & realtime

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/voice/config` | 🔒 | Voice Config |
| `POST` | `/api/v1/voice/speak` | 🔒 | Speak |
| `POST` | `/api/v1/voice/transcribe` | 🔒 | Transcribe |

## Plugins

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/plugins` | 🔒 | List Plugins |
| `POST` | `/api/v1/plugins/{name}/disable` | 🔒 | Disable Plugin |
| `POST` | `/api/v1/plugins/{name}/enable` | 🔒 | Enable Plugin |

## Workflows

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/workflows` | 🔒 | List Workflows |
| `POST` | `/api/v1/workflows` | 🔒 | Create Workflow |
| `DELETE` | `/api/v1/workflows/{wid}` | 🔒 | Delete Workflow |
| `POST` | `/api/v1/workflows/{wid}/run` | 🔒 | Run Workflow |

## Analytics

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/analytics/dashboard` | 🔒 | Dashboard |
| `GET` | `/api/v1/analytics/weekly-review` | 🔒 | Weekly Review |

## Sync

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/sync` | 🔒 | Sync |

## Preferences & devices

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/devices` | 🔒 | List Devices |
| `POST` | `/api/v1/devices` | 🔒 | Register Device |
| `DELETE` | `/api/v1/devices/{did}` | 🔒 | Remove Device |
| `GET` | `/api/v1/preferences` | 🔒 | Get Preferences |
| `PUT` | `/api/v1/preferences/{key}` | 🔒 | Put Preference |

## Integrations

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/api/v1/integrations/gmail/inbox` | 🔒 | Gmail Inbox |
| `POST` | `/api/v1/integrations/google/calendar/sync` | 🔒 | Google Calendar Sync |
| `GET` | `/api/v1/integrations/status` | 🔒 | Integrations Status |

## Ops

| Method | Path | Auth | Summary |
|---|---|:-:|---|
| `GET` | `/healthz` |  | Healthz |
| `GET` | `/metrics` |  | Prom |
| `GET` | `/readyz` |  | Readyz |
