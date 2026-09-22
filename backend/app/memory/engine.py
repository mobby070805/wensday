"""Memory engine: structured preferences + episodic/long-term memory with semantic recall.

* **Preferences** — relational key/value (name, language, voice…), always injected into prompts.
* **Memories**   — text + embedding + importance. Recall blends similarity, importance and recency.
* **Consolidation** — near-duplicate memories bump importance instead of piling up.
* **Decay**      — old, low-importance, never-recalled episodic memories are pruned.
The database is the source of truth; the vector store is an index that can be rebuilt (`reindex`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import utcnow
from app.models import Memory, Preference, User
from .embeddings import Embedder, cosine
from .facts import Fact, extract_facts
from .vectorstore import VectorStore

COLLECTION = "memories"
DEDUPE_SIMILARITY = 0.92
STORE_THRESHOLD = 0.4  # episodic memories below this importance are not worth keeping

# how important is an event of this intent to remember?
INTENT_IMPORTANCE = {"mood_low": 0.5, "presence_update": 0.4, "goal_create": 0.7, "email_draft": 0.45,
                     "calendar_create": 0.5, "reminder_create": 0.45, "llm": 0.4}


@dataclass
class Recalled:
    memory: Memory
    score: float


class MemoryEngine:
    def __init__(self, embedder: Embedder, store: VectorStore):
        self.embedder, self.store = embedder, store
        self._hydrated: set[str] = set()

    # ------------------------------------------------------------ preferences
    async def preferences(self, session: AsyncSession, user_id: str) -> dict:
        rows = (await session.execute(select(Preference).where(Preference.user_id == user_id, Preference.deleted_at.is_(None)))).scalars()
        return {p.key: p.value for p in rows}

    async def set_preference(self, session: AsyncSession, user_id: str, key: str, value) -> None:
        row = (await session.execute(select(Preference).where(Preference.user_id == user_id, Preference.key == key))).scalars().first()
        if row:
            row.value, row.deleted_at = value, None
        else:
            session.add(Preference(user_id=user_id, key=key, value=value))
        await session.flush()

    # ------------------------------------------------------------ memories
    async def _hydrate(self, session: AsyncSession, user_id: str) -> None:
        if self.store.persistent or user_id in self._hydrated:
            return
        rows = (await session.execute(select(Memory).where(Memory.user_id == user_id, Memory.deleted_at.is_(None),
                                                            Memory.embedding.is_not(None)))).scalars()
        for m in rows:
            await self.store.upsert(COLLECTION, m.id, m.embedding, {"user_id": user_id})
        self._hydrated.add(user_id)

    async def remember(self, session: AsyncSession, user_id: str, text: str, *, kind: str = "episodic",
                       importance: float = 0.5, meta: dict | None = None) -> Memory | None:
        text = text.strip()
        if not text or (kind == "episodic" and importance < STORE_THRESHOLD):
            return None
        await self._hydrate(session, user_id)
        vec = (await self.embedder.embed([text]))[0]
        for id_, sim, _ in await self.store.search(COLLECTION, vec, 1, {"user_id": user_id}):
            if sim >= DEDUPE_SIMILARITY:
                existing = await session.get(Memory, id_)
                if existing and not existing.deleted_at:
                    existing.importance = min(1.0, max(existing.importance, importance) + 0.05)
                    existing.access_count += 1
                    await session.flush()
                    return existing
        mem = Memory(user_id=user_id, kind=kind, text=text, importance=importance, embedding=vec, meta=meta or {})
        session.add(mem)
        await session.flush()
        await self.store.upsert(COLLECTION, mem.id, vec, {"user_id": user_id})
        return mem

    async def recall(self, session: AsyncSession, user_id: str, query: str, k: int = 5, min_similarity: float = 0.15,
                     now: datetime | None = None) -> list[Recalled]:
        await self._hydrate(session, user_id)
        now = now or utcnow()
        vec = (await self.embedder.embed([query]))[0]
        hits = await self.store.search(COLLECTION, vec, k * 3, {"user_id": user_id})
        sims = {i: s for i, s, _ in hits if s >= min_similarity}
        if not sims:
            return []
        rows = (await session.execute(select(Memory).where(Memory.id.in_(sims), Memory.deleted_at.is_(None)))).scalars().all()
        scored = []
        for m in rows:
            age_days = max(0.0, (now - m.created_at).total_seconds() / 86400)
            recency = math.exp(-age_days / 45)
            scored.append(Recalled(m, 0.7 * sims[m.id] + 0.2 * m.importance + 0.1 * recency))
        scored.sort(key=lambda r: r.score, reverse=True)
        top = scored[:k]
        for r in top:
            r.memory.access_count += 1
            r.memory.last_accessed = now
        await session.flush()
        return top

    async def forget(self, session: AsyncSession, user_id: str, memory_id: str) -> bool:
        m = await session.get(Memory, memory_id)
        if not m or m.user_id != user_id or m.deleted_at:
            return False
        m.deleted_at = utcnow()
        await self.store.delete(COLLECTION, memory_id)
        await session.flush()
        return True

    async def forget_all(self, session: AsyncSession, user_id: str) -> int:
        ids = (await session.execute(select(Memory.id).where(Memory.user_id == user_id, Memory.deleted_at.is_(None)))).scalars().all()
        for i in ids:
            await self.forget(session, user_id, i)
        return len(ids)

    async def prune(self, session: AsyncSession, user_id: str, now: datetime | None = None) -> int:
        """Drop stale, unimportant, never-recalled episodic memories (older than 60 days)."""
        now = now or utcnow()
        q = select(Memory).where(Memory.user_id == user_id, Memory.kind == "episodic", Memory.deleted_at.is_(None),
                                 Memory.importance < 0.6, Memory.access_count == 0, Memory.created_at < now - timedelta(days=60))
        stale = list((await session.execute(q)).scalars())
        for m in stale:
            await self.forget(session, user_id, m.id)
        return len(stale)

    async def reindex(self, session: AsyncSession, user_id: str) -> int:
        """Rebuild the vector index for a user from the database (e.g. after switching to Qdrant)."""
        rows = (await session.execute(select(Memory).where(Memory.user_id == user_id, Memory.deleted_at.is_(None)))).scalars().all()
        for m in rows:
            m.embedding = (await self.embedder.embed([m.text]))[0]
            await self.store.upsert(COLLECTION, m.id, m.embedding, {"user_id": user_id})
        self._hydrated.add(user_id)
        await session.flush()
        return len(rows)

    # ------------------------------------------------------------ learning
    async def learn(self, session: AsyncSession, user: User, text: str) -> list[Fact]:
        """Pull explicit facts out of an utterance; update preferences and store memories."""
        facts = extract_facts(text)
        for f in facts:
            if f.type in ("name", "language"):
                await self.set_preference(session, user.id, f.key, f.value)
                if f.type == "name" and not user.name:
                    user.name = f.value
            await self.remember(session, user.id, f.text, kind="fact", importance=f.importance, meta={"type": f.type})
        return facts

    async def note_event(self, session: AsyncSession, user_id: str, text: str, intent: str) -> None:
        importance = INTENT_IMPORTANCE.get(intent, 0.3)
        await self.remember(session, user_id, text, kind="episodic", importance=importance, meta={"intent": intent})

    # ------------------------------------------------------------ prompt context
    async def context_block(self, session: AsyncSession, user: User, query: str, k: int = 5) -> str:
        prefs = await self.preferences(session, user.id)
        lines = []
        if prefs:
            lines.append("Known preferences: " + "; ".join(f"{k}={v}" for k, v in prefs.items()))
        recalled = await self.recall(session, user.id, query, k=k)
        if recalled:
            lines.append("Relevant memories:\n" + "\n".join(f"- {r.memory.text}" for r in recalled))
        return "\n".join(lines)
