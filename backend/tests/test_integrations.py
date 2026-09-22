"""Google OAuth, Calendar sync, Gmail send/inbox — all against a mocked Google."""
import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx

from app.integrations.google import FEATURE_SCOPES
from app.models import OAuthAccount
from app.security import decrypt_secret
from sqlalchemy import select
from .conftest import API, Person, running

CAL = FEATURE_SCOPES["calendar"]
SEND = FEATURE_SCOPES["gmail_send"]
READ = FEATURE_SCOPES["gmail_read"]


class FakeGoogle:
    """Just enough of Google's token, userinfo, Calendar and Gmail endpoints; records every call."""

    def __init__(self, scope="openid email profile", email_verified=True):
        self.calls, self.scope, self.email_verified = [], scope, email_verified
        self.events = [
            {"id": "g1", "summary": "Board meeting", "start": {"dateTime": "2031-03-01T10:00:00+05:30"}, "end": {"dateTime": "2031-03-01T11:00:00+05:30"}},
            {"id": "g2", "summary": "Pongal", "start": {"date": "2031-03-02"}, "end": {"date": "2031-03-03"}},
        ]
        self.inserted, self.sent, self.expires_in = [], [], 3600

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        self.calls.append((req.method, url))
        if url.endswith("/token"):
            form = parse_qs(req.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                return httpx.Response(200, json={"access_token": "AT-1", "refresh_token": "RT-1", "expires_in": self.expires_in, "scope": self.scope})
            return httpx.Response(200, json={"access_token": "AT-2", "expires_in": 3600, "scope": self.scope})
        if "openidconnect" in url:
            return httpx.Response(200, json={"sub": "g-123", "email": "Madesh@Gmail.com", "email_verified": self.email_verified, "name": "Madesh K"})
        if "/calendars/primary/events" in url and req.method == "GET":
            return httpx.Response(200, json={"items": self.events})
        if "/calendars/primary/events" in url and req.method == "POST":
            self.inserted.append(json.loads(req.content))
            return httpx.Response(200, json={"id": f"new-{len(self.inserted)}"})
        if url.endswith("/messages/send"):
            self.sent.append(json.loads(req.content))
            return httpx.Response(200, json={"id": "m1"})
        if "/users/me/messages/" in url:
            return httpx.Response(200, json={"snippet": "Please confirm the PO", "payload": {"headers": [
                {"name": "From", "value": "vendor@acme.com"}, {"name": "Subject", "value": "PO 42"}]}})
        if url.endswith("/users/me/messages") or "/users/me/messages?" in url:
            return httpx.Response(200, json={"messages": [{"id": "m9"}]})
        return httpx.Response(404)


def google_app(fake, **kw):
    return running(google_client_id="cid", google_client_secret="secret", http=httpx.AsyncClient(transport=httpx.MockTransport(fake)), **kw)


def consent_state(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


def complete_login(c, fake, features="", headers=None):
    login = c.get(f"{API}/auth/google/login", params={"features": features}, headers=headers or {})
    assert login.status_code == 200, login.text
    return login.json()["url"], c.get(f"{API}/auth/google/callback", params={"code": "abc", "state": consent_state(login.json()["url"])}, follow_redirects=False)


def token_from_redirect(resp):
    return parse_qs(urlparse(resp.headers["location"]).fragment)["access_token"][0]


# ------------------------------------------------------------------ OAuth
def test_google_is_501_when_not_configured(client):
    assert client.get(f"{API}/auth/google/login").status_code == 501
    assert client.get(f"{API}/auth/google/callback", params={"code": "x", "state": "y"}).status_code == 501


def test_login_url_requests_only_the_scopes_asked_for():
    with google_app(FakeGoogle()) as c:
        url, _ = complete_login(c, None, "calendar,gmail_send")
        q = parse_qs(urlparse(url).query)
        assert q["client_id"] == ["cid"] and q["access_type"] == ["offline"]
        scopes = set(q["scope"][0].split())
        assert scopes == {"openid", "email", "profile", CAL, SEND}
        plain = c.get(f"{API}/auth/google/login").json()["url"]
        assert set(parse_qs(urlparse(plain).query)["scope"][0].split()) == {"openid", "email", "profile"}     # least privilege by default


def test_callback_creates_the_account_and_hands_back_tokens_via_fragment():
    with google_app(FakeGoogle()) as c:
        _, resp = complete_login(c, None)
        assert resp.status_code in (302, 307) and resp.headers["location"].startswith("http://localhost:3000/auth/callback#")
        me = c.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token_from_redirect(resp)}"}).json()
        assert me["email"] == "madesh@gmail.com" and me["name"] == "Madesh K"


def test_signing_in_again_reuses_the_same_user():
    with google_app(FakeGoogle()) as c:
        ids = set()
        for _ in range(2):
            _, resp = complete_login(c, None)
            ids.add(c.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token_from_redirect(resp)}"}).json()["id"])
        assert len(ids) == 1


def test_forged_or_expired_state_and_unverified_email_are_rejected():
    with google_app(FakeGoogle()) as c:
        assert c.get(f"{API}/auth/google/callback", params={"code": "x", "state": "forged"}).status_code == 400
    with google_app(FakeGoogle(email_verified=False)) as c:
        login = c.get(f"{API}/auth/google/login").json()["url"]
        r = c.get(f"{API}/auth/google/callback", params={"code": "x", "state": consent_state(login)}, follow_redirects=False)
        assert r.status_code == 400 and "not verified" in r.json()["detail"]


def test_token_exchange_failure_is_a_clean_502():
    def failing(req):
        return httpx.Response(400) if str(req.url).endswith("/token") else httpx.Response(404)

    with google_app(failing) as c:
        login = c.get(f"{API}/auth/google/login").json()["url"]
        assert c.get(f"{API}/auth/google/callback", params={"code": "x", "state": consent_state(login)}).status_code == 502


def test_connecting_google_to_a_signed_in_account_links_instead_of_creating_a_new_user():
    fake = FakeGoogle(scope=f"openid email profile {CAL} {SEND}")
    with google_app(fake) as c:
        me = Person(c, "work@corp.com", "Madesh")
        _, resp = complete_login(c, fake, "calendar,gmail_send", headers=me.h)
        assert c.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token_from_redirect(resp)}"}).json()["id"] == me.id
        status = me.get("/integrations/status").json()["google"]
        assert status == {"configured": True, "connected": True, "calendar": True, "gmail_send": True, "gmail_read": False}


def test_oauth_tokens_are_encrypted_at_rest():
    fake = FakeGoogle(scope=f"openid email profile {CAL}")
    with google_app(fake) as c:
        me = Person(c, "a@x.com", "A")
        complete_login(c, fake, "calendar", headers=me.h)

        async def read():
            async with c.app.state.db.session() as s:
                acct = (await s.execute(select(OAuthAccount))).scalars().one()
                return acct.access_token_enc, acct.refresh_token_enc, decrypt_secret(c.app.state.settings, acct.access_token_enc)

        access_enc, refresh_enc, plain = c.portal.call(read)
        assert "AT-1" not in access_enc and "RT-1" not in refresh_enc and plain == "AT-1"


# ------------------------------------------------------------------ Calendar
def test_calendar_sync_imports_dedupes_and_pushes_local_events():
    fake = FakeGoogle(scope=f"openid email profile {CAL}")
    with google_app(fake) as c:
        me = Person(c, "a@x.com", "A")
        complete_login(c, fake, "calendar", headers=me.h)
        me.post("/events", {"title": "Local only", "start_at": "2031-03-05T09:00:00Z"})

        first = me.post("/integrations/google/calendar/sync").json()
        assert first == {"imported": 2, "updated": 0, "pushed": 1}
        second = me.post("/integrations/google/calendar/sync").json()
        assert second == {"imported": 0, "updated": 2, "pushed": 0}            # idempotent by external_id; nothing pushed twice
        assert len(fake.inserted) == 1 and fake.inserted[0]["summary"] == "Local only"

        events = {e["title"]: e for e in me.get("/events").json()}
        assert events["Board meeting"]["start_at"] == "2031-03-01T04:30:00Z" and events["Board meeting"]["source"] == "google"
        assert events["Pongal"]["start_at"] == "2031-03-02T00:00:00Z"          # all-day events survive


def test_calendar_sync_requires_the_calendar_scope():
    fake = FakeGoogle()
    with google_app(fake) as c:
        me = Person(c, "a@x.com", "A")
        assert me.post("/integrations/google/calendar/sync").status_code == 409          # nothing connected
        complete_login(c, fake, "", headers=me.h)                                        # connected, but no calendar scope
        assert me.post("/integrations/google/calendar/sync").status_code == 409


def test_expired_access_token_is_refreshed_transparently():
    fake = FakeGoogle(scope=f"openid email profile {CAL}")
    fake.expires_in = 1                                                                   # token is already "expired" (<60s left)
    with google_app(fake) as c:
        me = Person(c, "a@x.com", "A")
        complete_login(c, fake, "calendar", headers=me.h)
        assert me.post("/integrations/google/calendar/sync").status_code == 200
        grants = [m for m, u in fake.calls if u.endswith("/token")]
        assert len(grants) == 2                                                           # code exchange + refresh


# ------------------------------------------------------------------ Gmail
def _raw_message(fake):
    import email
    return email.message_from_bytes(base64.urlsafe_b64decode(fake.sent[-1]["raw"]))


def test_confirmed_email_is_really_sent_through_gmail():
    fake = FakeGoogle(scope=f"openid email profile {SEND}")
    with google_app(fake) as c:
        me = Person(c, "a@x.com", "Madesh")
        complete_login(c, fake, "gmail_send", headers=me.h)
        me.say("send a mail to ravi@acme.com and mention quotation ready")
        assert fake.sent == []                                                            # drafted, NOT sent
        out = me.say("send it directly")
        assert out["reply"].startswith("Sent, Madesh") and len(fake.sent) == 1
        msg = _raw_message(fake)
        assert msg["To"] == "ravi@acme.com" and msg["Subject"] == "Quotation ready" and "Quotation ready." in msg.get_payload(decode=True).decode()


def test_a_name_instead_of_an_address_is_queued_not_guessed():
    fake = FakeGoogle(scope=f"openid email profile {SEND}")
    with google_app(fake) as c:
        me = Person(c, "a@x.com", "Madesh")
        complete_login(c, fake, "gmail_send", headers=me.h)
        me.say("send a mail to client and mention quotation ready")
        out = me.say("send it directly")
        assert fake.sent == [] and out["data"]["status"] == "queued" and "saved the draft" in out["reply"]


def test_gmail_inbox_summary_lists_unread_mail():
    fake = FakeGoogle(scope=f"openid email profile {READ}")
    with google_app(fake) as c:
        me = Person(c, "a@x.com", "Madesh")
        assert me.get("/integrations/gmail/inbox").status_code == 409
        complete_login(c, fake, "gmail_read", headers=me.h)
        r = me.get("/integrations/gmail/inbox").json()
        assert r["messages"][0]["subject"] == "PO 42" and "PO 42" in r["summary"] and "vendor@acme.com" in r["summary"]
