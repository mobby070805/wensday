"""Personal productivity coaching: energy-aware daily plan, gentle nudges, weekly review."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import local_to_utc, utc_to_local
from app.models import Reminder, Task
from . import calendar as cal
from . import goals as goals_svc
from . import tasks as tasks_svc


async def plan_day(session: AsyncSession, user_id: str, local_now: datetime, tz: str, *, low_energy: bool = False) -> dict:
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc, end_utc = local_to_utc(day_start, tz), local_to_utc(day_start + timedelta(days=1), tz)
    events = await cal.between(session, user_id, start_utc, end_utc)
    open_ = await tasks_svc.open_tasks(session, user_id)
    ranked = tasks_svc.rank_tasks(open_, local_to_utc(local_now, tz), low_energy=low_energy)
    q = select(Reminder).where(Reminder.user_id == user_id, Reminder.status == "pending", Reminder.deleted_at.is_(None),
                               Reminder.due_at >= start_utc, Reminder.due_at < end_utc).order_by(Reminder.due_at)
    reminders = list((await session.execute(q)).scalars())
    items: list[dict] = []
    for e in events:
        items.append({"type": "event", "title": e.title, "at": utc_to_local(e.start_at, tz).isoformat()})
    for r in reminders:
        items.append({"type": "reminder", "title": r.title, "at": utc_to_local(r.due_at, tz).isoformat()})
    for t in ranked[: 3 if low_energy else 6]:
        items.append({"type": "task", "title": t.title, "priority": t.priority,
                      "at": utc_to_local(t.due_at, tz).isoformat() if t.due_at else None})
    items.sort(key=lambda i: (i["at"] is None, i["at"] or ""))
    return {"items": items, "focus": ranked[0].title if ranked else None, "low_energy": low_energy}


async def weekly_review(session: AsyncSession, user_id: str, now_utc: datetime) -> dict:
    since = now_utc - timedelta(days=7)
    done = (await session.execute(select(func.count()).select_from(Task).where(
        Task.user_id == user_id, Task.status == "done", Task.completed_at >= since))).scalar_one()
    still_open = len(await tasks_svc.open_tasks(session, user_id))
    goals = [{"title": g.title, "progress": await goals_svc.progress(session, g)} for g in await goals_svc.active_goals(session, user_id)]
    if done >= 5:
        headline = "Strong week — keep the rhythm."
    elif done:
        headline = "Steady progress. Pick one goal to push this week."
    else:
        headline = "Quiet week. Let's choose one small task to restart momentum."
    return {"completed": done, "open": still_open, "goals": goals, "headline": headline}
