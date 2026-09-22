"""Knowledge retrieval + document analysis (RAG over documents, notes and memories)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentChunk, Memory, Note
from .embeddings import Embedder, cosine

_SENT = re.compile(r"(?<=[.!?।])\s+|\n{2,}")


def chunk_text(text: str, max_chars: int = 600, overlap_sentences: int = 1) -> list[str]:
    """Sentence-aware chunking with one sentence of overlap between chunks."""
    sentences = [s.strip() for s in _SENT.split(text) if s.strip()]
    chunks: list[str] = []
    cur: list[str] = []
    size = 0
    for s in sentences:
        if cur and size + len(s) > max_chars:
            chunks.append(" ".join(cur))
            cur = cur[-overlap_sentences:] if overlap_sentences else []
            size = sum(len(x) for x in cur)
        cur.append(s)
        size += len(s)
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def extractive_summary(text: str, sentences: int = 3) -> str:
    """Offline summary: the first sentence plus the longest (most informative) others, in order."""
    sents = [s.strip() for s in _SENT.split(text) if len(s.strip()) > 20]
    if len(sents) <= sentences:
        return " ".join(sents)
    picked = {0} | set(sorted(range(1, len(sents)), key=lambda i: len(sents[i]), reverse=True)[: sentences - 1])
    return " ".join(sents[i] for i in sorted(picked))


@dataclass
class Hit:
    source: str        # document | note | memory
    title: str
    text: str
    score: float
    ref_id: str


class Knowledge:
    def __init__(self, embedder: Embedder, llm=None):
        self.embedder, self.llm = embedder, llm

    async def ingest(self, session: AsyncSession, user_id: str, title: str, text: str, mime: str = "text/plain") -> Document:
        chunks = chunk_text(text)
        vecs = await self.embedder.embed(chunks) if chunks else []
        summary = extractive_summary(text)
        if self.llm is not None and getattr(self.llm, "has_remote", False):
            try:
                resp = await self.llm.complete("Summarise the document in 3 short sentences, in the document's own language.",
                                               [{"role": "user", "content": text[:12000]}], None, 300)
                summary = resp.text or summary
            except Exception:  # noqa: BLE001
                pass
        doc = Document(user_id=user_id, title=title, mime=mime, text=text, summary=summary)
        doc.chunks = [DocumentChunk(user_id=user_id, idx=i, text=c, embedding=v) for i, (c, v) in enumerate(zip(chunks, vecs))]
        session.add(doc)
        await session.flush()
        return doc

    async def search(self, session: AsyncSession, user_id: str, query: str, k: int = 5, min_similarity: float = 0.12) -> list[Hit]:
        qv = (await self.embedder.embed([query]))[0]
        hits: list[Hit] = []

        rows = (await session.execute(select(DocumentChunk, Document.title).join(Document, Document.id == DocumentChunk.document_id)
                                      .where(DocumentChunk.user_id == user_id, Document.deleted_at.is_(None)))).all()
        for chunk, title in rows:
            if chunk.embedding:
                hits.append(Hit("document", title, chunk.text, cosine(qv, chunk.embedding), chunk.document_id))

        notes = list((await session.execute(select(Note).where(Note.user_id == user_id, Note.deleted_at.is_(None)))).scalars())
        missing = [n for n in notes if n.embedding is None]
        if missing:
            for n, v in zip(missing, await self.embedder.embed([f"{n.title}\n{n.body}" for n in missing])):
                n.embedding = v
            await session.flush()
        for n in notes:
            hits.append(Hit("note", n.title or "Note", n.body, cosine(qv, n.embedding), n.id))

        mems = (await session.execute(select(Memory).where(Memory.user_id == user_id, Memory.deleted_at.is_(None),
                                                            Memory.embedding.is_not(None)))).scalars()
        for m in mems:
            hits.append(Hit("memory", "Memory", m.text, cosine(qv, m.embedding), m.id))

        hits = [h for h in hits if h.score >= min_similarity]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    async def answer(self, session: AsyncSession, user_id: str, question: str) -> dict:
        hits = await self.search(session, user_id, question)
        citations = [{"source": h.source, "title": h.title, "ref_id": h.ref_id, "score": round(h.score, 3)} for h in hits]
        if not hits:
            return {"answer": None, "citations": []}
        if self.llm is not None and getattr(self.llm, "has_remote", False):
            ctx = "\n\n".join(f"[{i + 1}] ({h.source}: {h.title}) {h.text}" for i, h in enumerate(hits))
            resp = await self.llm.complete(
                "Answer the question using ONLY the numbered context. Cite sources like [1]. If the context does not "
                "contain the answer, say so. Reply in the language style of the question (Tamil, English or Tanglish).",
                [{"role": "user", "content": f"Context:\n{ctx}\n\nQuestion: {question}"}], None, 500)
            if resp.text:
                return {"answer": resp.text, "citations": citations}
        return {"answer": hits[0].text, "citations": citations}  # offline: best passage, verbatim
