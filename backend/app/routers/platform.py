"""Preferences, devices, plugins, workflows, analytics, sync and integrations."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as sc
from app.core.timeutil import iso_z, to_naive_utc, utcnow
from app.db import get_session
from app.deps import current_user, rate_limit
from app.integrations import google as g
from app.models import Device, Event, Goal, Note, OAuthAccount, Reminder, Task, User, Workflow
from app.services import analytics as analytics_svc
from app.services import coaching, workflows as wf_svc
from app.services import goals as goals_svc

router = APIRouter(dependencies=[Depends(rate_limit)])


# ------------------------------------------------------------------ preferences / devices
@router.get("/preferences", tags=["preferences"])
async def get_preferences(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await request.app.state.memory.preferences(session, user.id)


@router.put("/preferences/{key}", tags=["preferences"], response_model=sc.PreferenceOut)
async def put_preference(key: str, body: sc.PreferenceIn, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if len(key) > 80:
        raise HTTPException(422, "key too long")
    await request.app.state.memory.set_preference(session, user.id, key, body.value)
    return sc.PreferenceOut(key=key, value=body.value)


@router.post("/devices", tags=["devices"], status_code=201)
async def register_device(body: sc.DeviceIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if body.push_token:  # one row per push token: re-registering a device updates it
        existing = (await session.execute(select(Device).where(Device.user_id == user.id, Device.push_token == body.push_token))).scalars().first()
        if existing:
            existing.name, existing.last_seen, existing.deleted_at = body.name, utcnow(), None
            return {"id": existing.id}
    d = Device(user_id=user.id, name=body.name, platform=body.platform, push_token=body.push_token, last_seen=utcnow())
    session.add(d)
    await session.flush()
    return {"id": d.id}


@router.get("/devices", tags=["devices"])
async def list_devices(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Device).where(Device.user_id == user.id, Device.deleted_at.is_(None)))).scalars()
    return [{"id": d.id, "name": d.name, "platform": d.platform, "last_seen": iso_z(d.last_seen)} for d in rows]


@router.delete("/devices/{did}", tags=["devices"], status_code=204)
async def remove_device(did: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    d = await session.get(Device, did)
    if not d or d.user_id != user.id:
        raise HTTPException(404, "device not found")
    d.deleted_at = utcnow()
    return Response(status_code=204)


# ------------------------------------------------------------------ plugins
class PluginEnable(BaseModel):
    scopes: list[str] | None = None
    config: dict | None = None


@router.get("/plugins", tags=["plugins"])
async def list_plugins(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    pm = request.app.state.plugins
    out = []
    for spec in pm.plugins.values():
        st = await pm.setting(session, user.id, spec.name)
        out.append({"name": spec.name, "version": spec.version, "description": spec.description, "scopes": spec.scopes,
                    "tools": [t.name for t in spec.tools], "enabled": bool(st and st.enabled),
                    "granted_scopes": st.granted_scopes if st else [], "config": st.config if st else {}})
    return out


@router.post("/plugins/{name}/enable", tags=["plugins"])
async def enable_plugin(name: str, body: PluginEnable, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    pm = request.app.state.plugins
    if name not in pm.plugins:
        raise HTTPException(404, "unknown plugin")
    st = await pm.enable(session, user.id, name, body.scopes, body.config)
    return {"name": name, "enabled": True, "granted_scopes": st.granted_scopes}


@router.post("/plugins/{name}/disable", tags=["plugins"])
async def disable_plugin(name: str, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if name not in request.app.state.plugins.plugins:
        raise HTTPException(404, "unknown plugin")
    await request.app.state.plugins.disable(session, user.id, name)
    return {"name": name, "enabled": False}


# ------------------------------------------------------------------ workflows
async def _wf(session, user, wid) -> Workflow:
    wf = await session.get(Workflow, wid)
    if not wf or wf.user_id != user.id or wf.deleted_at:
        raise HTTPException(404, "workflow not found")
    return wf


@router.get("/workflows", tags=["workflows"], response_model=list[sc.WorkflowOut])
async def list_workflows(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return list((await session.execute(select(Workflow).where(Workflow.user_id == user.id, Workflow.deleted_at.is_(None)))).scalars())


@router.post("/workflows", tags=["workflows"], response_model=sc.WorkflowOut, status_code=201)
async def create_workflow(body: sc.WorkflowIn, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    reg = request.app.state.registry
    for i, step in enumerate(body.steps):
        tool = reg.get(step.get("tool", ""))
        if tool is None:
            raise HTTPException(422, f"step {i + 1}: unknown tool '{step.get('tool')}'")
        if tool.requires_confirmation:
            raise HTTPException(422, f"step {i + 1}: '{tool.name}' needs user confirmation and cannot run in a workflow")
    wf = Workflow(user_id=user.id, **body.model_dump())
    session.add(wf)
    await session.flush()
    return wf


@router.delete("/workflows/{wid}", tags=["workflows"], status_code=204)
async def delete_workflow(wid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    (await _wf(session, user, wid)).deleted_at = utcnow()
    return Response(status_code=204)


@router.post("/workflows/{wid}/run", tags=["workflows"])
async def run_workflow(wid: str, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    wf = await _wf(session, user, wid)
    run = await wf_svc.run_workflow(request.app.state.make_ctx(session, user), request.app.state.registry, wf)
    return {"status": run.status, "log": run.log}


# ------------------------------------------------------------------ analytics
@router.get("/analytics/dashboard", tags=["analytics"])
async def dashboard(user: User = Depends(current_user), session: AsyncSession = Depends(get_session), days: int = Query(14, ge=7, le=90)):
    return await analytics_svc.dashboard(session, user.id, utcnow(), user.timezone, days)


@router.get("/analytics/weekly-review", tags=["analytics"])
async def weekly_review(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await coaching.weekly_review(session, user.id, utcnow())


# ------------------------------------------------------------------ sync
_SYNC = {"tasks": (Task, sc.TaskOut), "reminders": (Reminder, sc.ReminderOut), "events": (Event, sc.EventOut), "notes": (Note, sc.NoteOut)}


@router.get("/sync", tags=["sync"])
async def sync(user: User = Depends(current_user), session: AsyncSession = Depends(get_session), since: datetime | None = None):
    """Incremental pull. Persist `server_time` and send it back as `since` next time.
    Deleted rows come back as tombstones `{id, deleted: true}`."""
    server_time = utcnow()
    cut = to_naive_utc(since) if since else datetime(1970, 1, 1)
    changes: dict[str, list] = {}
    for name, (model, out) in _SYNC.items():
        rows = (await session.execute(select(model).where(model.user_id == user.id, model.updated_at > cut))).scalars()
        changes[name] = [{"id": r.id, "deleted": True} if r.deleted_at else out.model_validate(r).model_dump(mode="json") for r in rows]
    grows = (await session.execute(select(Goal).where(Goal.user_id == user.id, Goal.updated_at > cut))).scalars()
    changes["goals"] = [{"id": r.id, "deleted": True} if r.deleted_at else (await goals_svc.to_out(session, r)).model_dump(mode="json") for r in grows]
    return {"server_time": iso_z(server_time), "changes": changes}


# ------------------------------------------------------------------ integrations
@router.get("/integrations/status", tags=["integrations"])
async def integrations_status(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    acct = (await session.execute(select(OAuthAccount).where(OAuthAccount.user_id == user.id, OAuthAccount.provider == "google"))).scalars().first()
    scopes = set(acct.scopes or []) if acct else set()
    return {"google": {"configured": request.app.state.google.configured, "connected": bool(acct),
                       "calendar": g.FEATURE_SCOPES["calendar"] in scopes, "gmail_send": g.FEATURE_SCOPES["gmail_send"] in scopes,
                       "gmail_read": g.FEATURE_SCOPES["gmail_read"] in scopes}}


@router.post("/integrations/google/calendar/sync", tags=["integrations"])
async def google_calendar_sync(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    st = request.app.state
    token = await g.access_token_for(session, st.settings, st.google, user.id, "calendar")
    if not token:
        raise HTTPException(409, "Google Calendar is not connected")
    try:
        return await g.sync_calendar(session, user.id, g.GoogleCalendar(st.http, token))
    except g.GoogleError as e:
        raise HTTPException(502, str(e)) from e


@router.get("/integrations/gmail/inbox", tags=["integrations"])
async def gmail_inbox(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session), n: int = Query(5, le=15)):
    st = request.app.state
    token = await g.access_token_for(session, st.settings, st.google, user.id, "gmail_read")
    if not token:
        raise HTTPException(409, "Gmail is not connected")
    try:
        msgs = await g.recent_inbox(st.http, token, n)
    except g.GoogleError as e:
        raise HTTPException(502, str(e)) from e
    summary = "\n".join(f"• {m['subject'] or '(no subject)'} — {m['from']}" for m in msgs)
    if st.llm.has_remote and msgs:
        resp = await st.llm.complete("Summarise these unread emails in 2-3 short sentences. Mention anything urgent.",
                                     [{"role": "user", "content": "\n".join(f"{m['from']}: {m['subject']} — {m['snippet']}" for m in msgs)}], None, 300)
        summary = resp.text or summary
    return {"messages": msgs, "summary": summary}
