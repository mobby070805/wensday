from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note


async def create_note(session: AsyncSession, user_id: str, body: str, *, title: str = "", kind: str = "note",
                      tags: list[str] | None = None, meta: dict | None = None) -> Note:
    body = body.strip()
    title = (title or body.split("\n", 1)[0])[:80]
    note = Note(user_id=user_id, title=title, body=body, kind=kind, tags=tags or [], meta=meta or {})
    session.add(note)
    await session.flush()
    return note


def _terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[\w஀-௿]+", text.lower()) if len(t) > 1]


async def search(session: AsyncSession, user_id: str, query: str, limit: int = 10) -> list[Note]:
    """Keyword search (title weighted x3, tags x2). Semantic search lives in memory.knowledge."""
    terms = _terms(query)
    notes = list((await session.execute(select(Note).where(Note.user_id == user_id, Note.deleted_at.is_(None)))).scalars())
    if not terms:
        return sorted(notes, key=lambda n: n.updated_at, reverse=True)[:limit]
    scored = []
    for n in notes:
        hay_title, hay_body, hay_tags = n.title.lower(), n.body.lower(), " ".join(n.tags).lower()
        s = sum(3 * (t in hay_title) + (t in hay_body) + 2 * (t in hay_tags) for t in terms)
        if s:
            scored.append((s, n))
    scored.sort(key=lambda p: (p[0], p[1].updated_at), reverse=True)
    return [n for _, n in scored[:limit]]
