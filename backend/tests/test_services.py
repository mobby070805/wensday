"""Pure service logic: recurrence, ranking, meeting heuristics, calendar conflicts, email templates, time helpers."""
from datetime import datetime, timedelta

import pytest

from app.core import timeutil
from app.db import Database
from app.models import Task, User
from app.services import calendar as cal
from app.services import meetings
from app.services.email import template_draft
from app.services.reminders import next_occurrence
from app.services.tasks import find_open_by_title, rank_tasks, create_task


# ------------------------------------------------------------------ reminder recurrence
D = datetime(2031, 1, 31, 9, 0)   # a Friday


@pytest.mark.parametrize("rec,expected", [
    ("daily", datetime(2031, 2, 1, 9, 0)),
    ("weekly", datetime(2031, 2, 7, 9, 0)),
    ("weekdays", datetime(2031, 2, 3, 9, 0)),          # Friday -> skips the weekend -> Monday
    ("monthly", datetime(2031, 2, 28, 9, 0)),          # Jan 31 -> clamped to Feb 28
    ("none", None),
    ("bogus", None),
])
def test_next_occurrence(rec, expected):
    assert next_occurrence(D, rec, after=D) == expected


def test_next_occurrence_catches_up_after_long_downtime_without_looping_forever():
    long_ago = datetime(2020, 1, 1, 9, 0)
    nxt = next_occurrence(long_ago, "daily", after=datetime(2031, 6, 15, 12, 0))
    assert nxt == datetime(2031, 6, 16, 9, 0)
    assert next_occurrence(datetime(1990, 1, 1), "daily", after=datetime(2031, 1, 1)) == datetime(2031, 1, 2)   # decades overdue: still instant


def test_monthly_recurrence_does_not_drift_after_a_short_month():
    d = datetime(2031, 1, 31, 8, 0)
    feb = next_occurrence(d, "monthly", after=d)
    assert feb == datetime(2031, 2, 28, 8, 0)
    assert next_occurrence(d, "monthly", after=feb) == datetime(2031, 3, 31, 8, 0)      # back to the 31st, not the 28th
    assert next_occurrence(d, "weekdays", after=datetime(2031, 2, 1, 9, 0)) == datetime(2031, 2, 3, 8, 0)   # Sat -> Mon, same clock time


def test_weekdays_recurrence_skips_weekends_after_downtime():
    fri = datetime(2031, 1, 3, 9, 0)                                                     # a Friday
    assert next_occurrence(fri, "weekdays", after=datetime(2031, 3, 1, 12, 0)).weekday() < 5


def test_monthly_recurrence_across_year_end_and_leap_day():
    assert next_occurrence(datetime(2030, 12, 15, 8, 0), "monthly", after=datetime(2030, 12, 15, 8, 0)) == datetime(2031, 1, 15, 8, 0)
    assert next_occurrence(datetime(2032, 1, 31, 8, 0), "monthly", after=datetime(2032, 1, 31, 8, 0)) == datetime(2032, 2, 29, 8, 0)


# ------------------------------------------------------------------ task ranking
NOW = datetime(2031, 1, 1, 12, 0)


def _t(title, prio, due=None):
    return Task(title=title, priority=prio, due_at=due, status="open")


def test_overdue_then_due_today_then_plain_priority_then_low():
    tasks = [_t("plain high", 4), _t("overdue medium", 2, NOW - timedelta(days=1)), _t("low", 1), _t("due today", 3, NOW + timedelta(hours=5))]
    assert [t.title for t in rank_tasks(tasks, NOW)] == ["overdue medium", "due today", "plain high", "low"]


def test_low_energy_keeps_only_what_matters_and_at_most_three():
    tasks = [_t("a", 4), _t("b", 4), _t("c", 3), _t("d", 3), _t("trivial", 1), _t("meh", 2), _t("due soon", 2, NOW + timedelta(hours=2))]
    keep = [t.title for t in rank_tasks(tasks, NOW, low_energy=True)]
    assert len(keep) == 3 and "trivial" not in keep and "meh" not in keep
    assert [t.title for t in rank_tasks([_t("meh", 2), _t("trivial", 1)], NOW, low_energy=True)] == []


async def test_task_title_matching_is_fuzzy_but_not_reckless():
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.create_all()
    async with db.session() as s:
        u = User(email="a@x.com")
        s.add(u)
        await s.flush()
        await create_task(s, u.id, "Buy milk and eggs")
        await create_task(s, u.id, "Call the plumber")
        assert (await find_open_by_title(s, u.id, "milk")).title == "Buy milk and eggs"
        assert (await find_open_by_title(s, u.id, "call plumber")).title == "Call the plumber"
        assert await find_open_by_title(s, u.id, "quantum physics homework") is None
        assert await find_open_by_title(s, u.id, "") is None
    await db.dispose()


# ------------------------------------------------------------------ calendar
async def test_back_to_back_events_do_not_conflict_but_overlaps_do():
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.create_all()
    async with db.session() as s:
        u = User(email="a@x.com")
        s.add(u)
        await s.flush()
        start = datetime(2031, 1, 1, 10, 0)
        _, none = await cal.create_event(s, u.id, "A", start, start + timedelta(hours=1))
        _, adjacent = await cal.create_event(s, u.id, "B", start + timedelta(hours=1), start + timedelta(hours=2))
        _, overlap = await cal.create_event(s, u.id, "C", start + timedelta(minutes=30), start + timedelta(hours=1, minutes=30))
        assert none == [] and adjacent == [] and {e.title for e in overlap} == {"A", "B"}
        e = await cal.find_by_title(s, u.id, "B", start - timedelta(days=1))
        moved = await cal.reschedule(s, e, start + timedelta(days=1))
        assert moved.end_at - moved.start_at == timedelta(hours=1)               # duration preserved
    await db.dispose()


# ------------------------------------------------------------------ meetings & email templates
def test_meeting_heuristics_understand_english_tanglish_and_tamil_cues():
    t = ("Ravi: We decided to launch on the 5th.\n"
         "Priya: I will send the deck by Friday.\n"
         "Ravi: Client ku quotation anuppanum.\n"
         "Priya: Budget mudivu panniyachu.\n"
         "Kumar: வேலை முடிக்க வேண்டும்.\n"
         "Ravi: Nice weather today.")
    r = meetings.heuristic(t)
    assert len(r["decisions"]) == 2 and any("launch" in d for d in r["decisions"])
    owners = {a["owner"]: a["text"] for a in r["action_items"]}
    assert set(owners) == {"Priya", "Ravi", "Kumar"} and "deck" in owners["Priya"] and "weather" not in " ".join(owners.values())
    assert r["summary"]


def test_email_template_language_follows_the_message():
    subj, body = template_draft("ravi.kumar@acme.com", "quotation ready", "Madesh")
    assert subj == "Quotation ready" and body.startswith("Hi Ravi Kumar,") and body.endswith("Regards,\nMadesh")
    assert template_draft("", "நாளை கூட்டம் உள்ளது", "Madesh")[1].startswith("வணக்கம்")
    assert len(template_draft("", "x" * 200, "M")[0]) <= 60


# ------------------------------------------------------------------ time helpers
def test_timezone_round_trip_and_wire_format():
    local = datetime(2031, 1, 1, 9, 0)
    utc = timeutil.local_to_utc(local, "Asia/Kolkata")
    assert utc == datetime(2031, 1, 1, 3, 30) and timeutil.utc_to_local(utc, "Asia/Kolkata") == local
    assert timeutil.iso_z(utc) == "2031-01-01T03:30:00Z" and timeutil.iso_z(None) is None
    assert timeutil.local_to_utc(local, "America/New_York") == datetime(2031, 1, 1, 14, 0)


# ------------------------------------------------------------------ multi-worker safety
async def test_only_one_of_two_racing_workers_claims_a_due_reminder():
    from app.core.timeutil import utcnow
    from app.models import Reminder
    from app.services.reminders import claim
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.create_all()
    async with db.session() as setup:
        u = User(email="a@x.com")
        setup.add(u)
        await setup.flush()
        rem = Reminder(user_id=u.id, title="x", due_at=datetime(2020, 1, 1), recurrence="daily")
        setup.add(rem)
        await setup.commit()
        rid = rem.id
    now = utcnow()
    async with db.session() as worker_a, db.session() as worker_b:
        seen_by_a, seen_by_b = await worker_a.get(Reminder, rid), await worker_b.get(Reminder, rid)   # both read "pending"
        assert [await claim(worker_a, seen_by_a, now), await claim(worker_b, seen_by_b, now)] == [True, False]
        await worker_a.commit()
    async with db.session() as check:
        r = await check.get(Reminder, rid)
        assert r.due_at > now and r.status == "pending"          # a daily reminder advanced exactly once
    await db.dispose()
