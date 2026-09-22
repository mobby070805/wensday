# Wensday — Architecture

## 1. System context

```
 ┌────────────┐  ┌────────────┐  ┌────────────┐
 │  Web (Next)│  │ Flutter app│  │ Desktop PWA│
 │ mic/speaker│  │ mic/speaker│  │            │
 └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
       │ REST + WS (JWT)                │
       └───────────────┬────────────────┘
                 ┌─────▼──────┐
                 │  FastAPI   │  routers → services → repositories
                 │  gateway   │
                 └─┬───┬───┬──┘
      ┌────────────┘   │   └───────────────┐
┌─────▼─────┐   ┌──────▼──────┐     ┌──────▼───────┐
│  Agent    │   │ Memory      │     │ Integrations │
│ orchestr. │   │ engine      │     │ Google Cal/  │
│ NLU+LLM   │   │ prefs+vector│     │ Gmail/Plugins│
└─┬───────┬─┘   └──┬───────┬──┘     └──────────────┘
  │       │        │       │
┌─▼──┐ ┌──▼───┐ ┌──▼───┐ ┌─▼─────┐
│LLM │ │Voice │ │Postgr│ │Qdrant │  + Redis (cache, pubsub, rate limit)
│prov│ │STT/TTS│ │  SQL │ │       │
└────┘ └──────┘ └──────┘ └───────┘
```

## 2. Key design decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Language layer is native, not translated.** `app/i18n` owns detection, normalisation, lexicon and persona lines for `ta`/`en`/`tanglish`. | Brief requires first-class languages; also makes offline mode possible. |
| D2 | **Two-tier understanding.** Tier 1: deterministic NLU (`app/nlu`) resolves intents + entities. Tier 2: LLM handles open conversation and complex reasoning and can call the same tool registry. | Low latency and reliability for commands ("reminder set pannu"); LLM for everything else. |
| D3 | **One Tool Registry.** Built-in services, workflows and plugins register `Tool`s (name, JSON schema, permission scope, handler). Both NLU and LLM tool-calling go through it. | One surface to secure, test and extend. |
| D4 | **Provider abstraction** for LLM, embeddings, STT, TTS, vector store, cache. Each has an in-process fallback. | Runs anywhere; CI needs no external services. |
| D5 | **Confirmation gate** for side-effecting external actions (send mail, delete). Tools declare `requires_confirmation`; agent stores a pending action and asks. | Matches "Review panna venduma illa direct send panna venduma?" |
| D6 | **Sync by cursor.** Every syncable row has `updated_at`, `deleted_at`; devices pull `GET /sync?since=`; server pushes change events over WS. | Simple, robust LWW for a personal assistant. |
| D7 | SQLAlchemy 2 async; SQLite (dev/test) and PostgreSQL (prod) via URL. Portable types only (JSON, String UUIDs). | Fast tests, prod parity. |
| D8 | Memory engine: **structured prefs** (relational) + **episodic vectors** (Qdrant or in-memory) with hashing-based local embeddings as offline default. | Deterministic tests; swap in real embeddings via provider. |

## 3. Backend layering

```
routers/   HTTP + WS, validation, auth dependency
agent/     orchestrator (turn loop), tool registry, confirmation state
nlu/       intent classifier, entity extractors (time, task text, contact…)
i18n/      language detect, normalise, lexicon, persona
llm/       provider interface + Anthropic / OpenAI-compatible / Offline
memory/    preferences, episodic store, recall + decay, embeddings, vector stores
voice/     STT/TTS provider interfaces, SSML/language-run splitter, WS voice session
services/  business logic (tasks, reminders, notes, goals, calendar, email, coaching, docs, meetings, workflows, analytics)
integrations/ Google Calendar, Gmail, browser-assist adapters
plugins/   SDK + loader + example plugin
models.py  ORM       schemas.py  Pydantic DTOs
```

## 4. Turn lifecycle (voice or text)

1. Client sends audio chunks (or text) on `/ws/voice` or `POST /api/v1/chat`.
2. STT → text (skipped for typed input).
3. `i18n.detect` → `LangProfile(lang, script, mixed, register)`.
4. Voice-command grammar & NLU run. High-confidence intent → tool call directly.
5. Otherwise: memory recall + preferences → prompt → LLM (with tool schema) → tool loop.
6. Persona layer renders reply in the mirrored language style.
7. TTS splits reply into language runs → audio stream; text always sent too (captions).
8. Turn stored as episodic memory candidate; importance-scored.

## 5. Data model (summary — full DDL in `docs/database.md`)

`users`, `devices`, `preferences`, `memories`, `conversations`, `messages`, `tasks`, `reminders`, `events`, `notes`, `documents`, `document_chunks`, `goals`, `milestones`, `workflows`, `workflow_runs`, `plugins_installed`, `oauth_accounts`, `pending_actions`.

## 6. Security model

- OAuth2 authorization-code (Google) → server issues its own JWT pair (access 15 min, refresh 30 d, rotation).
- Every repository query is filtered by `user_id`; there is no cross-user endpoint.
- Plugins declare scopes (`tasks:read`, `net:fetch`, …); the registry refuses tools whose scopes the user has not granted.
- External-send tools always require confirmation unless the user opts a specific tool into auto-approve.

## 7. Deployment topology

Docker images for `api`, `web`; Kubernetes: Deployments (api, web, worker), StatefulSets/managed services for Postgres, Redis, Qdrant; Ingress with TLS; HPA on api; CronJob-free reminder worker using a leader-elected loop (Redis lock). See `docs/deployment.md`.

## 8. Phases

See `ROADMAP.md` for live status and completion percentages.
