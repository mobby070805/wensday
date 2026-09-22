# Deployment guide

> **Status:** these manifests and Dockerfiles were written and their YAML validated, but **never built or applied** — no Docker daemon or cluster was available. Expect to fix small things on first contact; the CI job `manifests` (kubeconform) and a staging deploy are the intended safety nets.

## Topology
```
            Ingress (TLS, websocket timeouts)
             ├── wensday.example.com     → web  (Next.js, 2+ replicas)
             └── api.wensday.example.com → api  (FastAPI, 2–10 replicas, HPA on CPU)
                                              │
   worker (1 replica: reminders + scheduled workflows) ─┤
                                              ├── PostgreSQL  (system of record)
                                              ├── Redis       (cache, rate-limit, event fan-out across replicas)
                                              └── Qdrant      (vector index; optional — falls back to in-process)
```
**Why a separate worker.** Reminder firing must not depend on how many API pods exist. Firing is *claim-based* (a conditional `UPDATE … WHERE status='pending' AND due_at=<read value>`), so even if two workers overlap during a rollout each reminder fires exactly once — covered by a test. The worker publishes to Redis; every API replica forwards those events to its connected sockets, so **Redis is required as soon as you run more than one API replica or a separate worker.**

## 1 · Local full stack
`docker compose up --build` → web :3000, API :8000. Set `WENSDAY_JWT_SECRET` in your shell first.

## 2 · Kubernetes
```bash
# secrets (never commit these)
kubectl create namespace wensday
kubectl -n wensday create secret generic wensday-secrets \
  --from-literal=WENSDAY_DATABASE_URL='postgresql+asyncpg://wensday:<pw>@postgres:5432/wensday' \
  --from-literal=WENSDAY_JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  --from-literal=WENSDAY_TOKEN_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')" \
  --from-literal=WENSDAY_ANTHROPIC_API_KEY=… \
  --from-literal=WENSDAY_GOOGLE_CLIENT_ID=… --from-literal=WENSDAY_GOOGLE_CLIENT_SECRET=…
kubectl -n wensday create secret generic wensday-postgres --from-literal=password='<pw>'

# edit hostnames in deploy/k8s/10-config.yaml and 60-ingress.yaml, image owner in 20/30/40
kubectl apply -k deploy/k8s
kubectl -n wensday rollout status deploy/api deploy/worker deploy/web
```
**Production checklist**
- [ ] Use managed Postgres and Redis; remove `50-data.yaml` from `kustomization.yaml`.
- [ ] `WENSDAY_JWT_SECRET` ≥ 32 random bytes; `WENSDAY_TOKEN_ENCRYPTION_KEY` set (otherwise derived from the JWT secret — rotating one then breaks stored OAuth tokens).
- [ ] **Schema management:** the app can `create_all()` on start (`AUTO_CREATE_TABLES=true`) which only *creates missing tables*. There are **no migrations yet** (Alembic is on the roadmap); before the first schema change in production, introduce Alembic and set `AUTO_CREATE_TABLES=false`.
- [ ] TLS via cert-manager; the ingress annotations extend proxy timeouts to 1 h for websockets.
- [ ] Web image: `NEXT_PUBLIC_API_URL` is baked in at **build** time — build per environment.
- [ ] Set `WENSDAY_CORS_ORIGINS` to exactly your web origin.
- [ ] Backups: Postgres PITR; Qdrant snapshots (or rebuild: `POST /memories/reindex` re-indexes from Postgres, which is the source of truth).
- [ ] Alert on `/readyz` failures and 5xx rate from `/metrics` (Prometheus text format).

## 3 · CI/CD (GitHub Actions — `.github/workflows/ci.yml`)
| Job | Runs |
|---|---|
| `backend` | pytest on Python 3.12 and 3.13 |
| `web` | `tsc --noEmit`, vitest, `next build` |
| `mobile` | `flutter analyze`, `flutter test` |
| `manifests` | kubeconform on `deploy/k8s`, `docker compose config` |
| `images` (main only) | build & push `wensday-api` and `wensday-web` to GHCR |
| `deploy` (main only, needs `vars.DEPLOY_ENABLED=true`, secret `KUBE_CONFIG` = base64 kubeconfig) | `kubectl apply -k`, set images to the commit SHA, wait for rollout |

Repository settings: variable `PUBLIC_API_URL` (build arg for the web image); environment `production` with required reviewers is recommended.

## 4 · Rollback
`kubectl -n wensday rollout undo deploy/api` (and `worker`, `web`). Database changes are additive only until migrations exist, so rolling the image back is safe.

## 5 · Operational notes
- **Scaling:** API is stateless (JWT + DB + Redis). Websockets are per-pod; any pod can serve any user thanks to Redis fan-out.
- **LLM outage:** the router fails over provider→provider and finally to the offline engine; nothing needs a restart. A provider that errors is skipped for 30 s (circuit breaker).
- **Privacy:** users can export (`GET /export`) and erase (`DELETE /memories`) what Wensday remembers. Logs contain request ids and paths, never message text.
