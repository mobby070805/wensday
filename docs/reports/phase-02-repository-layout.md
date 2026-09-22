# Phase 2 — Repository layout · **100 %**

```
backend/   app/{core,i18n,nlu,llm,agent,memory,voice,services,routers,integrations,plugins}  tests/  Dockerfile
web/       src/{app,components,lib}  tests/  Dockerfile
mobile/    lib/{core,voice,state,ui}  test/
deploy/k8s  kustomize manifests        docker-compose.yml        .github/workflows/ci.yml
docs/      guides, generated API/DB reference, reports            scripts/gen_docs.py
```
**Principles:** routers (HTTP) → agent (orchestration) → services (business logic) → models; the language layer (`i18n`, `nlu`) has no web or DB dependencies so it is independently testable; every external dependency (LLM, embeddings, vector store, STT/TTS, mailer, HTTP client) is an injectable interface with an in-process fallback.

**Gap:** the repo is not under git (the workspace was not a git repository) — run `git init` before the first commit. A root `.gitignore` is in place; commit `web/package-lock.json` (the Docker build uses `npm ci`).
