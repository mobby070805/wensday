"""REST API: auth & token security, tenant isolation, CRUD, sync, realtime socket, plugins, workflows, analytics."""
import httpx
import pytest
from starlette.websockets import WebSocketDisconnect

from app.services.reminders import fire_due
from .conftest import API, Person, running


# ------------------------------------------------------------------ ops
def test_health_ready_and_metrics(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz").json()
    assert ready["status"] == "ready" and ready["llm_remote"] is False
    m = client.get("/metrics").text
    assert "wensday_http_requests_total" in m and "wensday_http_request_seconds_count" in m


def test_request_id_header_is_set_and_echoed(client):
    assert len(client.get("/healthz").headers["x-request-id"]) >= 8
    assert client.get("/healthz", headers={"x-request-id": "abc123"}).headers["x-request-id"] == "abc123"


def test_security_headers_are_present_on_every_response(client):
    h = client.get("/healthz").headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in h  # never sent over plain HTTP (the TestClient is http://)


def test_hsts_is_sent_only_when_the_request_arrived_over_tls(client):
    forwarded_https = client.get("/healthz", headers={"x-forwarded-proto": "https"})
    assert "max-age=" in forwarded_https.headers["strict-transport-security"]
    assert "strict-transport-security" not in client.get("/healthz").headers


# ------------------------------------------------------------------ auth
def test_register_login_me(client):
    p = Person(client, "Madesh@Example.com", "Madesh")
    me = p.get("/auth/me").json()
    assert me["email"] == "madesh@example.com" and me["timezone"] == "Asia/Kolkata" and me["language"] == "auto"
    ok = client.post(f"{API}/auth/login", json={"email": "MADESH@example.com", "password": "password123"})
    assert ok.status_code == 200 and ok.json()["token_type"] == "bearer"


def test_register_validation_and_duplicates(client):
    Person(client, "a@x.com", "A")
    assert client.post(f"{API}/auth/register", json={"email": "a@x.com", "password": "password123"}).status_code == 409
    assert client.post(f"{API}/auth/register", json={"email": "b@x.com", "password": "short"}).status_code == 422
    assert client.post(f"{API}/auth/register", json={"email": "not-an-email", "password": "password123"}).status_code == 422


def test_login_does_not_reveal_whether_the_account_exists(client):
    Person(client, "a@x.com", "A")
    wrong_pw = client.post(f"{API}/auth/login", json={"email": "a@x.com", "password": "nope-nope-nope"})
    no_user = client.post(f"{API}/auth/login", json={"email": "ghost@x.com", "password": "nope-nope-nope"})
    assert wrong_pw.status_code == no_user.status_code == 401 and wrong_pw.json() == no_user.json()


def test_refresh_rotates_and_replay_kills_every_session(client):
    p = Person(client, "a@x.com", "A")
    old = p.tokens["refresh_token"]
    fresh = client.post(f"{API}/auth/refresh", json={"refresh_token": old})
    assert fresh.status_code == 200 and fresh.json()["refresh_token"] != old
    replay = client.post(f"{API}/auth/refresh", json={"refresh_token": old})
    assert replay.status_code == 401 and "reuse" in replay.json()["detail"]
    # the replay is treated as theft: the legitimately rotated token is now dead too
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": fresh.json()["refresh_token"]}).status_code == 401


def test_logout_revokes_the_refresh_token(client):
    p = Person(client, "a@x.com", "A")
    assert client.post(f"{API}/auth/logout", json={"refresh_token": p.tokens["refresh_token"]}).status_code == 204
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": p.tokens["refresh_token"]}).status_code == 401


def test_token_type_confusion_and_garbage_are_rejected(client):
    p = Person(client, "a@x.com", "A")
    as_bearer = {"Authorization": f"Bearer {p.tokens['refresh_token']}"}
    assert client.get(f"{API}/auth/me", headers=as_bearer).status_code == 401           # refresh token used as access token
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": p.tokens["access_token"]}).status_code == 401  # and vice versa
    assert client.get(f"{API}/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.get(f"{API}/auth/me").status_code == 401


@pytest.mark.parametrize("path", ["/tasks", "/reminders", "/events", "/notes", "/goals", "/memories", "/documents", "/sync", "/analytics/dashboard",
                                  "/plugins", "/workflows", "/conversations", "/preferences", "/devices", "/voice/config", "/export"])
def test_every_endpoint_requires_authentication(client, path):
    assert client.get(API + path).status_code == 401


def test_update_profile_validates_timezone_and_language(madesh):
    assert madesh.patch("/auth/me", {"timezone": "Not/AZone"}).status_code == 422
    assert madesh.patch("/auth/me", {"language": "klingon"}).status_code == 422
    ok = madesh.patch("/auth/me", {"timezone": "America/New_York", "language": "ta", "name": "Mads"}).json()
    assert ok["timezone"] == "America/New_York" and ok["language"] == "ta"


def test_rate_limit_returns_429():
    with running(rate_limit_per_minute=3) as c:
        codes = [c.post(f"{API}/auth/login", json={"email": "a@x.com", "password": "x"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


# ------------------------------------------------------------------ tenant isolation
def test_users_can_never_touch_each_others_data(client):
    a, b = Person(client, "a@x.com", "A"), Person(client, "b@x.com", "B")
    ids = {
        "tasks": a.post("/tasks", {"title": "secret task"}).json()["id"],
        "reminders": a.post("/reminders", {"title": "secret", "due_at": "2031-01-01T09:00:00Z"}).json()["id"],
        "events": a.post("/events", {"title": "secret", "start_at": "2031-01-01T09:00:00Z"}).json()["id"],
        "notes": a.post("/notes", {"title": "secret", "body": "s"}).json()["id"],
        "goals": a.post("/goals", {"title": "secret"}).json()["id"],
    }
    for kind, rid in ids.items():
        assert b.get(f"/{kind}/{rid}").status_code == 404, kind
        assert b.patch(f"/{kind}/{rid}", {"title": "hacked"}).status_code == 404, kind
        assert b.delete(f"/{kind}/{rid}").status_code == 404, kind
        assert b.get(f"/{kind}").json() == [], kind
        assert a.get(f"/{kind}/{rid}").status_code == 200, kind          # untouched
    mem = a.post("/memories", {"text": "A's private fact"}).json()["id"]
    assert b.delete(f"/memories/{mem}").status_code == 404
    assert b.get("/memories/search", params={"q": "private fact"}).json() == []
    doc = a.post("/documents", {"title": "d", "text": "Confidential quarterly numbers are here."}).json()["id"]
    assert b.delete(f"/documents/{doc}").status_code == 404 and b.get("/documents").json() == []
    assert b.post("/knowledge/ask", {"question": "confidential quarterly numbers"}).json()["answer"] is None
    a.say("hello")
    assert b.get(f"/conversations/{a.cid}/messages").status_code == 404


# ------------------------------------------------------------------ CRUD
def test_task_lifecycle_and_filters(madesh):
    t = madesh.post("/tasks", {"title": "Write report", "priority": 3, "tags": ["work"], "due_at": "2031-05-01T10:00:00+05:30"})
    assert t.status_code == 201 and t.json()["due_at"] == "2031-05-01T04:30:00Z"
    tid = t.json()["id"]
    assert [x["id"] for x in madesh.get("/tasks", params={"status": "open"}).json()] == [tid]
    done = madesh.patch(f"/tasks/{tid}", {"status": "done"}).json()
    assert done["status"] == "done" and done["completed_at"]
    assert madesh.get("/tasks", params={"status": "open"}).json() == []
    assert madesh.patch(f"/tasks/{tid}", {"status": "open"}).json()["completed_at"] is None
    assert madesh.delete(f"/tasks/{tid}").status_code == 204
    assert madesh.get(f"/tasks/{tid}").status_code == 404 and madesh.get("/tasks").json() == []


@pytest.mark.parametrize("body", [{"title": ""}, {"title": "x", "priority": 9}, {"title": "x", "priority": 0}, {}, {"title": "x" * 301}])
def test_task_validation(madesh, body):
    assert madesh.post("/tasks", body).status_code == 422


def test_reminder_times_round_trip_in_utc(madesh):
    r = madesh.post("/reminders", {"title": "Standup", "due_at": "2031-01-01T09:00:00+05:30", "recurrence": "daily", "style": "tg"}).json()
    assert r["due_at"] == "2031-01-01T03:30:00Z" and r["recurrence"] == "daily" and r["status"] == "pending"
    assert madesh.post("/reminders", {"title": "x", "due_at": "2031-01-01T09:00:00Z", "recurrence": "hourly"}).status_code == 422


def test_event_defaults_and_validation(madesh):
    e = madesh.post("/events", {"title": "Sync", "start_at": "2031-01-01T09:00:00Z"}).json()
    assert e["end_at"] == "2031-01-01T10:00:00Z" and e["source"] == "local"
    bad = madesh.post("/events", {"title": "Bad", "start_at": "2031-01-01T09:00:00Z", "end_at": "2031-01-01T08:00:00Z"})
    assert bad.status_code == 422


def test_goal_progress_from_milestones_then_manual_override(madesh):
    g = madesh.post("/goals", {"title": "Learn Tamil typing", "milestones": [{"title": "Home row"}, {"title": "Speed 30wpm"}]}).json()
    assert g["progress"] == 0
    after = madesh.post(f"/goals/{g['id']}/milestones/{g['milestones'][0]['id']}/toggle").json()
    assert after["progress"] == 50
    assert madesh.patch(f"/goals/{g['id']}", {"manual_progress": 80}).json()["progress"] == 80
    assert madesh.patch(f"/goals/{g['id']}", {"manual_progress": 101}).status_code == 422


def test_goal_progress_from_linked_tasks(madesh):
    g = madesh.post("/goals", {"title": "Ship v1"}).json()
    t1 = madesh.post("/tasks", {"title": "a", "goal_id": g["id"]}).json()["id"]
    madesh.post("/tasks", {"title": "b", "goal_id": g["id"]})
    madesh.patch(f"/tasks/{t1}", {"status": "done"})
    assert madesh.get(f"/goals/{g['id']}").json()["progress"] == 50


# ------------------------------------------------------------------ sync
def test_sync_is_incremental_and_reports_deletions_as_tombstones(madesh):
    t1 = madesh.post("/tasks", {"title": "one"}).json()["id"]
    first = madesh.get("/sync").json()
    assert [t["id"] for t in first["changes"]["tasks"]] == [t1]
    cursor = first["server_time"]
    assert all(v == [] for v in madesh.get("/sync", params={"since": cursor}).json()["changes"].values())

    t2 = madesh.post("/tasks", {"title": "two"}).json()["id"]
    madesh.delete(f"/tasks/{t1}")
    changes = madesh.get("/sync", params={"since": cursor}).json()["changes"]["tasks"]
    by_id = {c["id"]: c for c in changes}
    assert by_id[t1] == {"id": t1, "deleted": True} and by_id[t2]["title"] == "two"


# ------------------------------------------------------------------ realtime socket
def test_socket_rejects_a_bad_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"{API}/ws?token=nope") as ws:
            ws.receive_json()


def test_socket_pushes_changes_made_from_another_device(client, madesh):
    with client.websocket_connect(f"{API}/ws?token={madesh.tokens['access_token']}") as ws:
        assert ws.receive_json() == {"type": "ready"}
        madesh.post("/tasks", {"title": "from phone"})                      # a second device writes
        evt = ws.receive_json()
        assert evt["type"] == "sync" and evt["kind"] == "tasks" and evt["op"] == "create"
        madesh.say("add task buy milk")                                     # voice command also notifies
        assert ws.receive_json() == {"type": "sync", "kind": "all", "op": "chat"}


def test_socket_only_delivers_your_own_events(client):
    a, b = Person(client, "a@x.com", "A"), Person(client, "b@x.com", "B")
    with client.websocket_connect(f"{API}/ws?token={a.tokens['access_token']}") as ws:
        ws.receive_json()
        b.post("/tasks", {"title": "B's task"})
        a.post("/tasks", {"title": "A's task"})
        evt = ws.receive_json()
        assert evt["kind"] == "tasks" and evt["id"] == a.get("/tasks").json()[0]["id"]


def _fire(app):
    async def go():
        async with app.state.db.session() as s:
            n = await fire_due(s, app.state.hub)
            await s.commit()
            return n
    return go


def test_due_reminder_is_pushed_in_the_users_language_and_fired_once(client, madesh):
    # created *before* the socket subscribes, so the only event the socket can see is the due-notification
    madesh.post("/reminders", {"title": "Pay rent", "due_at": "2020-01-01T00:00:00Z", "style": "tg"})
    with client.websocket_connect(f"{API}/ws?token={madesh.tokens['access_token']}") as ws:
        assert ws.receive_json() == {"type": "ready"}
        assert client.portal.call(_fire(client.app)) == 1
        evt = ws.receive_json()
        assert evt["type"] == "reminder.due" and evt["text"] == "Reminder, Madesh: Pay rent" and evt["style"] == "tg"
    assert client.portal.call(_fire(client.app)) == 0                          # idempotent: nothing left to fire
    assert madesh.get("/reminders", params={"status": "fired"}).json()[0]["fired_at"]


# ------------------------------------------------------------------ preferences / devices / privacy
def test_preferences_and_devices(madesh):
    assert madesh.put("/preferences/wake_word", {"value": "Wensday"}).json() == {"key": "wake_word", "value": "Wensday"}
    assert madesh.get("/preferences").json() == {"wake_word": "Wensday"}
    d1 = madesh.post("/devices", {"name": "Pixel", "platform": "android", "push_token": "tok"}).json()["id"]
    d2 = madesh.post("/devices", {"name": "Pixel 8", "platform": "android", "push_token": "tok"}).json()["id"]
    assert d1 == d2                                                             # same push token = same device
    assert madesh.get("/devices").json()[0]["name"] == "Pixel 8"
    assert madesh.delete(f"/devices/{d1}").status_code == 204 and madesh.get("/devices").json() == []
    assert madesh.post("/devices", {"name": "x", "platform": "toaster"}).status_code == 422


def test_export_and_forget_everything(madesh):
    madesh.say("my name is Madesh")
    madesh.post("/memories", {"text": "Prefers filter coffee", "importance": 0.8})
    exported = madesh.get("/export").json()
    assert exported["user"]["email"] == "madesh@example.com" and exported["preferences"]["name"] == "Madesh"
    assert any("filter coffee" in m["text"] for m in exported["memories"])
    assert madesh.delete("/memories").json()["forgotten"] >= 2
    assert madesh.get("/memories").json() == [] and madesh.get("/export").json()["memories"] == []


def test_low_importance_episodic_memory_is_rejected(madesh):
    assert madesh.post("/memories", {"text": "trivia", "kind": "episodic", "importance": 0.1}).status_code == 422


# ------------------------------------------------------------------ documents / knowledge / meetings
def test_document_ingest_ask_with_citations_and_delete(madesh):
    doc = madesh.post("/documents", {"title": "Vendor terms", "text":
                      "Payment is due within 30 days of invoice. Late payments attract 2% monthly interest. "
                      "Delivery happens within 7 working days. Warranty covers manufacturing defects for one year."}).json()
    assert doc["summary"]
    ans = madesh.post("/knowledge/ask", {"question": "what is the late payment interest?"}).json()
    assert "2% monthly interest" in ans["answer"] and ans["citations"][0]["source"] == "document"
    assert madesh.delete(f"/documents/{doc['id']}").status_code == 204
    assert madesh.post("/knowledge/ask", {"question": "late payment interest"}).json()["answer"] is None


def test_notes_are_searchable_by_voice_and_knowledge(madesh):
    madesh.post("/notes", {"title": "Trip", "body": "Book train tickets to Madurai for Pongal"})
    assert madesh.post("/knowledge/ask", {"question": "madurai train tickets"}).json()["citations"][0]["source"] == "note"


def test_meeting_summary_extracts_decisions_and_action_items_in_tanglish(madesh):
    transcript = ("Ravi: Quotation ready aagiduchu. We decided to send it on Friday. "
                  "Priya: I will share the revised pricing sheet by tomorrow. "
                  "Ravi: Client ku follow up mail anuppanum. Budget mudivu panniyachu, 5 lakh approve.")
    r = madesh.post("/meetings/summarize", {"title": "Quote sync", "transcript": transcript, "create_tasks": True}).json()
    assert any("Friday" in d for d in r["decisions"])
    owners = {a["owner"] for a in r["action_items"]}
    assert {"Priya", "Ravi"} <= owners and len(r["task_ids"]) == len(r["action_items"]) >= 2
    assert madesh.get("/notes", params={"kind": "meeting"}).json()[0]["title"] == "Quote sync"
    assert any("share the revised pricing" in t["title"] for t in madesh.get("/tasks").json())


# ------------------------------------------------------------------ plugins: permission model
def _wf(madesh, tool, args):
    wid = madesh.post("/workflows", {"name": f"t-{tool}", "steps": [{"tool": tool, "args": args}]}).json()["id"]
    return madesh.post(f"/workflows/{wid}/run").json()


def test_plugins_are_off_until_enabled_and_scoped(madesh):
    listing = {p["name"]: p for p in madesh.get("/plugins").json()}
    assert {"weather", "browser"} <= set(listing) and not listing["browser"]["enabled"]

    blocked = _wf(madesh, "open_url", {"url": "https://example.com"})
    assert blocked["status"] == "failed" and "not enabled" in blocked["log"][0]["error"]

    madesh.post("/plugins/browser/enable", {})
    ok = _wf(madesh, "open_url", {"url": "example.com"})
    assert ok["status"] == "ok" and ok["log"][0]["data"] == {"action": "open_url", "url": "https://example.com"}

    assert _wf(madesh, "open_url", {"url": "javascript:alert(1)"})["status"] == "failed"     # unsafe scheme refused

    madesh.post("/plugins/browser/enable", {"scopes": []})                                    # revoke the scope
    assert _wf(madesh, "open_url", {"url": "https://example.com"})["status"] == "failed"
    madesh.post("/plugins/browser/disable")
    assert _wf(madesh, "web_search", {"query": "x"})["status"] == "failed"


def test_plugin_endpoints_reject_unknown_plugins(madesh):
    assert madesh.post("/plugins/nope/enable", {}).status_code == 404
    assert madesh.post("/plugins/nope/disable").status_code == 404


def _weather_handler(request: httpx.Request) -> httpx.Response:
    if "geocoding" in request.url.host:
        return httpx.Response(200, json={"results": [{"name": "Chennai", "latitude": 13.08, "longitude": 80.27}]})
    return httpx.Response(200, json={"current": {"temperature_2m": 31.4, "weather_code": 3}})


def test_weather_plugin_answers_in_the_users_language_style():
    http = httpx.AsyncClient(transport=httpx.MockTransport(_weather_handler))
    with running(http=http) as c:
        p = Person(c, "a@x.com", "Madesh")
        assert p.say("weather enna")["reply"].startswith("Weather plugin innum enable aagala")
        p.post("/plugins/weather/enable", {"config": {"city": "Chennai"}})
        out = p.say("weather enna")
        assert out["reply"] == "Chennai la ippo 31°C, mugam moottam." and out["intent"] == "weather"
        assert p.say("what's the weather")["reply"] == "It's 31°C and overcast in Chennai."


# ------------------------------------------------------------------ workflows
def test_workflow_triggered_by_a_spoken_phrase_in_any_language(madesh):
    wf = madesh.post("/workflows", {"name": "Morning", "trigger": {"type": "phrase", "phrases": ["good morning routine", "kaalai routine"]},
                                    "steps": [{"tool": "create_task", "args": {"title": "Review inbox for {{user.name}}"}},
                                              {"tool": "plan_day", "args": {}}]})
    assert wf.status_code == 201
    out = madesh.say("Wensday, kalai routine start pannu")          # note the different spelling: skeleton-matched
    assert out["intent"] == "workflow"
    assert out["reply"] == 'Done — "Morning" workflow run panniten (2 steps).'.replace("Done —", "Done, Madesh —")
    assert [t["title"] for t in madesh.get("/tasks").json()] == ["Review inbox for Madesh"]


def test_workflows_cannot_contain_unknown_or_confirmation_gated_tools(madesh):
    assert madesh.post("/workflows", {"name": "x", "steps": [{"tool": "rm_rf"}]}).status_code == 422
    assert madesh.post("/workflows", {"name": "x", "steps": [{"tool": "send_email", "args": {"draft_id": "1"}}]}).status_code == 422


def test_workflow_stops_at_the_first_failing_step(madesh):
    wid = madesh.post("/workflows", {"name": "w", "steps": [
        {"tool": "complete_task", "args": {"query": "nonexistent"}}, {"tool": "create_task", "args": {"title": "never"}}]}).json()["id"]
    run = madesh.post(f"/workflows/{wid}/run").json()
    assert run["status"] == "failed" and len(run["log"]) == 1 and madesh.get("/tasks").json() == []


# ------------------------------------------------------------------ analytics
def test_dashboard_and_weekly_review(madesh):
    for title in ("a", "b", "c"):
        tid = madesh.post("/tasks", {"title": title}).json()["id"]
        if title != "c":
            madesh.patch(f"/tasks/{tid}", {"status": "done"})
    madesh.say("hello")
    madesh.say("vanakkam")
    d = madesh.get("/analytics/dashboard").json()
    assert d["tasks"]["open"] == 1 and d["tasks"]["completed_total"] == 2 and len(d["tasks"]["completed_series"]) == 14
    assert d["streak_days"] == 1 and d["language_usage"] == {"en": 1, "tanglish": 1}
    review = madesh.get("/analytics/weekly-review").json()
    assert review["completed"] == 2 and review["open"] == 1 and review["headline"]
