from __future__ import annotations

import difflib
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import utcnow
from app.models import Event


async def conflicts(session: AsyncSession, user_id: str, start: datetime, end: datetime, exclude_id: str | None = None) -> list[Event]:
    q = select(Event).where(Event.user_id == user_id, Event.deleted_at.is_(None), Event.start_at < end, Event.end_at > start)
    rows = list((await session.execute(q)).scalars())
    return [e for e in rows if e.id != exclude_id]


async def create_event(session: AsyncSession, user_id: str, title: str, start: datetime, end: datetime | None = None, *,
                       location: str = "", notes: str = "", attendees: list[str] | None = None,
                       source: str = "local", external_id: str | None = None) -> tuple[Event, list[Event]]:
    end = end or start + timedelta(hours=1)
    clashes = await conflicts(session, user_id, start, end)
    ev = Event(user_id=user_id, title=title.strip() or "Meeting", start_at=start, end_at=end, location=location,
               notes=notes, attendees=attendees or [], source=source, external_id=external_id)
    session.add(ev)
    await session.flush()
    return ev, clashes


async def between(session: AsyncSession, user_id: str, start: datetime, end: datetime) -> list[Event]:
    q = (select(Event).where(Event.user_id == user_id, Event.deleted_at.is_(None), Event.start_at >= start, Event.start_at < end)
         .order_by(Event.start_at))
    return list((await session.execute(q)).scalars())


async def next_event(session: AsyncSession, user_id: str, now: datetime | None = None) -> Event | None:
    now = now or utcnow()
    q = (select(Event).where(Event.user_id == user_id, Event.deleted_at.is_(None), Event.end_at > now)
         .order_by(Event.start_at).limit(1))
    return (await session.execute(q)).scalars().first()


async def find_by_title(session: AsyncSession, user_id: str, query: str, now: datetime | None = None) -> Event | None:
    now = now or utcnow()
    q = select(Event).where(Event.user_id == user_id, Event.deleted_at.is_(None), Event.end_at > now).order_by(Event.start_at)
    events = list((await session.execute(q)).scalars())
    query = query.lower().strip()
    if not events:
        return None
    if not query:
        return events[0] if len(events) == 1 else None
    for e in events:
        if query in e.title.lower() or e.title.lower() in query:
            return e
    best = max(events, key=lambda e: difflib.SequenceMatcher(None, query, e.title.lower()).ratio())
    return best if difflib.SequenceMatcher(None, query, best.title.lower()).ratio() >= 0.6 else None


async def reschedule(session: AsyncSession, event: Event, new_start: datetime) -> Event:
    length = event.end_at - event.start_at
    event.start_at, event.end_at = new_start, new_start + length
    await session.flush()
    return event
