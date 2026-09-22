"""Dashboard analytics: everything the web/mobile dashboards render, in one query set."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import utc_to_local
from app.models import Message, Reminder, Task
from . import goals as goals_svc


async def dashboard(session: AsyncSession, user_id: str, now_utc: datetime, tz: str, days: int = 14) -> dict:
    since = now_utc - timedelta(days=days)
    lookback = now_utc - timedelta(days=max(days, 90))  # wider than the chart so streaks aren't capped by it
    done_rows = (await session.execute(select(Task.completed_at).where(
        Task.user_id == user_id, Task.status == "done", Task.completed_at >= lookback))).scalars().all()
    by_day: Counter[str] = Counter(utc_to_local(d, tz).date().isoformat() for d in done_rows if d)
    today = utc_to_local(now_utc, tz).date()
    series = [{"date": (today - timedelta(days=i)).isoformat(), "completed": by_day.get((today - timedelta(days=i)).isoformat(), 0)}
              for i in range(days - 1, -1, -1)]

    streak = 0
    for i in range(90):
        if by_day.get((today - timedelta(days=i)).isoformat()):
            streak += 1
        elif i > 0:  # today may still be empty without breaking yesterday's streak
            break

    open_tasks = (await session.execute(select(Task).where(Task.user_id == user_id, Task.status == "open", Task.deleted_at.is_(None)))).scalars().all()
    overdue = sum(1 for t in open_tasks if t.due_at and t.due_at < now_utc)
    goals = [{"title": g.title, "progress": await goals_svc.progress(session, g)} for g in await goals_svc.active_goals(session, user_id)]
    fired = (await session.execute(select(func.count()).select_from(Reminder).where(
        Reminder.user_id == user_id, Reminder.fired_at >= since))).scalar_one()
    langs = (await session.execute(select(Message.lang, func.count()).where(
        Message.user_id == user_id, Message.role == "user", Message.created_at >= now_utc - timedelta(days=30)).group_by(Message.lang))).all()

    return {
        "tasks": {"open": len(open_tasks), "overdue": overdue, "completed_series": series,
                  "completed_total": sum(s["completed"] for s in series)},
        "streak_days": streak,
        "goals": goals,
        "reminders_fired": fired,
        "language_usage": {lang: n for lang, n in langs},
    }
