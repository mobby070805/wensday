"""Failover router over LLM providers with a small circuit breaker."""
from __future__ import annotations

import json
import logging
import re
import time

import httpx

from app.config import Settings
from .base import LLMError, LLMProvider, LLMResponse, ToolSpec
from .providers import AnthropicProvider, OfflineProvider, OpenAICompatProvider

log = logging.getLogger("wensday.llm")


class LLMRouter:
    def __init__(self, providers: list[LLMProvider], cooldown_s: float = 30.0):
        self.providers = providers
        self._cooldown = cooldown_s
        self._down_until: dict[str, float] = {}

    @property
    def has_remote(self) -> bool:
        return any(p.remote and p.configured for p in self.providers)

    async def complete(self, system: str, messages: list[dict], tools: list[ToolSpec] | None = None,
                       max_tokens: int = 1024) -> LLMResponse:
        for p in self.providers:
            if not p.configured or self._down_until.get(p.name, 0) > time.monotonic():
                continue
            try:
                return await p.complete(system, messages, tools, max_tokens)
            except LLMError as e:
                log.warning("provider %s failed (%s); failing over", p.name, e)
                self._down_until[p.name] = time.monotonic() + self._cooldown
        return LLMResponse(provider="offline")

    async def json_task(self, system: str, user: str, max_tokens: int = 1024) -> dict | None:
        """Ask for a JSON object; tolerate code fences / prose around it."""
        resp = await self.complete(system, [{"role": "user", "content": user}], None, max_tokens)
        if not resp.text:
            return None
        m = re.search(r"\{.*\}", resp.text, re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            return None


def build_router(settings: Settings, client: httpx.AsyncClient) -> LLMRouter:
    keyless_local = "localhost" in settings.openai_base_url or "127.0.0.1" in settings.openai_base_url
    registry = {
        "anthropic": lambda: AnthropicProvider(client, settings.anthropic_api_key, settings.anthropic_model),
        "openai_compat": lambda: OpenAICompatProvider(client, settings.openai_api_key, settings.openai_base_url,
                                                      settings.openai_model, keyless=keyless_local),
        "offline": OfflineProvider,
    }
    chain = [registry[n]() for n in settings.llm_chain if n in registry]
    if not any(isinstance(p, OfflineProvider) for p in chain):
        chain.append(OfflineProvider())
    return LLMRouter(chain)
