# Phase 10 — Deployment system · **60 %** (authored, unexecuted)

**Delivered:** multi-stage, non-root Dockerfiles for API/worker and web (Next.js standalone) · `docker-compose.yml` (Postgres, Redis, Qdrant, API, worker, web, health-checked) · Kubernetes manifests via kustomize: API Deployment (rolling, probes, resources, read-only root FS, dropped capabilities) + HPA + PDB, dedicated **worker** Deployment, web Deployment, in-cluster Postgres/Redis/Qdrant for dev/staging, Ingress with TLS and websocket timeouts, NetworkPolicy restricting data stores to API/worker · GitHub Actions: backend (Py 3.12/3.13), web, mobile, manifest validation, image build & push to GHCR, gated deploy with rollout checks · Prometheus-format `/metrics`, `/healthz`, `/readyz` · [deployment guide](../deployment.md).

**Verified:** every YAML file parses; every workload declares resource requests. A real `uvicorn` process was exercised over HTTP (health, readiness, CORS preflight, auth enforcement, three-language chat).

**Not verified — treat as a first draft:** no image has been built, no compose stack started, no manifest applied, no CI run. Docker and Kubernetes were not available. Likely first-contact issues: image tags/owner placeholders (`ghcr.io/OWNER/…`), `web/package-lock.json` must be committed for `npm ci`, ingress annotations assume ingress-nginx + cert-manager, and PostgreSQL has never been used with this code (asyncpg + the generated DDL).

**Known operational gaps:** no schema migrations (Alembic) · no Redis integration test though multi-replica push depends on it · no secrets manager wiring (manual `kubectl create secret`) · no log aggregation/tracing config · Prometheus alert rules and dashboards not provided · no backup CronJobs.
