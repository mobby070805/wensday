"""Google integration: OAuth2 (login + incremental consent), Calendar sync, Gmail send/read.

All HTTP goes through an injected httpx client so the flows are testable with MockTransport.
Tokens are encrypted at rest (Fernet) and refreshed transparently.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.timeutil import to_naive_utc, utcnow
from app.models import EmailDraft, Event, OAuthAccount, User
from app.security import decrypt_secret, encrypt_secret

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
CAL_API = "https://www.googleapis.com/calendar/v3"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"

BASE_SCOPES = ["openid", "email", "profile"]
FEATURE_SCOPES = {
    "calendar": "https://www.googleapis.com/auth/calendar",
    "gmail_send": "https://www.googleapis.com/auth/gmail.send",
    "gmail_read": "https://www.googleapis.com/auth/gmail.readonly",
}


class GoogleError(Exception):
    pass


class GoogleOAuth:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.s, self.http = settings, http

    @property
    def configured(self) -> bool:
        return bool(self.s.google_client_id and self.s.google_client_secret)

    def auth_url(self, state: str, features: list[str] | None = None) -> str:
        scopes = BASE_SCOPES + [FEATURE_SCOPES[f] for f in (features or []) if f in FEATURE_SCOPES]
        return AUTH_URL + "?" + urlencode({
            "client_id": self.s.google_client_id, "redirect_uri": self.s.google_redirect_uri, "response_type": "code",
            "scope": " ".join(scopes), "state": state, "access_type": "offline", "prompt": "consent",
            "include_granted_scopes": "true"})

    async def exchange_code(self, code: str) -> dict:
        r = await self.http.post(TOKEN_URL, data={
            "code": code, "client_id": self.s.google_client_id, "client_secret": self.s.google_client_secret,
            "redirect_uri": self.s.google_redirect_uri, "grant_type": "authorization_code"})
        if r.status_code != 200:
            raise GoogleError(f"token exchange failed: {r.status_code}")
        return r.json()

    async def userinfo(self, access_token: str) -> dict:
        r = await self.http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        if r.status_code != 200:
            raise GoogleError("userinfo failed")
        return r.json()

    async def refresh(self, refresh_token: str) -> dict:
        r = await self.http.post(TOKEN_URL, data={
            "refresh_token": refresh_token, "client_id": self.s.google_client_id,
            "client_secret": self.s.google_client_secret, "grant_type": "refresh_token"})
        if r.status_code != 200:
            raise GoogleError("token refresh failed")
        return r.json()


async def store_tokens(session: AsyncSession, settings: Settings, user_id: str, subject: str, tok: dict) -> OAuthAccount:
    acct = (await session.execute(select(OAuthAccount).where(OAuthAccount.provider == "google", OAuthAccount.subject == subject))).scalars().first()
    if acct is None:
        acct = OAuthAccount(user_id=user_id, provider="google", subject=subject)
        session.add(acct)
    acct.access_token_enc = encrypt_secret(settings, tok.get("access_token"))
    if tok.get("refresh_token"):  # Google only returns it on first consent
        acct.refresh_token_enc = encrypt_secret(settings, tok["refresh_token"])
    acct.scopes = sorted(set(acct.scopes or []) | set((tok.get("scope") or "").split()))
    acct.expires_at = utcnow() + timedelta(seconds=int(tok.get("expires_in", 3600)))
    await session.flush()
    return acct


async def access_token_for(session: AsyncSession, settings: Settings, oauth: GoogleOAuth, user_id: str,
                           need_scope: str | None = None) -> str | None:
    acct = (await session.execute(select(OAuthAccount).where(OAuthAccount.user_id == user_id, OAuthAccount.provider == "google"))).scalars().first()
    if not acct or (need_scope and FEATURE_SCOPES[need_scope] not in (acct.scopes or [])):
        return None
    if acct.expires_at and acct.expires_at - utcnow() > timedelta(seconds=60) and acct.access_token_enc:
        return decrypt_secret(settings, acct.access_token_enc)
    refresh = decrypt_secret(settings, acct.refresh_token_enc)
    if not refresh:
        return None
    tok = await oauth.refresh(refresh)
    await store_tokens(session, settings, user_id, acct.subject, tok)
    return tok["access_token"]


# ------------------------------------------------------------------ Calendar
class GoogleCalendar:
    def __init__(self, http: httpx.AsyncClient, token: str):
        self.http, self._h = http, {"Authorization": f"Bearer {token}"}

    async def list_events(self, time_min: datetime, time_max: datetime) -> list[dict]:
        r = await self.http.get(f"{CAL_API}/calendars/primary/events", headers=self._h, params={
            "timeMin": time_min.isoformat() + "Z", "timeMax": time_max.isoformat() + "Z", "singleEvents": "true", "orderBy": "startTime"})
        if r.status_code != 200:
            raise GoogleError(f"calendar list failed: {r.status_code}")
        return r.json().get("items", [])

    async def insert_event(self, ev: Event) -> str:
        body = {"summary": ev.title, "location": ev.location, "description": ev.notes,
                "start": {"dateTime": ev.start_at.isoformat() + "Z"}, "end": {"dateTime": ev.end_at.isoformat() + "Z"}}
        r = await self.http.post(f"{CAL_API}/calendars/primary/events", headers=self._h, json=body)
        if r.status_code not in (200, 201):
            raise GoogleError(f"calendar insert failed: {r.status_code}")
        return r.json()["id"]


def _g_time(t: dict) -> datetime | None:
    raw = t.get("dateTime") or t.get("date")
    if not raw:
        return None
    return to_naive_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))


async def sync_calendar(session: AsyncSession, user_id: str, cal: GoogleCalendar, days: int = 30) -> dict:
    """Pull Google events into local `events` (idempotent by external_id); push local-only ones up."""
    now = utcnow()
    imported = updated = pushed = 0
    for item in await cal.list_events(now - timedelta(days=1), now + timedelta(days=days)):
        start, end = _g_time(item.get("start", {})), _g_time(item.get("end", {}))
        if not start:
            continue
        existing = (await session.execute(select(Event).where(Event.user_id == user_id, Event.external_id == item["id"]))).scalars().first()
        fields = dict(title=item.get("summary", "(no title)"), start_at=start, end_at=end or start + timedelta(hours=1),
                      location=item.get("location", ""), notes=item.get("description", ""))
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.deleted_at = None
            updated += 1
        else:
            session.add(Event(user_id=user_id, source="google", external_id=item["id"], **fields))
            imported += 1
    local_only = (await session.execute(select(Event).where(Event.user_id == user_id, Event.source == "local", Event.external_id.is_(None),
                                                            Event.deleted_at.is_(None), Event.start_at >= now))).scalars().all()
    for ev in local_only:
        ev.external_id = await cal.insert_event(ev)
        pushed += 1
    await session.flush()
    return {"imported": imported, "updated": updated, "pushed": pushed}


# ------------------------------------------------------------------ Gmail
class GmailSender:
    name = "gmail"

    def __init__(self, http: httpx.AsyncClient, settings: Settings, oauth: GoogleOAuth):
        self.http, self.settings, self.oauth = http, settings, oauth

    async def send(self, session: AsyncSession, user: User, draft: EmailDraft) -> bool:
        if not draft.recipient or "@" not in draft.recipient:
            return False  # "client" is a name, not an address: leave queued rather than guess
        token = await access_token_for(session, self.settings, self.oauth, user.id, "gmail_send")
        if not token:
            return False
        msg = EmailMessage()
        msg["To"], msg["Subject"] = draft.recipient, draft.subject
        msg.set_content(draft.body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        r = await self.http.post(f"{GMAIL_API}/users/me/messages/send", headers={"Authorization": f"Bearer {token}"}, json={"raw": raw})
        return r.status_code == 200


async def recent_inbox(http: httpx.AsyncClient, token: str, n: int = 5) -> list[dict]:
    h = {"Authorization": f"Bearer {token}"}
    r = await http.get(f"{GMAIL_API}/users/me/messages", headers=h, params={"maxResults": n, "q": "in:inbox is:unread"})
    if r.status_code != 200:
        raise GoogleError(f"gmail list failed: {r.status_code}")
    out = []
    for m in r.json().get("messages", []):
        d = await http.get(f"{GMAIL_API}/users/me/messages/{m['id']}", headers=h,
                           params={"format": "metadata", "metadataHeaders": ["From", "Subject"]})
        if d.status_code != 200:
            continue
        data = d.json()
        hdr = {x["name"]: x["value"] for x in data.get("payload", {}).get("headers", [])}
        out.append({"id": m["id"], "from": hdr.get("From", ""), "subject": hdr.get("Subject", ""), "snippet": data.get("snippet", "")})
    return out
