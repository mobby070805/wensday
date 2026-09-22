from __future__ import annotations

import difflib
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import utcnow
from app.models import Task


async def create_task(session: AsyncSession, user_id: str, title: str, *, due_at: datetime | None = None,
                      priority: int = 2, notes: str = "", tags: list[str] | None = None, goal_id: str | None = None) -> Task:
    task = Task(user_id=user_id, title=title.strip(), due_at=due_at, priority=priority, notes=notes, tags=tags or [], goal_id=goal_id)
    session.add(task)
    await session.flush()
    return task


async def open_tasks(session: AsyncSession, user_id: str, limit: int = 100) -> list[Task]:
    q = select(Task).where(Task.user_id == user_id, Task.status == "open", Task.deleted_at.is_(None)).limit(limit)
    return list((await session.execute(q)).scalars())


async def find_open_by_title(session: AsyncSession, user_id: str, query: str) -> Task | None:
    """Best fuzzy match among open tasks (substring first, then difflib ratio)."""
    q = query.lower().strip()
    tasks = await open_tasks(session, user_id)
    if not tasks or not q:
        return None
    for t in tasks:
        if q in t.title.lower() or t.title.lower() in q:
            return t
    scored = [(difflib.SequenceMatcher(None, q, t.title.lower()).ratio(), t) for t in tasks]
    best = max(scored, key=lambda s: s[0])
    return best[1] if best[0] >= 0.6 else None


async def complete_task(session: AsyncSession, task: Task) -> Task:
    task.status, task.completed_at = "done", utcnow()
    await session.flush()
    return task


def rank_tasks(tasks: list[Task], now_utc: datetime | None = None, low_energy: bool = False) -> list[Task]:
    """Order by importance + urgency. In low-energy mode keep only what really matters today."""
    now = now_utc or utcnow()

    def score(t: Task) -> float:
        s = t.priority * 10.0
        if t.due_at:
            if t.due_at < now:
                s += 25          # already late: outranks a merely high-priority task
            elif t.due_at - now <= timedelta(hours=24):
                s += 12
            elif t.due_at - now <= timedelta(days=3):
                s += 5
        return s

    ranked = sorted(tasks, key=score, reverse=True)
    if low_energy:
        keep = [t for t in ranked if t.priority >= 3 or (t.due_at and t.due_at - now <= timedelta(hours=24))]
        return keep[:3]
    return ranked
