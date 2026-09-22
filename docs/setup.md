# Setup guide

## Prerequisites
| Tool | Version | For |
|---|---|---|
| Python | 3.12+ (developed on 3.14) | backend |
| Node.js | 22+ | web |
| Flutter | 3.22+ | mobile (optional) |
| Docker | 24+ | full stack with Postgres/Redis/Qdrant (optional) |

The backend needs **no external service** to run: SQLite replaces Postgres, an in-process cache replaces Redis, and an in-memory index replaces Qdrant.

## 1 · Backend
```bash
cd backend
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                   # then edit
python -m uvicorn app.main:factory --factory --reload  # http://localhost:8000/docs
python -m pytest -q                                    # 312 tests
```
Minimum `.env` for local work: nothing (defaults are fine). For anything shared, set `WENSDAY_JWT_SECRET` to a long random string.

### Database migrations (Alembic)

SQLite dev/test databases are still created automatically (`WENSDAY_AUTO_CREATE_TABLES=true`, the default). Anywhere the schema needs to be reproducible — PostgreSQL, staging, production — use Alembic instead:

```bash
cd backend
python -m alembic upgrade head                        # apply every pending migration
python -m alembic current                              # what revision is this database at?
python -m alembic revision --autogenerate -m "add X"   # after changing app/models.py
python -m alembic upgrade head --sql                    # preview the SQL without connecting (any dialect, e.g. postgresql://...)
```

The database URL comes from `WENSDAY_DATABASE_URL` (or `.env`) automatically — there's nothing to edit in `alembic.ini`. If a database already has an `alembic_version` table, the app's own `create_all` refuses to run against it even if `AUTO_CREATE_TABLES` is left on, so the two mechanisms can't collide. `tests/test_migrations.py` runs `alembic upgrade head`, `downgrade base`, and `check` (drift detection) for real on every CI run.

### Configuration reference (all `WENSDAY_*`)
| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./wensday.db` | `postgresql+asyncpg://user:pw@host/db` in production |
| `REDIS_URL` / `QDRANT_URL` | unset | enable multi-replica event fan-out / production vector index |
| `JWT_SECRET` | dev value | **change in any shared environment** |
| `TOKEN_ENCRYPTION_KEY` | derived from JWT secret | Fernet key for stored OAuth tokens |
| `LLM_CHAIN` | `["anthropic","openai_compat","offline"]` | failover order; `offline` is always appended |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | – / `claude-sonnet-5` | primary LLM |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | – | any OpenAI-compatible server; for **Ollama/vLLM** set `OPENAI_BASE_URL=http://localhost:11434/v1` (no key needed) |
| `EMBEDDING_PROVIDER` | `hashing` | `hashing` (offline, language-aware) or `openai_compat` |
| `STT_PROVIDER` / `TTS_PROVIDER` | `browser` | `browser` = the client does speech; server options `whisper`, `azure` |
| `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` | – | Azure STT/TTS (voices `ta-IN-PallaviNeural`, `en-IN-NeerjaNeural`) |
| `WHISPER_BASE_URL` | – | OpenAI-compatible `/audio/transcriptions` server |
| `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` | – | Google sign-in, Calendar, Gmail |
| `REMINDER_WORKER` | `true` | run background jobs inside the API process; set `false` when a separate worker runs |
| `PLUGIN_DIR` | unset | directory of extra plugin `.py` files |

## 2 · Web
```bash
cd web
cp .env.example .env.local        # NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
npm install
npm run dev                       # http://localhost:3000
npm run typecheck && npm test && npm run build
```
**Voice needs Chrome or Edge** (Web Speech API) and microphone permission. Space bar = push-to-talk; the "hands-free" toggle listens continuously and acts only on utterances starting with "Wensday".

## 3 · Google OAuth (optional)
1. Google Cloud Console → APIs & Services → create an OAuth client (Web). Redirect URI: `http://localhost:8000/api/v1/auth/google/callback`.
2. Enable the Calendar API and Gmail API. Set `WENSDAY_GOOGLE_CLIENT_ID/SECRET`.
3. "Continue with Google" on the login page signs in with the minimum scopes. Calendar/Gmail access is requested separately (incremental consent) via `GET /auth/google/login?features=calendar,gmail_send,gmail_read` while signed in.

## 4 · An LLM (optional but recommended)
`WENSDAY_ANTHROPIC_API_KEY=…` — or run a local model: `ollama serve`, then `WENSDAY_OPENAI_BASE_URL=http://localhost:11434/v1`, `WENSDAY_OPENAI_MODEL=<model>`. Without any LLM, rule-based commands still work fully; open-ended questions get an honest "offline mode" reply.

## 5 · Better voice
| Goal | Do this |
|---|---|
| Natural Tamil female voice on desktop | Install a Tamil (India) voice in your OS (Windows: Settings → Time & language → Speech → add voices → Tamil) |
| Same voices everywhere | `STT_PROVIDER=azure`, `TTS_PROVIDER=azure` + Azure key/region. Reply text is transliterated per language run and sent as SSML with `ta-IN`/`en-IN` voices. |
| Self-hosted STT | run a Whisper-compatible server, `STT_PROVIDER=whisper`, `WHISPER_BASE_URL=…` |

## 6 · Full stack with Docker
```bash
docker compose up --build        # web :3000, api :8000/docs — Postgres, Redis, Qdrant, worker included
```

## Troubleshooting
| Symptom | Cause / fix |
|---|---|
| Web UI: "Failed to fetch" | API not running, or `WENSDAY_CORS_ORIGINS` doesn't include the web origin |
| Mic button does nothing | Not Chrome/Edge, or mic permission denied, or the page isn't on `localhost`/HTTPS |
| Tamil text shows as `?` on Windows terminals | `set PYTHONUTF8=1` |
| Replies say "offline mode" for open questions | No LLM configured — expected; see step 4 |
| Reminders don't fire | `REMINDER_WORKER=false` and no worker running, or the web socket is disconnected (the reminder still fires; only the live push is missed) |
