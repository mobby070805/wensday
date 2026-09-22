"""Concrete LLM providers. All talk plain HTTPS through an injected httpx client, so tests
can drive them with `httpx.MockTransport` and no network."""
from __future__ import annotations

import json

import httpx

from .base import LLMError, LLMResponse, ToolCall, ToolSpec


class AnthropicProvider:
    name, remote = "anthropic", True

    def __init__(self, client: httpx.AsyncClient, api_key: str | None, model: str, base_url: str = "https://api.anthropic.com"):
        self._c, self._key, self._model, self._base = client, api_key, model, base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self._key)

    @staticmethod
    def _wire(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)  # parallel tool results share one user turn
                else:
                    out.append({"role": "user", "content": [block]})
            elif m.get("tool_calls"):
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                blocks += [{"type": "tool_use", "id": t["id"], "name": t["name"], "input": t["args"]} for t in m["tool_calls"]]
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    async def complete(self, system, messages, tools=None, max_tokens=1024) -> LLMResponse:
        body: dict = {"model": self._model, "max_tokens": max_tokens, "system": system, "messages": self._wire(messages)}
        if tools:
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in tools]
        try:
            r = await self._c.post(f"{self._base}/v1/messages", json=body, timeout=30,
                                   headers={"x-api-key": self._key or "", "anthropic-version": "2023-06-01"})
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise LLMError(f"anthropic: {e}") from e
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        calls = [ToolCall(b["id"], b["name"], b.get("input") or {}) for b in data.get("content", []) if b.get("type") == "tool_use"]
        return LLMResponse(text=text.strip(), tool_calls=calls, provider=self.name)


class OpenAICompatProvider:
    """OpenAI, Azure-OpenAI-compatible gateways, Ollama, vLLM, LM Studio…"""

    name, remote = "openai_compat", True

    def __init__(self, client: httpx.AsyncClient, api_key: str | None, base_url: str, model: str, *, keyless: bool = False):
        self._c, self._key, self._base, self._model, self._keyless = client, api_key, base_url.rstrip("/"), model, keyless

    @property
    def configured(self) -> bool:
        # local servers (Ollama) need no key, but must be pointed away from the public default
        return bool(self._key) or self._keyless

    @staticmethod
    def _wire(system: str, messages: list[dict]) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            elif m.get("tool_calls"):
                out.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": [
                    {"id": t["id"], "type": "function", "function": {"name": t["name"], "arguments": json.dumps(t["args"])}}
                    for t in m["tool_calls"]]})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    async def complete(self, system, messages, tools=None, max_tokens=1024) -> LLMResponse:
        body: dict = {"model": self._model, "max_tokens": max_tokens, "messages": self._wire(system, messages)}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}} for t in tools]
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        try:
            r = await self._c.post(f"{self._base}/chat/completions", json=body, headers=headers, timeout=30)
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
            raise LLMError(f"openai_compat: {e}") from e
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tc["id"], tc["function"]["name"], args))
        return LLMResponse(text=(msg.get("content") or "").strip(), tool_calls=calls, provider=self.name)


class OfflineProvider:
    """Last-resort provider: produces nothing, which tells the agent to answer from rules/persona."""

    name, remote = "offline", False
    configured = True

    async def complete(self, system, messages, tools=None, max_tokens=1024) -> LLMResponse:
        return LLMResponse(text="", provider=self.name)
