from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from .agent.builtin_tools import register_builtins
from .agent.orchestrator import Agent
from .agent.tools import Ctx, ToolRegistry
from .config import Settings, get_settings
from .core.cache import make_cache
from .core.events import EventHub
from .core.timeutil import local_now
from .db import Database
from .integrations.google import GmailSender, GoogleOAuth
from .llm.router import LLMRouter, build_router
from .memory.embeddings import HashingEmbedder, OpenAICompatEmbedder
from .memory.engine import MemoryEngine
from .memory.knowledge import Knowledge
from .memory.vectorstore import InMemoryVectorStore, QdrantStore
from .plugins.sdk import PluginManager
from .routers import assistant, auth, platform, resources, voice
from .services import reminders as reminders_svc
from .services import workflows as workflows_svc
from .services.email import NullSender
from .voice.providers import build_stt, build_tts

log = logging.getLogger("wensday")
API = "/api/v1"


def create_app(settings: Settings | None = None, *, llm: LLMRouter | None = None, http: httpx.AsyncClient | None = None,
               stt=None, tts=None, mailer=None) -> FastAPI:
    """App factory. Every collaborator can be injected, which is how the tests run with no network."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        st = app.state
        st.settings = settings
        st.db = Database(settings.database_url)
        if settings.auto_create_tables:
            await st.db.create_all()
        st.http = http or httpx.AsyncClient(timeout=30)
        st.cache = make_cache(settings.redis_url)
        st.hub = EventHub(settings.redis_url)
        await st.hub.start()

        st.llm = llm or build_router(settings, st.http)
        embedder = (OpenAICompatEmbedder(st.http, settings.openai_api_key, settings.openai_base_url, settings.embedding_model, settings.embedding_dim)
                    if settings.embedding_provider == "openai_compat" else HashingEmbedder(settings.embedding_dim))
        store = QdrantStore(st.http, settings.qdrant_url, settings.qdrant_api_key, embedder.dim) if settings.qdrant_url else InMemoryVectorStore()
        st.memory = MemoryEngine(embedder, store)
        st.knowledge = Knowledge(embedder, st.llm)

        st.registry = ToolRegistry()
        register_builtins(st.registry)
        st.plugins = PluginManager(st.registry)
        st.plugins.load_builtin()
        if settings.plugin_dir:
            st.plugins.load_dir(settings.plugin_dir)

        st.google = GoogleOAuth(settings, st.http)
        st.mailer = mailer or (GmailSender(st.http, settings, st.google) if st.google.configured else NullSender())
        st.stt = stt or build_stt(settings, st.http)
        st.tts = tts or build_tts(settings, st.http)
        st.agent = Agent(st.registry)

        def make_ctx(session, user) -> Ctx:
            return Ctx(session=session, user=user, now=local_now(user.timezone or settings.default_timezone), settings=settings, hub=st.hub,
                       llm=st.llm, memory=st.memory, knowledge=st.knowledge, mailer=st.mailer, plugins=st.plugins, http=st.http, registry=st.registry)

        st.make_ctx = make_ctx

        tasks: list[asyncio.Task] = []
        if settings.reminder_worker:
            tasks.append(asyncio.create_task(reminders_svc.worker(app)))
            tasks.append(asyncio.create_task(_workflow_loop(app)))
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await st.hub.stop()
            if http is None:
                await st.http.aclose()
            await st.db.dispose()

    app = FastAPI(title="Wensday API", version="0.1.0", lifespan=lifespan,
                  description="Voice-first personal assistant for Tamil, English and Tanglish.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    metrics: dict = {"count": defaultdict(int), "sum": 0.0, "n": 0}

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            log.exception("unhandled error rid=%s path=%s", rid, request.url.path)
            response = JSONResponse({"detail": "internal server error", "request_id": rid}, status_code=500)
        dt = time.perf_counter() - t0
        metrics["count"][(request.method, response.status_code)] += 1
        metrics["sum"] += dt
        metrics["n"] += 1
        response.headers["x-request-id"] = rid
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "no-referrer"
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            # only ever sent over TLS: HSTS on a plain-HTTP response is meaningless and, if this
            # API were ever briefly served over HTTP by mistake, would be actively harmful
            response.headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
        # method + path + status only — never the query string (e.g. /memories/search?q=...) or
        # body, both of which can carry the user's own message text.
        log.info("%s %s -> %d %.1fms rid=%s", request.method, request.url.path, response.status_code, dt * 1000, rid)
        return response

    @app.get("/healthz", tags=["ops"])
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    async def readyz(request: Request):
        try:
            async with request.app.state.db.session() as s:
                await s.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ready", "llm_remote": request.app.state.llm.has_remote}

    @app.get("/metrics", tags=["ops"], response_class=PlainTextResponse)
    async def prom():
        lines = ["# TYPE wensday_http_requests_total counter"]
        lines += [f'wensday_http_requests_total{{method="{m}",status="{s}"}} {n}' for (m, s), n in sorted(metrics["count"].items())]
        lines += ["# TYPE wensday_http_request_seconds summary", f"wensday_http_request_seconds_sum {metrics['sum']:.6f}",
                  f"wensday_http_request_seconds_count {metrics['n']}"]
        return "\n".join(lines) + "\n"

    for r in (auth.router, resources.tasks, resources.reminders, resources.events, resources.notes, resources.goals,
              assistant.router, platform.router, voice.router):
        app.include_router(r, prefix=API)
    return app


async def _workflow_loop(app: FastAPI) -> None:
    while True:
        try:
            await workflows_svc.scheduled_tick(app)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("workflow scheduler tick failed")
        await asyncio.sleep(30)


def factory() -> FastAPI:
    """`uvicorn app.main:factory --factory`"""
    return create_app()
