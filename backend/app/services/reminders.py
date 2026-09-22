from __future__ import annotations

import asyncio
import calendar
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import EventHub
from app.core.timeutil import utcnow
from app.i18n.persona import say
from app.models import Reminder, User

log = logging.getLogger("wensday.reminders")


async def create_reminder(session: AsyncSession, user_id: str, title: str, due_at: datetime, *,
                          recurrence: str = "none", style: str = "en") -> Reminder:
    r = Reminder(user_id=user_id, title=title.strip() or "Reminder", due_at=due_at, recurrence=recurrence, style=style)
    session.add(r)
    await session.flush()
    return r


async def upcoming(session: AsyncSession, user_id: str, limit: int = 20) -> list[Reminder]:
    q = (select(Reminder).where(Reminder.user_id == user_id, Reminder.status == "pending", Reminder.deleted_at.is_(None))
         .order_by(Reminder.due_at).limit(limit))
    return list((await session.execute(q)).scalars())


def _add_months(anchor: datetime, months: int) -> datetime:
    """anchor + N months, keeping the anchor's day-of-month where the month has it (Jan 31 -> Feb 28 -> Mar 31)."""
    total = anchor.month - 1 + months
    year, month = anchor.year + total // 12, total % 12 + 1
    return anchor.replace(year=year, month=month, day=min(anchor.day, calendar.monthrange(year, month)[1]))


def next_occurrence(due: datetime, recurrence: str, after: datetime) -> datetime | None:
    """First occurrence strictly after *after*, or None for one-off reminders.

    Computed arithmetically from the original *due* (not by stepping), so a reminder that was
    overdue for years still resolves instantly and monthly recurrences never drift.
    """
    if recurrence in ("daily", "weekly"):
        period = timedelta(days=1 if recurrence == "daily" else 7)
        k = max(1, (after - due) // period + 1)
        return due + k * period
    if recurrence == "weekdays":
        nxt = due + timedelta(days=max(1, (after - due) // timedelta(days=1)))   # jump close, then walk at most a week
        while nxt <= after or nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        return nxt
    if recurrence == "monthly":
        k = max(1, (after.year - due.year) * 12 + after.month - due.month)
        nxt = _add_months(due, k)
        while nxt <= after:
            k += 1
            nxt = _add_months(due, k)
        return nxt
    return None


async def claim(session: AsyncSession, r: Reminder, now: datetime) -> bool:
    """Atomically take ownership of firing *r*. Returns True for exactly one caller.

    A conditional UPDATE (`WHERE status='pending' AND due_at=<the value we read>`) is the lock: if two
    workers, or two API replicas, race on the same reminder, only one UPDATE matches a row.
    """
    nxt = next_occurrence(r.due_at, r.recurrence, now)
    values = {"fired_at": now, "updated_at": utcnow(), **({"due_at": nxt} if nxt else {"status": "fired"})}
    res = await session.execute(update(Reminder).where(Reminder.id == r.id, Reminder.status == "pending", Reminder.due_at == r.due_at).values(**values))
    return res.rowcount == 1


async def fire_due(session: AsyncSession, hub: EventHub, now: datetime | None = None) -> int:
    """Fire every reminder that is due. Safe to run from many workers at once: each reminder fires exactly once."""
    now = now or utcnow()
    q = select(Reminder).where(Reminder.status == "pending", Reminder.due_at <= now, Reminder.deleted_at.is_(None))
    fired = 0
    for r in list((await session.execute(q)).scalars()):
        snapshot = (r.id, r.title, r.style, r.user_id)
        if not await claim(session, r, now):
            continue  # another worker got it
        await session.commit()  # release the row before doing network I/O
        rid, title, style, user_id = snapshot
        user = await session.get(User, user_id)
        first = (user.name or "").split(" ")[0] if user else ""
        await hub.publish(user_id, {"type": "reminder.due", "id": rid, "title": title, "style": style,
                                    "text": say("reminder_due", style, first or None, title=title)})
        fired += 1
    return fired


async def worker(app, interval_s: float = 10.0) -> None:
    """Background loop started from the app lifespan."""
    while True:
        try:
            async with app.state.db.session() as session:
                n = await fire_due(session, app.state.hub)
                await session.commit()
                if n:
                    log.info("fired %d reminder(s)", n)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the worker must survive transient DB errors
            log.exception("reminder worker tick failed")
        await asyncio.sleep(interval_s)
