# Deployment guide

> **Status:** these manifests and Dockerfiles were written and their YAML validated, but **never built or applied** — no Docker daemon or cluster was available. Expect to fix small things on first contact; the CI job `manifests` (kubeconform) and a staging deploy are the intended safety nets. What *has* been executed and verified: the migration DDL (`tests/test_migrations.py` — 9 tests, real `alembic upgrade head`/`downgrade base`/`check` against SQLite, plus offline PostgreSQL SQL emission) and Redis resilience (`tests/test_redis_compat.py` — 10 tests against fakeredis, a real in-process RESP-protocol server).

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
`docker compose up --build` → web :3000, API :8000. Set `WENSDAY_JWT_SECRET` in your shell first. The `api` service's entrypoint is the server itself; run migrations once against the same Postgres before or right after first start: `docker compose run --rm api python -m alembic upgrade head`.

## 2 · Staging deployment
Staging exists to answer one question before production does: *does this actually work against real Postgres, real Redis, and a real cluster* — none of which this build environment had. Use a separate namespace/cluster from production (or the same cluster, a `wensday-staging` namespace) with the same manifests:

```bash
kubectl create namespace wensday-staging
# same secrets recipe as below, created in wensday-staging instead of wensday
kubectl apply -k deploy/k8s -n wensday-staging          # namespace field in the manifests still says `wensday` — override with -n or edit 00-namespace.yaml's copy for staging
kubectl -n wensday-staging apply -f deploy/k8s/25-migrate-job.yaml
kubectl -n wensday-staging wait --for=condition=complete job/db-migrate --timeout=120s
kubectl -n wensday-staging rollout status deploy/api deploy/worker deploy/web
```

Before promoting to production, confirm on staging: `/readyz` returns `{"status":"ready"}` with a real Postgres URL configured; `tests/test_redis_compat.py`'s claims hold against a real `redis-server` (`redis-cli monitor` while using the app is a quick sanity check); a full voice turn works in an actual browser with a microphone; Google OAuth completes end to end if configured. None of these were possible to verify in the environment this codebase was built in.

## 3 · Production deployment (Kubernetes)
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

# schema first, every release (idempotent; see deploy/k8s/25-migrate-job.yaml)
kubectl -n wensday delete job db-migrate --ignore-not-found
kubectl -n wensday apply -f deploy/k8s/25-migrate-job.yaml
kubectl -n wensday wait --for=condition=complete job/db-migrate --timeout=120s

kubectl -n wensday rollout status deploy/api deploy/worker deploy/web
```
**Production checklist**
- [ ] Use managed Postgres and Redis; remove `50-data.yaml` from `kustomization.yaml`.
- [ ] `WENSDAY_JWT_SECRET` ≥ 32 random bytes; `WENSDAY_TOKEN_ENCRYPTION_KEY` set (otherwise derived from the JWT secret — rotating one then breaks stored OAuth tokens).
- [x] **Schema management:** Alembic migrations exist (`backend/alembic/`, one baseline revision covering all 21 tables). Run `alembic upgrade head` (the `db-migrate` Job) before every rollout; `WENSDAY_AUTO_CREATE_TABLES` is `false` in `10-config.yaml`, and the app refuses to run `create_all` against a database that already has an `alembic_version` table even if that were left on. Verified: `alembic upgrade head`/`downgrade base`/`check` (drift detection) run for real against SQLite in CI, and `alembic upgrade head --sql` against a `postgresql://` URL confirms the DDL is valid PostgreSQL with no live server required. **Not yet verified: an actual migration against a live PostgreSQL server.**
- [ ] TLS via cert-manager; the ingress annotations extend proxy timeouts to 1 h for websockets.
- [ ] Web image: `NEXT_PUBLIC_API_URL` is baked in at **build** time — build per environment.
- [ ] Set `WENSDAY_CORS_ORIGINS` to exactly your web origin.
- [ ] Backups: Postgres PITR; Qdrant snapshots (or rebuild: `POST /memories/reindex` re-indexes from Postgres, which is the source of truth).
- [ ] Alert on `/readyz` failures and 5xx rate from `/metrics` (Prometheus text format).
- [x] **Redis resilience:** `RedisCache` and `EventHub` both degrade to local, per-replica behaviour rather than raising when Redis is unreachable mid-session (a rate-limited endpoint returns 200, not 500, during a Redis outage — verified against fakeredis). The pubsub listener reconnects with backoff after a dropped connection instead of dying silently.

## 4 · CI/CD (GitHub Actions — `.github/workflows/ci.yml`)
| Job | Runs |
|---|---|
| `backend` | pytest on Python 3.12 and 3.13 (includes the migration and Redis-compat suites) |
| `web` | `tsc --noEmit`, vitest, `next build` |
| `mobile` | `flutter analyze`, `flutter test` |
| `manifests` | kubeconform on `deploy/k8s` (including the migration Job), `docker compose config` |
| `images` (main only) | build & push `wensday-api` and `wensday-web` to GHCR |
| `deploy` (main only, needs `vars.DEPLOY_ENABLED=true`, secret `KUBE_CONFIG` = base64 kubeconfig) | `kubectl apply -k`, run the `db-migrate` Job to completion (fails the deploy on migration failure), set images to the commit SHA, wait for rollout |

Repository settings: variable `PUBLIC_API_URL` (build arg for the web image); environment `production` with required reviewers is recommended.

## 5 · Rollback
`kubectl -n wensday rollout undo deploy/api` (and `worker`, `web`) rolls the *code* back. **The database does not roll back automatically** — Alembic migrations are forward-only here (no automated `alembic downgrade` step in CI, by design: a bad downgrade against production data is often more dangerous than the bug it's fixing). Write migrations additively (new nullable columns/tables) so an old image version keeps working against a newer schema for at least one release, and only run `alembic downgrade` by hand, deliberately, after checking what it would actually drop.

## 6 · Operational notes
- **Scaling:** API is stateless (JWT + DB + Redis). Websockets are per-pod; any pod can serve any user thanks to Redis fan-out.
- **LLM outage:** the router fails over provider→provider and finally to the offline engine; nothing needs a restart. A provider that errors is skipped for 30 s (circuit breaker).
- **Privacy:** users can export (`GET /export`) and erase (`DELETE /memories`) what Wensday remembers. Logs contain request ids and paths, never message text.
