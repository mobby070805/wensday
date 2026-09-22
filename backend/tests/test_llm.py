"""LLM layer: provider wire formats, failover router, and the agent's tool-calling tier."""
import json

import httpx
import pytest

from app.config import Settings
from app.llm.base import LLMError, LLMResponse, ToolCall, ToolSpec
from app.llm.providers import AnthropicProvider, OfflineProvider, OpenAICompatProvider
from app.llm.router import LLMRouter, build_router
from .conftest import Person, running

TOOLS = [ToolSpec("create_task", "Add a task", {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]})]
HISTORY = [
    {"role": "user", "content": "add book flights"},
    {"role": "assistant", "content": "On it.", "tool_calls": [{"id": "t1", "name": "create_task", "args": {"title": "Book flights"}},
                                                             {"id": "t2", "name": "create_task", "args": {"title": "Book hotel"}}]},
    {"role": "tool", "tool_call_id": "t1", "content": '{"ok": true}'},
    {"role": "tool", "tool_call_id": "t2", "content": '{"ok": true}'},
]


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ------------------------------------------------------------------ Anthropic wire format
async def test_anthropic_request_and_response_mapping():
    seen = {}

    def handler(req: httpx.Request):
        seen["h"], seen["body"], seen["url"] = req.headers, json.loads(req.content), str(req.url)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Sure. "}, {"type": "tool_use", "id": "tu1", "name": "create_task", "input": {"title": "X"}}]})

    p = AnthropicProvider(_client(handler), "sk-test", "claude-sonnet-5")
    r = await p.complete("You are Wensday", HISTORY, TOOLS, 300)
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["h"]["x-api-key"] == "sk-test" and seen["h"]["anthropic-version"] == "2023-06-01"
    b = seen["body"]
    assert b["model"] == "claude-sonnet-5" and b["system"] == "You are Wensday" and b["max_tokens"] == 300
    assert b["tools"] == [{"name": "create_task", "description": "Add a task", "input_schema": TOOLS[0].schema}]
    assert b["messages"][1]["content"][1] == {"type": "tool_use", "id": "t1", "name": "create_task", "input": {"title": "Book flights"}}
    results = b["messages"][2]["content"]                                      # parallel results share ONE user turn
    assert [x["tool_use_id"] for x in results] == ["t1", "t2"] and len(b["messages"]) == 3
    assert r.text == "Sure." and r.tool_calls == [ToolCall("tu1", "create_task", {"title": "X"})] and r.provider == "anthropic"


async def test_anthropic_errors_become_llm_errors():
    for handler in (lambda r: httpx.Response(529), lambda r: httpx.Response(200, content=b"not json")):
        with pytest.raises(LLMError):
            await AnthropicProvider(_client(handler), "k", "m").complete("s", [{"role": "user", "content": "hi"}])


# ------------------------------------------------------------------ OpenAI-compatible wire format
async def test_openai_compat_request_and_response_mapping():
    seen = {}

    def handler(req: httpx.Request):
        seen["body"], seen["auth"] = json.loads(req.content), req.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "c1", "function": {"name": "create_task", "arguments": '{"title": "Y"}'}}]}}]})

    p = OpenAICompatProvider(_client(handler), "sk", "http://llm/v1", "gpt-x")
    r = await p.complete("sys", HISTORY, TOOLS)
    b = seen["body"]
    assert seen["auth"] == "Bearer sk" and b["messages"][0] == {"role": "system", "content": "sys"}
    assert b["tools"][0]["function"]["parameters"] == TOOLS[0].schema
    assistant = b["messages"][2]
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"title": "Book flights"}'
    assert [m["role"] for m in b["messages"][3:]] == ["tool", "tool"]
    assert r.tool_calls == [ToolCall("c1", "create_task", {"title": "Y"})] and r.text == ""


async def test_openai_compat_tolerates_malformed_tool_arguments_and_needs_a_key_unless_local():
    bad = lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": "{oops"}}]}}]})
    r = await OpenAICompatProvider(_client(bad), "k", "http://x", "m").complete("s", [{"role": "user", "content": "hi"}])
    assert r.tool_calls[0].args == {}
    assert not OpenAICompatProvider(_client(bad), None, "https://api.openai.com/v1", "m").configured
    assert OpenAICompatProvider(_client(bad), None, "http://localhost:11434/v1", "llama", keyless=True).configured


# ------------------------------------------------------------------ router
class Scripted:
    """A provider whose behaviour is a list of responses/exceptions, consumed in order."""

    remote, configured = True, True

    def __init__(self, name, script):
        self.name, self.script, self.calls, self.last_system, self.last_tools = name, list(script), 0, None, None

    async def complete(self, system, messages, tools=None, max_tokens=1024):
        self.calls += 1
        self.last_system, self.last_tools = system, tools
        step = self.script.pop(0) if self.script else self.script_default()
        if isinstance(step, Exception):
            raise step
        return step

    def script_default(self):
        return LLMResponse(text="ok", provider=self.name)


async def test_router_fails_over_and_opens_a_circuit_breaker():
    a = Scripted("a", [LLMError("down")])
    b = Scripted("b", [])
    router = LLMRouter([a, b, OfflineProvider()], cooldown_s=60)
    assert (await router.complete("s", [])).provider == "b"
    assert (await router.complete("s", [])).provider == "b"
    assert a.calls == 1                                       # not retried while the breaker is open
    assert router.has_remote


async def test_router_falls_back_to_offline_when_everything_fails_or_is_unconfigured():
    a = Scripted("a", [LLMError("x")])
    assert (await LLMRouter([a, OfflineProvider()]).complete("s", [])).provider == "offline"
    unconfigured = AnthropicProvider(_client(lambda r: httpx.Response(500)), None, "m")
    assert not LLMRouter([unconfigured, OfflineProvider()]).has_remote
    assert (await LLMRouter([unconfigured, OfflineProvider()]).complete("s", [])).provider == "offline"


async def test_router_json_task_extracts_json_from_fenced_or_chatty_replies():
    r = Scripted("a", [LLMResponse(text='Here you go:\n```json\n{"subject": "Quote", "body": "Ready"}\n```', provider="a"),
                       LLMResponse(text="no json here", provider="a")])
    router = LLMRouter([r])
    assert await router.json_task("sys", "u") == {"subject": "Quote", "body": "Ready"}
    assert await router.json_task("sys", "u") is None


def test_build_router_honours_configured_chain_and_always_ends_offline():
    s = Settings(jwt_secret="x" * 40, llm_chain=["anthropic"], anthropic_api_key="k")
    router = build_router(s, _client(lambda r: httpx.Response(200)))
    assert [p.name for p in router.providers] == ["anthropic", "offline"] and router.has_remote


# ------------------------------------------------------------------ agent tier 2 (LLM with tools)
TANGLISH_UNKNOWN = "epdi quantum computing work aagum nu vilakku"


def test_llm_tier_runs_tools_then_answers_and_carries_language_and_memory_context():
    prov = Scripted("fake", [
        LLMResponse(text="", tool_calls=[ToolCall("1", "create_task", {"title": "Book flights"})], provider="fake"),
        LLMResponse(text="Done Madesh, task add panniten.", provider="fake"),
    ])
    with running(llm=LLMRouter([prov])) as c:
        p = Person(c, "a@x.com", "Madesh")
        p.say("remember that I prefer window seats")
        out = p.say(TANGLISH_UNKNOWN)
        assert out["tier"] == "llm" and out["intent"] == "llm" and out["reply"] == "Done Madesh, task add panniten."
        assert [t["title"] for t in p.get("/tasks").json()] == ["Book flights"]           # the tool call really executed
        assert "Tanglish" in prov.last_system and "Madesh" in prov.last_system
        assert "spoken aloud" in prov.last_system and "never claim an action is done" in prov.last_system.lower()
        names = {t.name for t in prov.last_tools}
        assert "create_task" in names and "draft_email" in names
        assert "send_email" not in names                        # sending is confirmation-gated, never model-callable
        assert not names & {"get_weather", "open_url"}          # plugin tools stay hidden until the user enables them


def test_llm_sees_a_plugin_tool_only_after_the_user_enables_it():
    prov = Scripted("fake", [])
    with running(llm=LLMRouter([prov])) as c:
        p = Person(c, "a@x.com", "Madesh")
        p.say(TANGLISH_UNKNOWN)
        assert "get_weather" not in {t.name for t in prov.last_tools}
        p.post("/plugins/weather/enable", {})
        p.say(TANGLISH_UNKNOWN)
        assert "get_weather" in {t.name for t in prov.last_tools}


def test_tool_errors_are_reported_to_the_model_not_raised():
    seen = []

    class Spy(Scripted):
        async def complete(self, system, messages, tools=None, max_tokens=1024):
            seen[:] = list(messages)          # keep the most recent full history the model was shown
            return await super().complete(system, messages, tools, max_tokens)

    prov = Spy("fake", [LLMResponse(tool_calls=[ToolCall("1", "complete_task", {"query": "ghost"}), ToolCall("2", "nope", {})], provider="fake"),
                        LLMResponse(text="I couldn't find that.", provider="fake")])
    with running(llm=LLMRouter([prov])) as c:
        out = Person(c, "a@x.com", "Madesh").say(TANGLISH_UNKNOWN)
    assert out["reply"] == "I couldn't find that."
    results = [json.loads(m["content"]) for m in seen if m.get("role") == "tool"]
    assert results == [{"ok": False, "error": "no matching open task"}, {"ok": False, "error": "unknown tool: nope"}]


def test_runaway_tool_loop_is_capped_and_degrades_to_the_offline_reply():
    looping = Scripted("fake", [LLMResponse(tool_calls=[ToolCall(str(i), "get_time", {})], provider="fake") for i in range(10)])
    with running(llm=LLMRouter([looping])) as c:
        out = Person(c, "a@x.com", "Madesh").say(TANGLISH_UNKNOWN)
    assert looping.calls == 4 and out["tier"] == "offline"


def test_llm_outage_falls_back_to_the_offline_engine():
    dead = Scripted("fake", [LLMError("down")] * 3)
    with running(llm=LLMRouter([dead, OfflineProvider()])) as c:
        p = Person(c, "a@x.com", "Madesh")
        assert p.say(TANGLISH_UNKNOWN)["tier"] == "offline"
        assert p.say("Wensday, nalaiku 9 mani meeting remind pannu.")["tier"] == "rules"       # commands never needed the LLM


def test_rule_commands_do_not_spend_llm_calls():
    prov = Scripted("fake", [])
    with running(llm=LLMRouter([prov])) as c:
        p = Person(c, "a@x.com", "Madesh")
        p.say("Wensday, nalaiku 9 mani meeting remind pannu.")
        p.say("hello")
        p.say("add task buy milk")
    assert prov.calls == 0


def test_email_draft_uses_the_llm_when_available():
    prov = Scripted("fake", [LLMResponse(text='{"subject": "Quotation ready", "body": "Hi team,\\n\\nOur quotation is ready for review.\\n\\nRegards"}', provider="fake")])
    with running(llm=LLMRouter([prov])) as c:
        p = Person(c, "a@x.com", "Madesh")
        out = p.say("send a mail to client and mention quotation ready")
        assert out["data"]["subject"] == "Quotation ready" and "ready for review" in out["data"]["body"]
