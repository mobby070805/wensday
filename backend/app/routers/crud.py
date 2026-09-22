"""Generic per-user CRUD router factory.

Every query is scoped by `user_id` and hides tombstoned rows, so tenant isolation lives in one
place. Deletes are soft (tombstone) so other devices learn about them through `/sync`.
Each write commits *before* publishing the sync event, so a device that reacts to the event
always reads the committed row.
"""
# NOTE: deliberately no `from __future__ import annotations` here. The route signatures below use
# `create_schema` / `update_schema` (closure variables) as annotations, and FastAPI can only resolve
# them if the annotations are real objects rather than strings.
from collections.abc import Awaitable, Callable
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import to_naive_utc, utcnow
from app.db import get_session
from app.deps import current_user, rate_limit
from app.models import User


def crud_router(*, prefix: str, model, create_schema, update_schema, out_schema, order_by=None, filters: dict | None = None,
                before_create: Callable[..., Awaitable[dict]] | None = None,
                before_update: Callable[..., Awaitable[dict]] | None = None) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[prefix.strip("/")], dependencies=[Depends(rate_limit)])
    filters = filters or {}
    kind = prefix.strip("/")

    async def _get(session: AsyncSession, user: User, id: str):
        obj = await session.get(model, id)
        if not obj or obj.user_id != user.id or obj.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{kind[:-1]} not found")
        return obj

    async def _emit(request: Request, user: User, op: str, id: str):
        await request.app.state.hub.publish(user.id, {"type": "sync", "kind": kind, "op": op, "id": id})

    @router.get("", response_model=list[out_schema])
    async def list_(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), since: datetime | None = None):
        q = select(model).where(model.user_id == user.id, model.deleted_at.is_(None))
        for param, col in filters.items():
            if (v := request.query_params.get(param)) is not None:
                q = q.where(col == v)
        if since:
            q = q.where(model.updated_at > to_naive_utc(since))
        q = q.order_by(order_by if order_by is not None else model.created_at.desc()).limit(limit).offset(offset)
        return list((await session.execute(q)).scalars())

    @router.post("", response_model=out_schema, status_code=201)
    async def create(body: create_schema, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
        data = body.model_dump()
        if before_create:
            data = await before_create(session, user, data)
        obj = model(user_id=user.id, **data)
        session.add(obj)
        await session.commit()
        await _emit(request, user, "create", obj.id)
        return obj

    @router.get("/{id}", response_model=out_schema)
    async def read(id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
        return await _get(session, user, id)

    @router.patch("/{id}", response_model=out_schema)
    async def update(id: str, body: update_schema, request: Request, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
        obj = await _get(session, user, id)
        data = body.model_dump(exclude_unset=True)
        if before_update:
            data = await before_update(session, obj, data)
        for k, v in data.items():
            setattr(obj, k, v)
        obj.updated_at = utcnow()
        await session.commit()
        await _emit(request, user, "update", obj.id)
        return obj

    @router.delete("/{id}", status_code=204)
    async def delete(id: str, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
        obj = await _get(session, user, id)
        obj.deleted_at = obj.updated_at = utcnow()
        await session.commit()
        await _emit(request, user, "delete", obj.id)
        return Response(status_code=204)

    return router
