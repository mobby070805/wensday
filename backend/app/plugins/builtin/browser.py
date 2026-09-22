"""Browser-assistance plugin. The server never drives a browser; it returns *client actions*
(open a URL, run a search) that the web app / mobile app / extension executes, and summarises
page text the client supplies."""
from __future__ import annotations

from urllib.parse import quote_plus, urlparse

from app.agent.tools import Ctx, Tool, ToolResult
from app.memory.knowledge import extractive_summary
from app.plugins.sdk import PluginSpec


def _safe_url(url: str) -> str | None:
    u = url if "://" in url else "https://" + url
    p = urlparse(u)
    return u if p.scheme in ("http", "https") and p.netloc and "." in p.netloc else None  # no javascript:, file:, data:


async def open_url(ctx: Ctx, a: dict) -> ToolResult:
    url = _safe_url(a["url"])
    if not url:
        return ToolResult(False, error="only http(s) URLs can be opened")
    return ToolResult(data={"action": "open_url", "url": url})


async def web_search(ctx: Ctx, a: dict) -> ToolResult:
    return ToolResult(data={"action": "open_url", "url": "https://duckduckgo.com/?q=" + quote_plus(a["query"])})


async def summarize_page(ctx: Ctx, a: dict) -> ToolResult:
    text = a["text"][:20000]
    summary = extractive_summary(text)
    if ctx.llm is not None and ctx.llm.has_remote:
        resp = await ctx.llm.complete("Summarise this web page in 3 short sentences, in the page's language.",
                                      [{"role": "user", "content": text[:12000]}], None, 300)
        summary = resp.text or summary
    return ToolResult(data={"title": a.get("title", ""), "summary": summary})


_S = {"type": "string"}
PLUGIN = PluginSpec(
    name="browser", version="1.0.0", description="Open pages, search the web and summarise page text via the client.",
    scopes=["net:fetch"],
    tools=[
        Tool("open_url", "Ask the client to open a URL in the browser.", {"type": "object", "properties": {"url": _S}, "required": ["url"]}, open_url, frozenset({"net:fetch"})),
        Tool("web_search", "Ask the client to open a web search.", {"type": "object", "properties": {"query": _S}, "required": ["query"]}, web_search, frozenset({"net:fetch"})),
        Tool("summarize_page", "Summarise page text supplied by the client.", {"type": "object", "properties": {"text": _S, "title": _S}, "required": ["text"]},
             summarize_page, frozenset({"net:fetch"})),
    ],
)
