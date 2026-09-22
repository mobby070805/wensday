# Plugin guide

A plugin is a Python module exposing `PLUGIN = PluginSpec(...)`. Its tools join the same registry that the rule engine, the LLM and workflows use — one surface to secure.

```python
# my_plugin.py  — drop into WENSDAY_PLUGIN_DIR (or app/plugins/builtin for bundled ones)
from app.agent.tools import Ctx, Tool, ToolResult
from app.plugins.sdk import PluginSpec

async def lookup_order(ctx: Ctx, args: dict) -> ToolResult:
    resp = await ctx.http.get("https://shop.example/api/orders", params={"id": args["order_id"]})
    if resp.status_code != 200:
        return ToolResult(False, error="order service unavailable")
    return ToolResult(data={"status": resp.json()["status"]})

PLUGIN = PluginSpec(
    name="orders", version="1.0.0", description="Look up shop orders.",
    scopes=["net:fetch"],
    tools=[Tool("lookup_order", "Get the status of an order.",
                {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
                lookup_order, frozenset({"net:fetch"}))],
)
```

## Permission model
1. **Declared:** a plugin lists its `scopes`; each tool may use only scopes the plugin declared (checked at load).
2. **Enabled per user:** off by default. `POST /plugins/{name}/enable` (optionally with a reduced `scopes` list and `config`).
3. **Enforced at call time:** every call re-checks *enabled* and *granted ⊇ tool scopes*. The LLM only *sees* tool specs the user has enabled. Revoking a scope or disabling takes effect on the next call.

Known scopes: `net:fetch`, `tasks:read|write`, `notes:read|write`, `calendar:read|write`, `reminders:read|write`, `memory:read|write`, `email:draft`.

## Tools receive
`ctx.session` (DB, already scoped to the user via `ctx.user`), `ctx.now` (user-local time), `ctx.style` (`en|tg|ta`), `ctx.http` (shared async client), `ctx.extra["plugin_config"][name]` (the user's config for this plugin), `ctx.llm`, `ctx.memory`.
Return `ToolResult(data={...})` or `ToolResult(False, error="…")`. Exceptions are caught and reported to the caller as an error, never crash the turn.

## Bundled examples
- **weather** — Open-Meteo (no key). Answers "weather enna" / "what's the weather" in the user's language style.
- **browser** — `open_url`, `web_search`, `summarize_page`. The server never drives a browser: it returns a *client action* (`{"action":"open_url","url":…}`) that the web/mobile app executes. Only `http(s)` URLs are allowed.

## Security notes — read before installing third-party plugins
**Plugins are trusted code running in the API process.** Scopes gate the *tool API* the plugin is called through; they do **not** sandbox arbitrary Python (a plugin can `import os`). Only load plugins you have reviewed. Process isolation / signed plugins are on the roadmap.
