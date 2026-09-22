"""Conversation, memory, knowledge and meetings."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as sc
from app.core.timeutil import utcnow
from app.db import get_session
from app.deps import current_user, rate_limit
from app.models import Conversation, Document, Memory, Message, User
from app.services import meetings as meetings_svc

router = APIRouter(tags=["assistant"], dependencies=[Depends(rate_limit)])

_WRITE_INTENTS = {"reminder_create", "task_create", "task_complete", "note_create", "goal_create", "calendar_create",
                  "schedule_update", "email_draft", "email_send", "workflow", "llm"}


@router.post("/chat", response_model=sc.ChatOut)
async def chat(body: sc.ChatIn, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    st = request.app.state
    out = await st.agent.handle(st.make_ctx(session, user), body.text, body.conversation_id, body.lang_hint)
    await session.commit()
    if out.intent in _WRITE_INTENTS:  # tell the user's other devices to refresh
        await st.hub.publish(user.id, {"type": "sync", "kind": "all", "op": "chat"})
    return out


@router.get("/conversations")
async def list_conversations(user: User = Depends(current_user), session: AsyncSession = Depends(get_session), limit: int = Query(30, le=100)):
    rows = (await session.execute(select(Conversation).where(Conversation.user_id == user.id, Conversation.deleted_at.is_(None))
                                  .order_by(Conversation.updated_at.desc()).limit(limit))).scalars()
    return [{"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat() + "Z"} for c in rows]


@router.get("/conversations/{cid}/messages")
async def conversation_messages(cid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    conv = await session.get(Conversation, cid)
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "conversation not found")
    rows = (await session.execute(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).scalars()
    return [{"id": m.id, "role": m.role, "text": m.text, "lang": m.lang, "intent": m.intent, "at": m.created_at.isoformat() + "Z"} for m in rows]


@router.delete("/conversations/{cid}", status_code=204)
async def delete_conversation(cid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    conv = await session.get(Conversation, cid)
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "conversation not found")
    await session.delete(conv)
    return Response(status_code=204)


# ------------------------------------------------------------------ memory
@router.get("/memories", response_model=list[sc.MemoryOut])
async def list_memories(user: User = Depends(current_user), session: AsyncSession = Depends(get_session), kind: str | None = None,
                        limit: int = Query(100, le=500)):
    q = select(Memory).where(Memory.user_id == user.id, Memory.deleted_at.is_(None))
    if kind:
        q = q.where(Memory.kind == kind)
    return list((await session.execute(q.order_by(Memory.created_at.desc()).limit(limit))).scalars())


@router.post("/memories", response_model=sc.MemoryOut, status_code=201)
async def add_memory(body: sc.MemoryIn, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    m = await request.app.state.memory.remember(session, user.id, body.text, kind=body.kind, importance=body.importance)
    if m is None:
        raise HTTPException(422, "memory not stored (importance too low)")
    return m


@router.get("/memories/search", response_model=list[sc.MemoryOut])
async def search_memories(q: str, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session), k: int = 5):
    return [r.memory for r in await request.app.state.memory.recall(session, user.id, q, k=k)]


@router.delete("/memories/{mid}", status_code=204)
async def forget(mid: str, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if not await request.app.state.memory.forget(session, user.id, mid):
        raise HTTPException(404, "memory not found")
    return Response(status_code=204)


@router.delete("/memories")
async def forget_all(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return {"forgotten": await request.app.state.memory.forget_all(session, user.id)}


@router.post("/memories/reindex")
async def reindex(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return {"reindexed": await request.app.state.memory.reindex(session, user.id)}


@router.get("/export")
async def export_my_data(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Privacy: everything Wensday remembers about you, in one JSON document."""
    mem = request.app.state.memory
    rows = (await session.execute(select(Memory).where(Memory.user_id == user.id, Memory.deleted_at.is_(None)))).scalars()
    return {"exported_at": utcnow().isoformat() + "Z", "user": {"email": user.email, "name": user.name, "timezone": user.timezone},
            "preferences": await mem.preferences(session, user.id),
            "memories": [{"kind": m.kind, "text": m.text, "importance": m.importance, "created_at": m.created_at.isoformat() + "Z"} for m in rows]}


# ------------------------------------------------------------------ knowledge / documents / meetings
@router.post("/documents", response_model=sc.DocumentOut, status_code=201)
async def add_document(body: sc.DocumentIn, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await request.app.state.knowledge.ingest(session, user.id, body.title, body.text, body.mime)


@router.get("/documents", response_model=list[sc.DocumentOut])
async def list_documents(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return list((await session.execute(select(Document).where(Document.user_id == user.id, Document.deleted_at.is_(None))
                                       .order_by(Document.created_at.desc()))).scalars())


@router.delete("/documents/{did}", status_code=204)
async def delete_document(did: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    d = await session.get(Document, did)
    if not d or d.user_id != user.id:
        raise HTTPException(404, "document not found")
    await session.delete(d)
    return Response(status_code=204)


@router.post("/knowledge/ask")
async def ask(body: sc.AskIn, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await request.app.state.knowledge.answer(session, user.id, body.question)


@router.post("/meetings/summarize")
async def summarize_meeting(body: sc.MeetingIn, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    result = await meetings_svc.summarize(request.app.state.llm, body.transcript)
    saved = await meetings_svc.save_meeting(session, user.id, body.title, result, create_tasks=body.create_tasks)
    return {**result, **saved}
