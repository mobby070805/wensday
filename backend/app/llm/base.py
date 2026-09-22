"""Provider-neutral LLM types. Conversation history uses one simple dict format:

    {"role": "user"|"assistant", "content": str}
    {"role": "assistant", "content": str, "tool_calls": [{"id","name","args"}]}
    {"role": "tool", "tool_call_id": str, "content": str}

Each provider translates that to its own wire format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]  # JSON Schema for the arguments object


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider: str = "offline"


class LLMError(Exception):
    """Transient/provider failure: the router should try the next provider."""


class LLMProvider(Protocol):
    name: str
    remote: bool

    @property
    def configured(self) -> bool: ...

    async def complete(self, system: str, messages: list[dict], tools: list[ToolSpec] | None = None,
                       max_tokens: int = 1024) -> LLMResponse: ...
