"""Plugin SDK and manager.

A plugin is a Python module that exposes a module-level ``PLUGIN = PluginSpec(...)``.
Its tools join the same registry as built-ins, but every call is gated by:

  1. the user has *enabled* the plugin, and
  2. the user has *granted* every scope the tool declares.

Bundled plugins live in ``app/plugins/builtin``; extra ones can be dropped in a directory
named by ``WENSDAY_PLUGIN_DIR``.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.agent.tools import Tool, ToolRegistry
from app.models import PluginSetting

log = logging.getLogger("wensday.plugins")

KNOWN_SCOPES = {"net:fetch", "tasks:read", "tasks:write", "notes:read", "notes:write", "calendar:read", "calendar:write",
                "reminders:read", "reminders:write", "memory:read", "memory:write", "email:draft"}


@dataclass
class PluginSpec:
    name: str
    version: str
    description: str
    scopes: list[str]
    tools: list[Tool] = field(default_factory=list)


class PluginManager:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.plugins: dict[str, PluginSpec] = {}

    def register(self, spec: PluginSpec) -> None:
        bad = [s for s in spec.scopes if s not in KNOWN_SCOPES]
        if bad:
            raise ValueError(f"plugin {spec.name}: unknown scopes {bad}")
        for t in spec.tools:
            undeclared = set(t.scopes) - set(spec.scopes)
            if undeclared:
                raise ValueError(f"plugin {spec.name}: tool {t.name} uses undeclared scopes {sorted(undeclared)}")
            t.plugin = spec.name
            self.registry.register(t)
        self.plugins[spec.name] = spec

    def load_builtin(self) -> None:
        from . import builtin

        for m in pkgutil.iter_modules(builtin.__path__):
            mod = importlib.import_module(f"{builtin.__name__}.{m.name}")
            if hasattr(mod, "PLUGIN"):
                self.register(mod.PLUGIN)

    def load_dir(self, directory: str) -> None:
        for path in sorted(Path(directory).glob("*.py")):
            try:
                spec = importlib.util.spec_from_file_location(f"wensday_plugin_{path.stem}", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "PLUGIN"):
                    self.register(mod.PLUGIN)
            except Exception:  # noqa: BLE001 - one bad plugin must not stop the app
                log.exception("failed to load plugin %s", path)

    # ---- per-user state
    async def setting(self, session, user_id: str, name: str) -> PluginSetting | None:
        return (await session.execute(select(PluginSetting).where(PluginSetting.user_id == user_id, PluginSetting.plugin == name))).scalars().first()

    async def allowed(self, ctx, tool: Tool) -> bool:
        cache = ctx.extra.setdefault("_plugin_cache", {})
        if tool.plugin not in cache:
            cache[tool.plugin] = await self.setting(ctx.session, ctx.user.id, tool.plugin)
        st = cache[tool.plugin]
        if not st or not st.enabled or not set(tool.scopes) <= set(st.granted_scopes):
            return False
        ctx.extra.setdefault("plugin_config", {})[tool.plugin] = st.config or {}
        return True

    async def enable(self, session, user_id: str, name: str, granted: list[str] | None = None, config: dict | None = None) -> PluginSetting:
        spec = self.plugins[name]
        granted = spec.scopes if granted is None else [s for s in granted if s in spec.scopes]
        st = await self.setting(session, user_id, name)
        if st is None:
            st = PluginSetting(user_id=user_id, plugin=name)
            session.add(st)
        st.enabled, st.granted_scopes = True, granted
        if config is not None:
            st.config = config
        await session.flush()
        return st

    async def disable(self, session, user_id: str, name: str) -> None:
        st = await self.setting(session, user_id, name)
        if st:
            st.enabled = False
            await session.flush()
