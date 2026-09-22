"""Tasks, reminders, events, notes, goals."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as sc
from app.core.timeutil import utcnow
from app.db import get_session
from app.deps import current_user, rate_limit
from app.models import Event, Goal, Milestone, Note, Reminder, Task, User
from app.services import goals as goals_svc
from .crud import crud_router


async def _task_update(session, task, data):
    if data.get("status") == "done" and task.status != "done":
        data["completed_at"] = utcnow()
    elif data.get("status") == "open":
        data["completed_at"] = None
    return data


async def _event_create(session, user, data):
    data["end_at"] = data.get("end_at") or data["start_at"] + timedelta(hours=1)
    if data["end_at"] <= data["start_at"]:
        raise HTTPException(422, "end_at must be after start_at")
    return data


tasks = crud_router(prefix="/tasks", model=Task, create_schema=sc.TaskIn, update_schema=sc.TaskUpdate, out_schema=sc.TaskOut,
                    filters={"status": Task.status}, before_update=_task_update)
reminders = crud_router(prefix="/reminders", model=Reminder, create_schema=sc.ReminderIn, update_schema=sc.ReminderUpdate,
                        out_schema=sc.ReminderOut, order_by=Reminder.due_at, filters={"status": Reminder.status})
events = crud_router(prefix="/events", model=Event, create_schema=sc.EventIn, update_schema=sc.EventUpdate, out_schema=sc.EventOut,
                     order_by=Event.start_at, before_create=_event_create)
notes = crud_router(prefix="/notes", model=Note, create_schema=sc.NoteIn, update_schema=sc.NoteUpdate, out_schema=sc.NoteOut,
                    filters={"kind": Note.kind})

# ---- goals: custom because progress is computed and milestones nest
goals = APIRouter(prefix="/goals", tags=["goals"], dependencies=[Depends(rate_limit)])


async def _goal(session: AsyncSession, user: User, id: str) -> Goal:
    g = await session.get(Goal, id)
    if not g or g.user_id != user.id or g.deleted_at:
        raise HTTPException(404, "goal not found")
    return g


@goals.get("", response_model=list[sc.GoalOut])
async def list_goals(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Goal).where(Goal.user_id == user.id, Goal.deleted_at.is_(None)).order_by(Goal.created_at))).scalars()
    return [await goals_svc.to_out(session, g) for g in rows]


@goals.post("", response_model=sc.GoalOut, status_code=201)
async def create_goal(body: sc.GoalIn, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    g = await goals_svc.create_goal(session, user.id, body.title, description=body.description, target_date=body.target_date,
                                    milestones=[m.title for m in body.milestones])
    await session.commit()
    await request.app.state.hub.publish(user.id, {"type": "sync", "kind": "goals", "op": "create", "id": g.id})
    return await goals_svc.to_out(session, g)


@goals.get("/{id}", response_model=sc.GoalOut)
async def read_goal(id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await goals_svc.to_out(session, await _goal(session, user, id))


@goals.patch("/{id}", response_model=sc.GoalOut)
async def update_goal(id: str, body: sc.GoalUpdate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    g = await _goal(session, user, id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(g, k, v)
    g.updated_at = utcnow()
    await session.flush()
    return await goals_svc.to_out(session, g)


@goals.delete("/{id}", status_code=204)
async def delete_goal(id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    g = await _goal(session, user, id)
    g.deleted_at = g.updated_at = utcnow()


@goals.post("/{id}/milestones", response_model=sc.GoalOut, status_code=201)
async def add_milestone(id: str, body: sc.MilestoneIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    g = await _goal(session, user, id)
    g.milestones.append(Milestone(title=body.title))
    g.updated_at = utcnow()
    await session.flush()
    return await goals_svc.to_out(session, g)


@goals.post("/{id}/milestones/{mid}/toggle", response_model=sc.GoalOut)
async def toggle_milestone(id: str, mid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    g = await _goal(session, user, id)
    m = next((m for m in g.milestones if m.id == mid), None)
    if not m:
        raise HTTPException(404, "milestone not found")
    m.done = not m.done
    g.updated_at = utcnow()
    await session.flush()
    return await goals_svc.to_out(session, g)
