"""Custom workflows: a trigger plus an ordered list of tool calls, declared as JSON.

    {"name": "Good morning",
     "trigger": {"type": "phrase", "phrases": ["good morning routine", "kaalai routine"]},
     "steps": [{"tool": "plan_day", "args": {}},
               {"tool": "create_task", "args": {"title": "Review inbox", "due": "{{today_5pm}}"}}]}

Triggers: `phrase` (spoken/typed), `schedule` ({"at": "08:00", "days": "daily|weekdays"}).
Arg strings may use {{now}}, {{today}}, {{today_5pm}}, {{tomorrow_9am}}, {{user.name}}, {{prev.<key>}}.
Tools that require confirmation (e.g. send_email) are refused inside workflows.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import local_now, utcnow
from app.i18n.normalize import skeleton, words
from app.models import User, Workflow, WorkflowRun

log = logging.getLogger("wensday.workflows")
_VAR = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def _norm(text: str) -> str:
    return " ".join(skeleton(w) for w in words(text))


async def match_phrase(session: AsyncSession, user_id: str, text: str) -> Workflow | None:
    spoken = _norm(text)
    rows = (await session.execute(select(Workflow).where(Workflow.user_id == user_id, Workflow.enabled.is_(True), Workflow.deleted_at.is_(None)))).scalars()
    for wf in rows:
        if wf.trigger.get("type") == "phrase":
            for phrase in wf.trigger.get("phrases", []):
                p = _norm(phrase)
                if p and p in spoken:
                    return wf
    return None


def _vars(ctx, prev: dict) -> dict[str, str]:
    now = ctx.now
    return {
        "now": now.isoformat(timespec="seconds"),
        "today": now.date().isoformat(),
        "today_5pm": now.replace(hour=17, minute=0, second=0, microsecond=0).isoformat(),
        "tomorrow_9am": (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0).isoformat(),
        "user.name": ctx.user.name or "",
        **{f"prev.{k}": str(v) for k, v in prev.items()},
    }


def _render(value, variables: dict[str, str]):
    if isinstance(value, str):
        return _VAR.sub(lambda m: variables.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _render(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, variables) for v in value]
    return value


async def run_workflow(ctx, registry, wf: Workflow) -> WorkflowRun:
    prev: dict = {}
    log_entries: list[dict] = []
    status = "ok"
    for step in wf.steps:
        name = step.get("tool", "")
        tool = registry.get(name)
        if tool is not None and tool.requires_confirmation:
            log_entries.append({"tool": name, "ok": False, "error": "requires user confirmation; not allowed in workflows"})
            status = "failed"
            break
        res = await registry.call(name, ctx, _render(step.get("args", {}), _vars(ctx, prev)))
        log_entries.append({"tool": name, "ok": res.ok, **({"data": res.data} if res.ok else {"error": res.error})})
        if not res.ok:
            status = "failed"
            break
        prev = {k: v for k, v in res.data.items() if isinstance(v, (str, int, float))}
    run = WorkflowRun(user_id=ctx.user.id, workflow_id=wf.id, status=status, log=log_entries)
    ctx.session.add(run)
    await ctx.session.flush()
    return run


async def scheduled_tick(app) -> int:
    """Run schedule-triggered workflows whose local HH:MM matches now (at most once per day each)."""
    ran = 0
    async with app.state.db.session() as session:
        rows = (await session.execute(select(Workflow).where(Workflow.enabled.is_(True), Workflow.deleted_at.is_(None)))).scalars().all()
        for wf in rows:
            trig = wf.trigger or {}
            if trig.get("type") != "schedule":
                continue
            user = await session.get(User, wf.user_id)
            now = local_now(user.timezone)
            if now.strftime("%H:%M") != trig.get("at"):
                continue
            if trig.get("days") == "weekdays" and now.weekday() >= 5:
                continue
            last = (await session.execute(select(WorkflowRun.created_at).where(WorkflowRun.workflow_id == wf.id)
                                          .order_by(WorkflowRun.created_at.desc()).limit(1))).scalars().first()
            if last and utcnow() - last < timedelta(hours=23):
                continue
            ctx = app.state.make_ctx(session, user)
            await run_workflow(ctx, app.state.registry, wf)
            ran += 1
        await session.commit()
    return ran
