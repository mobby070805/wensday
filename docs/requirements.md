# Wensday — Requirements Specification

Wensday is a voice-first personal AI assistant with a warm, calm, efficient female persona. It runs on web, desktop (web/PWA shell) and mobile (Flutter) against one backend, and treats **Tamil, English and Tanglish as first-class languages**.

## 1. Personas & primary scenarios

| Persona | Scenario |
|---|---|
| Working professional (Chennai) | "Wensday, nalaiku 9 mani meeting remind pannu." while commuting |
| Manager | "Send a mail to client and mention quotation ready." → draft → confirm → send |
| Student / self-learner | Goal tracking, coaching, note-taking, document Q&A |
| Low-connectivity user | Offline fallback: reminders, tasks, notes keep working with the rule-based engine |

## 2. Functional requirements

IDs map 1:1 to the 20 core capabilities in the brief.

| ID | Capability | Acceptance criteria |
|---|---|---|
| F1 | Natural voice conversation | Streaming STT → agent → streaming TTS over WebSocket; barge-in supported; < 1.5 s first audio target on cloud providers |
| F2 | Preference memory | Structured key/value facts (name, wake word, tone, voice, work hours) persisted per user and injected into every prompt |
| F3 | Long-term contextual memory | Episodic memories embedded and stored in a vector index; top-k recall on each turn; importance decay; user can list/delete |
| F4 | Calendar | CRUD events; conflict detection; Google Calendar sync adapter |
| F5 | Tasks | CRUD, priority, due date, status, tags; energy-aware prioritisation |
| F6 | Email | Draft from intent, summarise thread, send only after confirmation |
| F7 | Notes | CRUD, tags, full-text + semantic search |
| F8 | Knowledge retrieval | RAG over notes, documents and memories with citations |
| F9 | Document analysis | Upload text/markdown/PDF-text; chunk, embed, summarise, ask questions |
| F10 | Meeting summaries | Transcript → summary, decisions, action items (auto-creates tasks on approval) |
| F11 | Productivity coaching | Mood/energy aware daily plan; nudges; weekly review |
| F12 | Goal tracking | Goals with milestones and progress %; linked tasks |
| F13 | Reminders | One-off and recurring; delivered via WebSocket push, mobile local notification, email fallback |
| F14 | Multi-device sync | Per-user event stream + `updated_at` cursor pull; last-writer-wins with tombstones |
| F15 | Custom workflows | Trigger (intent/schedule/event) → ordered steps (tool calls) declared as JSON |
| F16 | Browser assistance | Extension-safe tools: open URL, summarise page text supplied by client, search |
| F17 | Voice commands | Deterministic command grammar (works offline) that short-circuits the LLM |
| F18 | Offline fallback | Rule-based NLU + local templates handle core intents with no network/LLM |
| F19 | Dashboard & analytics | Task throughput, goal progress, streaks, language usage, reminder stats |
| F20 | Plugin architecture | Python plugin SDK: declare tools, intents, settings; hot-registered; sandboxed by permission scopes |

## 3. Language system (critical)

| ID | Requirement |
|---|---|
| L1 | Per-utterance detection of `ta` (Tamil script), `en`, `tanglish` (Tamil in Latin script), plus `mixed` sub-flag for code-switching |
| L2 | No translation pivot: the NLU lexicon contains Tamil-script, Tanglish and English surface forms for every intent, entity word and time expression |
| L3 | Replies mirror the user's language style: Tamil script → Tamil script; Tanglish → Tanglish; English → English; mixed → Tanglish-leaning |
| L4 | Chennai-Tamil register and informal speech ("da", "pannu", "iruken", "poitu varen") understood; incomplete grammar tolerated |
| L5 | Tanglish spelling variance handled (`nalaiku/naalaiku/nalaikku`, `pannu/panu/pannunga`) through normalisation + fuzzy match |
| L6 | Time expressions in all three: `9 mani`, `காலை 9 மணி`, `nalaiku morning 9`, `tomorrow 9am`, `inniku sayangalam 5 mani` |
| L7 | Persona lines (confirmations, errors, clarifications) are authored natively per language, not machine-translated |
| L8 | LLM system prompt instructs the model on the same mirroring rules; offline engine enforces them itself |

## 4. Voice requirements

- Female voice; selectable South-Indian-accent option (`ta-IN` / `en-IN` neural voices).
- Provider-abstracted STT and TTS (Whisper/Azure/Google/Web Speech; Azure `ta-IN-PallaviNeural`, `en-IN-NeerjaNeural`; browser SpeechSynthesis fallback).
- Mixed-language TTS: reply is split into language runs (Tamil script / Latin) and each run is rendered with the matching voice or SSML `<lang>` tag.
- Wake word "Wensday" handled client-side; server validates.

## 5. Non-functional requirements

| Area | Requirement |
|---|---|
| Security | OAuth2 (Google) + JWT access/refresh; scrypt password hashing; per-user row scoping on every query; secrets via env; rate limiting; PII never logged |
| Privacy | Memories deletable; export endpoint; provider calls minimise PII; on-device offline mode |
| Performance | p95 REST < 300 ms (excluding LLM); WS turn latency dominated by providers |
| Reliability | Provider failover chain (primary → secondary → offline engine); idempotent writes for sync |
| Observability | Structured JSON logs, request IDs, `/healthz`, `/readyz`, Prometheus `/metrics` (planned) |
| Portability | SQLite for dev/tests, PostgreSQL in prod; in-memory vector/cache fallbacks for Qdrant/Redis |
| Accessibility | Keyboard-operable web UI, captions for all voice output, adjustable speech rate |
| Testability | Every phase ships tests; CI runs backend, web and Flutter suites |

## 6. Out of scope for v1

Smart-home control, telephony (actual phone calls — "call pannu" is recorded as an intent and handed to the device dialer), payments.

## 7. Assumptions (decisions taken without asking)

1. The user's display name defaults from OAuth profile; the sample persona addresses the user by first name ("Madesh").
2. LLM providers are pluggable; default cloud provider is Anthropic, default fallback is the offline engine. No API key is committed.
3. STT/TTS heavy lifting is done by providers or the client browser/OS; the server owns orchestration, language routing and SSML generation.
4. Flutter and Docker artefacts are authored to spec but only validated where tooling exists (see reports).
