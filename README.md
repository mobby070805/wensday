# Wensday

A voice-first personal AI assistant with a calm, respectful female voice — built to treat **Tamil (தமிழ்), English and Tanglish** as first-class languages, not translations of each other.

> "Wensday, nalaiku 9 mani meeting remind pannu."
> → "Sure Madesh, nalaiku morning 9:00 AM-ku meeting reminder set panniten."

> "Naa inniku konjam tired ah iruken."
> → "Okay. Inniku schedule la important tasks mattum prioritize panren."

## What is in the box

| Area | Where | State |
|---|---|---|
| Backend (FastAPI, SQLAlchemy, JWT/OAuth) | [backend/](backend) | **Built and tested** — 312 tests |
| Language system (detect · normalise · NLU · persona) | [backend/app/i18n](backend/app/i18n), [nlu](backend/app/nlu) | **Built and tested** |
| Memory engine (preferences, semantic recall, decay) | [backend/app/memory](backend/app/memory) | **Built and tested** |
| Voice (STT/TTS providers, per-language voices, barge-in) | [backend/app/voice](backend/app/voice) | Built; providers tested against mocks only |
| Integrations (Google Calendar/Gmail) + plugin SDK | [backend/app/integrations](backend/app/integrations), [plugins](backend/app/plugins) | Built; tested against a mocked Google |
| Web app (Next.js + TypeScript) | [web/](web) | Type-checks, 25 unit tests, production build passes; **not exercised in a browser** |
| Mobile app (Flutter) | [mobile/](mobile) | Written to spec; **never compiled or run** (no Flutter SDK available) |
| Docker / Kubernetes / CI | [docker-compose.yml](docker-compose.yml), [deploy/k8s](deploy/k8s), [.github/workflows](.github/workflows) | YAML validated; **never built or applied** (no Docker/cluster available) |

The honest per-phase picture, including every known gap, is in [ROADMAP.md](ROADMAP.md) and [docs/reports/](docs/reports).

## Quick start (backend + web, no Docker needed)

```bash
# 1. backend  → http://localhost:8000/docs
cd backend
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
python -m uvicorn app.main:factory --factory --reload

# 2. web      → http://localhost:3000
cd ../web && npm install && npm run dev
```

Register in the web UI and talk to it. With no LLM key it runs on the built-in rule-based engine, which already handles reminders, tasks, notes, goals, calendar, email drafting and coaching in all three languages. Add `WENSDAY_ANTHROPIC_API_KEY` for open-ended conversation.

Full guides: [setup](docs/setup.md) · [deployment](docs/deployment.md) · [testing](docs/testing.md) · [language system](docs/language-system.md) · [plugins](docs/plugins.md) · [mobile](docs/mobile.md) · [API](docs/api.md) · [database](docs/database.md) · [architecture](docs/architecture.md) · [requirements](docs/requirements.md).

## How a turn works

```
speech/text → language detect (ta | en | tanglish, code-mixing flagged)
            → pending confirmation / slot answer?  → workflow phrase?
            → rule NLU (fast, offline, deterministic)  ──► tool registry ──► your data
            └─ unknown → facts → knowledge (RAG) → LLM with the same tools → offline fallback
            → reply rendered natively in the user's language style
            → split into language runs → Tamil voice / English (en-IN) voice
```

Design principles worth knowing: replies are authored per language (never machine-translated); anything with side effects outside the app (sending email) is **confirmation-gated** and can never be triggered by the LLM directly; every query is scoped by user id; the offline engine means the assistant degrades instead of dying when the LLM is unreachable.

## Repository layout

```
backend/   FastAPI app (app/), tests (tests/), Dockerfile
web/       Next.js app (src/), unit tests (tests/), Dockerfile
mobile/    Flutter app (lib/), tests (test/)
deploy/k8s Kubernetes manifests (kustomize)
docs/      requirements, architecture, guides, generated API/DB reference, phase reports
scripts/   gen_docs.py — regenerates docs/api.md, docs/database.md, docs/openapi.json from the code
```
