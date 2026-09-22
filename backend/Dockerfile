# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

FROM base AS deps
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM base AS runtime
# run as a non-root user
RUN useradd --create-home --uid 10001 wensday
COPY --from=deps /install /usr/local
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2)" || exit 1
# API:       uvicorn app.main:factory --factory --host 0.0.0.0 --port 8000
# Worker:    python -m app.worker           (override the command in the worker Deployment)
# Migrate:   python -m alembic upgrade head (run once before rolling out a new version; see deploy/k8s/25-migrate-job.yaml)
CMD ["uvicorn", "app.main:factory", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
