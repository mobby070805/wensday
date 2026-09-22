"""The Tool Registry — the single surface through which NLU intents, LLM tool-calls,
workflows and plugins all act on the user's data."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.events import EventHub
from app.i18n.detect import LangProfile
from app.llm.base import ToolSpec
from app.models import User

log = logging.getLogger("wensday.tools")


@dataclass
class Ctx:
    """Everything a tool needs for one user turn."""

    session: AsyncSession
    user: User
    now: datetime                      # user's local wall-clock time (naive)
    settings: Settings
    hub: EventHub
    llm: Any = None                    # LLMRouter
    memory: Any = None                 # MemoryEngine
    knowledge: Any = None              # Knowledge
    mailer: Any = None                 # MailSender
    plugins: Any = None                # PluginManager
    http: Any = None                   # shared httpx.AsyncClient
    registry: "ToolRegistry | None" = None
    profile: LangProfile | None = None
    style: str = "en"
    conversation_id: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def tz(self) -> str:
        return self.user.timezone or self.settings.default_timezone


@dataclass
class ToolResult:
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def as_json(self) -> dict:
        return {"ok": self.ok, **self.data} if self.ok else {"ok": False, "error": self.error}


Handler = Callable[[Ctx, dict], Awaitable[ToolResult]]


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Handler
    scopes: frozenset[str] = frozenset()
    requires_confirmation: bool = False
    llm_visible: bool = True
    plugin: str | None = None          # None for built-ins


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def unregister_plugin(self, plugin: str) -> None:
        self._tools = {n: t for n, t in self._tools.items() if t.plugin != plugin}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    async def specs(self, ctx: Ctx) -> list[ToolSpec]:
        """Tool specs the LLM may see for this user (built-ins + plugin tools the user enabled)."""
        out = []
        for t in self._tools.values():
            if not t.llm_visible:
                continue
            if t.plugin and not (ctx.plugins and await ctx.plugins.allowed(ctx, t)):
                continue
            out.append(ToolSpec(t.name, t.description, t.schema))
        return out

    async def call(self, name: str, ctx: Ctx, args: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, error=f"unknown tool: {name}")
        if tool.plugin and not (ctx.plugins and await ctx.plugins.allowed(ctx, tool)):
            return ToolResult(False, error=f"plugin '{tool.plugin}' is not enabled or lacks permission")
        missing = [k for k in tool.schema.get("required", []) if args.get(k) in (None, "")]
        if missing:
            return ToolResult(False, error=f"missing required argument(s): {', '.join(missing)}")
        try:
            return await tool.handler(ctx, args)
        except Exception as e:  # noqa: BLE001 - a broken tool must never crash the turn
            log.exception("tool %s failed", name)
            return ToolResult(False, error=f"{type(e).__name__}: {e}")
