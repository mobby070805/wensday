"""Built-in tools. Times cross the tool boundary as the user's *local* ISO-8601 strings;
storage is UTC, so every handler converts at the edge."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.core.timeutil import local_to_utc, utc_to_local, utcnow
from app.models import EmailDraft, PendingAction
from app.services import calendar as cal
from app.services import coaching, email as email_svc, goals as goals_svc, notes as notes_svc, reminders as rem_svc, tasks as tasks_svc
from .tools import Ctx, Tool, ToolRegistry, ToolResult


def _parse_local(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=None)


def _utc(ctx: Ctx, s: str | None) -> datetime | None:
    d = _parse_local(s)
    return local_to_utc(d, ctx.tz) if d else None


def _loc(ctx: Ctx, d: datetime | None) -> str | None:
    return utc_to_local(d, ctx.tz).isoformat() if d else None


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


S, I = {"type": "string"}, {"type": "integer"}
WHEN = {"type": "string", "description": "Local date-time, ISO-8601 without timezone, e.g. 2026-09-22T09:00:00"}


# ------------------------------------------------------------------ reminders
async def create_reminder(ctx: Ctx, a: dict) -> ToolResult:
    due = _utc(ctx, a["when"])
    r = await rem_svc.create_reminder(ctx.session, ctx.user.id, a["title"], due, recurrence=a.get("recurrence", "none"), style=ctx.style)
    return ToolResult(data={"id": r.id, "title": r.title, "when": a["when"], "recurrence": r.recurrence})


async def list_reminders(ctx: Ctx, a: dict) -> ToolResult:
    rows = await rem_svc.upcoming(ctx.session, ctx.user.id, a.get("limit", 10))
    return ToolResult(data={"reminders": [{"id": r.id, "title": r.title, "when": _loc(ctx, r.due_at)} for r in rows]})


# ------------------------------------------------------------------ tasks
async def create_task(ctx: Ctx, a: dict) -> ToolResult:
    t = await tasks_svc.create_task(ctx.session, ctx.user.id, a["title"], due_at=_utc(ctx, a.get("due")), priority=a.get("priority", 2))
    return ToolResult(data={"id": t.id, "title": t.title})


async def list_tasks(ctx: Ctx, a: dict) -> ToolResult:
    ranked = tasks_svc.rank_tasks(await tasks_svc.open_tasks(ctx.session, ctx.user.id), local_to_utc(ctx.now, ctx.tz))
    return ToolResult(data={"tasks": [{"id": t.id, "title": t.title, "priority": t.priority, "due": _loc(ctx, t.due_at)}
                                      for t in ranked[: a.get("limit", 10)]]})


async def complete_task(ctx: Ctx, a: dict) -> ToolResult:
    t = await tasks_svc.find_open_by_title(ctx.session, ctx.user.id, a["query"])
    if not t:
        return ToolResult(False, error="no matching open task")
    await tasks_svc.complete_task(ctx.session, t)
    return ToolResult(data={"id": t.id, "title": t.title})


# ------------------------------------------------------------------ notes / goals
async def create_note(ctx: Ctx, a: dict) -> ToolResult:
    n = await notes_svc.create_note(ctx.session, ctx.user.id, a["body"], title=a.get("title", ""))
    return ToolResult(data={"id": n.id, "title": n.title})


async def search_notes(ctx: Ctx, a: dict) -> ToolResult:
    rows = await notes_svc.search(ctx.session, ctx.user.id, a.get("query", ""), a.get("limit", 5))
    if not rows and ctx.knowledge and a.get("query"):  # keyword miss -> semantic fallback
        hits = [h for h in await ctx.knowledge.search(ctx.session, ctx.user.id, a["query"], 5) if h.source == "note"]
        return ToolResult(data={"notes": [{"id": h.ref_id, "title": h.title, "body": h.text} for h in hits]})
    return ToolResult(data={"notes": [{"id": n.id, "title": n.title, "body": n.body} for n in rows]})


async def create_goal(ctx: Ctx, a: dict) -> ToolResult:
    g = await goals_svc.create_goal(ctx.session, ctx.user.id, a["title"], target_date=_utc(ctx, a.get("target_date")),
                                    milestones=a.get("milestones"))
    return ToolResult(data={"id": g.id, "title": g.title})


async def list_goals(ctx: Ctx, a: dict) -> ToolResult:
    rows = await goals_svc.active_goals(ctx.session, ctx.user.id)
    return ToolResult(data={"goals": [{"id": g.id, "title": g.title, "progress": await goals_svc.progress(ctx.session, g)} for g in rows]})


# ------------------------------------------------------------------ calendar
async def create_event(ctx: Ctx, a: dict) -> ToolResult:
    start = _utc(ctx, a["start"])
    end = _utc(ctx, a.get("end")) or start + timedelta(hours=1)
    ev, clashes = await cal.create_event(ctx.session, ctx.user.id, a["title"], start, end, location=a.get("location", ""))
    return ToolResult(data={"id": ev.id, "title": ev.title, "start": a["start"], "conflicts": [c.title for c in clashes]})


async def list_events(ctx: Ctx, a: dict) -> ToolResult:
    day = _parse_local(a.get("day")) or ctx.now
    d0 = day.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = await cal.between(ctx.session, ctx.user.id, local_to_utc(d0, ctx.tz), local_to_utc(d0 + timedelta(days=1), ctx.tz))
    return ToolResult(data={"events": [{"id": e.id, "title": e.title, "start": _loc(ctx, e.start_at), "end": _loc(ctx, e.end_at)} for e in rows]})


async def next_event(ctx: Ctx, a: dict) -> ToolResult:
    e = await cal.next_event(ctx.session, ctx.user.id, local_to_utc(ctx.now, ctx.tz))
    return ToolResult(data={"event": {"id": e.id, "title": e.title, "start": _loc(ctx, e.start_at)} if e else None})


async def reschedule_event(ctx: Ctx, a: dict) -> ToolResult:
    now_utc = local_to_utc(ctx.now, ctx.tz)
    ev = await cal.find_by_title(ctx.session, ctx.user.id, a.get("query", ""), now_utc) or \
        (await cal.next_event(ctx.session, ctx.user.id, now_utc) if not a.get("query") else None)
    if not ev:
        return ToolResult(False, error="no matching upcoming event")
    await cal.reschedule(ctx.session, ev, _utc(ctx, a["start"]))
    return ToolResult(data={"id": ev.id, "title": ev.title, "start": a["start"]})


# ------------------------------------------------------------------ coaching
async def plan_day(ctx: Ctx, a: dict) -> ToolResult:
    return ToolResult(data=await coaching.plan_day(ctx.session, ctx.user.id, ctx.now, ctx.tz, low_energy=bool(a.get("low_energy"))))


# ------------------------------------------------------------------ email (confirmation-gated send)
async def draft_email(ctx: Ctx, a: dict) -> ToolResult:
    sender = (ctx.user.name or "").split(" ")[0] or "Me"
    subject, body = await email_svc.compose(ctx.llm, a.get("recipient", ""), a["body"], sender)
    d = await email_svc.create_draft(ctx.session, ctx.user, a.get("recipient", ""), subject, body, ctx.style)
    ctx.session.add(PendingAction(user_id=ctx.user.id, conversation_id=ctx.conversation_id, kind="email_send",
                                  payload={"draft_id": d.id}, expires_at=utcnow() + timedelta(hours=1)))
    await ctx.session.flush()
    return ToolResult(data={"draft_id": d.id, "recipient": d.recipient, "subject": d.subject, "body": d.body,
                            "note": "Draft saved, not sent. Ask the user whether to review it or send it directly."})


async def send_email(ctx: Ctx, a: dict) -> ToolResult:
    d = await ctx.session.get(EmailDraft, a["draft_id"])
    if not d or d.user_id != ctx.user.id or d.status not in ("draft", "queued"):
        return ToolResult(False, error="draft not found")
    status = await email_svc.send_draft(ctx.session, ctx.mailer, ctx.user, d)
    return ToolResult(data={"status": status, "recipient": d.recipient})


# ------------------------------------------------------------------ memory / knowledge
async def remember(ctx: Ctx, a: dict) -> ToolResult:
    m = await ctx.memory.remember(ctx.session, ctx.user.id, a["text"], kind="fact", importance=0.8)
    return ToolResult(data={"id": m.id if m else None})


async def recall(ctx: Ctx, a: dict) -> ToolResult:
    rows = await ctx.memory.recall(ctx.session, ctx.user.id, a["query"], k=5)
    return ToolResult(data={"memories": [r.memory.text for r in rows]})


async def ask_knowledge(ctx: Ctx, a: dict) -> ToolResult:
    return ToolResult(data=await ctx.knowledge.answer(ctx.session, ctx.user.id, a["question"]))


async def get_time(ctx: Ctx, a: dict) -> ToolResult:
    return ToolResult(data={"local_time": ctx.now.isoformat(), "timezone": ctx.tz})


def register_builtins(reg: ToolRegistry) -> None:
    def add(name, description, props, required, handler, scopes=(), **kw):
        reg.register(Tool(name, description, _obj(props, required), handler, frozenset(scopes), **kw))

    add("create_reminder", "Set a reminder for the user.", {"title": S, "when": WHEN, "recurrence": {"type": "string", "enum": ["none", "daily", "weekdays", "weekly", "monthly"]}},
        ["title", "when"], create_reminder, ["reminders:write"])
    add("list_reminders", "List upcoming reminders.", {"limit": I}, [], list_reminders, ["reminders:read"])
    add("create_task", "Add a task to the user's to-do list.", {"title": S, "due": WHEN, "priority": {"type": "integer", "minimum": 1, "maximum": 4}},
        ["title"], create_task, ["tasks:write"])
    add("list_tasks", "List open tasks, most important first.", {"limit": I}, [], list_tasks, ["tasks:read"])
    add("complete_task", "Mark an open task done (fuzzy title match).", {"query": S}, ["query"], complete_task, ["tasks:write"])
    add("create_note", "Save a note.", {"body": S, "title": S}, ["body"], create_note, ["notes:write"])
    add("search_notes", "Search the user's notes.", {"query": S, "limit": I}, [], search_notes, ["notes:read"])
    add("create_goal", "Create a goal to track.", {"title": S, "target_date": WHEN, "milestones": {"type": "array", "items": S}}, ["title"], create_goal, ["goals:write"])
    add("list_goals", "List active goals with progress.", {}, [], list_goals, ["goals:read"])
    add("create_event", "Schedule a calendar event.", {"title": S, "start": WHEN, "end": WHEN, "location": S}, ["title", "start"], create_event, ["calendar:write"])
    add("list_events", "List calendar events for a day (default today).", {"day": WHEN}, [], list_events, ["calendar:read"])
    add("next_event", "Get the next upcoming calendar event.", {}, [], next_event, ["calendar:read"])
    add("reschedule_event", "Move an upcoming event to a new start time.", {"query": S, "start": WHEN}, ["start"], reschedule_event, ["calendar:write"])
    add("plan_day", "Build today's plan from events, reminders and prioritised tasks.", {"low_energy": {"type": "boolean"}}, [], plan_day, ["tasks:read", "calendar:read"])
    add("draft_email", "Draft an email. Never sends; the user must confirm.", {"recipient": S, "body": S}, ["body"], draft_email, ["email:draft"])
    add("send_email", "Send a previously drafted email (only after the user confirmed).", {"draft_id": S}, ["draft_id"], send_email,
        ["email:send"], requires_confirmation=True, llm_visible=False)
    add("remember", "Store a long-term fact about the user.", {"text": S}, ["text"], remember, ["memory:write"])
    add("recall", "Search long-term memory.", {"query": S}, ["query"], recall, ["memory:read"])
    add("ask_knowledge", "Answer a question from the user's documents, notes and memories.", {"question": S}, ["question"], ask_knowledge, ["memory:read"])
    add("get_time", "Get the user's current local time.", {}, [], get_time)
