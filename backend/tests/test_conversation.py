"""End-to-end conversation behaviour through the real HTTP API: the brief's own examples,
language mirroring, multi-turn slot filling, and the email confirmation gate."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.email import NullSender
from .conftest import has_tamil, running, tamil_ratio


# ------------------------------------------------------------ the brief's examples
def test_brief_example_reminder_in_tanglish(madesh):
    out = madesh.say("Wensday, nalaiku 9 mani meeting remind pannu.")
    assert out["reply"] == "Sure Madesh, nalaiku morning 9:00 AM-ku meeting reminder set panniten."
    assert out["intent"] == "reminder_create" and out["style"] == "tg" and out["tier"] == "rules"

    reminders = madesh.get("/reminders").json()
    assert len(reminders) == 1 and reminders[0]["title"].lower() == "meeting"
    tomorrow_9_ist = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    assert reminders[0]["due_at"] == tomorrow_9_ist.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_brief_example_email_asks_review_or_send(madesh):
    out = madesh.say("Wensday, send a mail to client and mention quotation ready.")
    assert out["intent"] == "email_draft" and out["style"] == "en"
    assert out["data"]["recipient"] == "client" and "uotation ready" in out["data"]["body"]
    # the reply offers the choice in the user's language style: English here
    assert "review" in out["reply"].lower() and "send" in out["reply"].lower()


def test_brief_example_email_prompt_verbatim_in_tanglish(madesh):
    out = madesh.say("client ku mail anuppu, quotation ready nu sollu")
    assert out["reply"] == "Mail draft ready. Review panna venduma illa direct send panna venduma?"


def test_brief_example_tired_prioritises_important_tasks(madesh):
    out = madesh.say("Naa inniku konjam tired ah iruken.")
    assert out["reply"] == "Okay. Inniku schedule la important tasks mattum prioritize panren."


def test_tired_names_the_most_important_task_first(madesh):
    madesh.post("/tasks", {"title": "Send invoices", "priority": 4})
    madesh.post("/tasks", {"title": "Tidy desk", "priority": 1})
    out = madesh.say("Naa inniku konjam tired ah iruken.")
    assert "Send invoices" in out["reply"] and "Tidy desk" not in out["reply"]


def test_saptiya_gets_a_culturally_natural_and_honest_reply(madesh):
    out = madesh.say("Saptiya?")
    assert out["intent"] == "ate_q" and "AI" in out["reply"] and "saptingala" in out["reply"]


def test_presence_office(madesh):
    out = madesh.say("Naa office poitu varen.")
    assert out["intent"] == "presence_update" and "poitu vaanga" in out["reply"]


# ------------------------------------------------------------ language mirroring
def test_tamil_script_in_tamil_script_out(madesh):
    out = madesh.say("நாளை காலை 9 மணிக்கு மீட்டிங் நினைவூட்டு")
    assert out["style"] == "ta" and tamil_ratio(out["reply"]) > 0.6
    assert "நாளை காலை 9:00 மணிக்கு" in out["reply"]


def test_english_in_english_out(madesh):
    out = madesh.say("please remind me to call mom tomorrow at 5pm")
    assert out["style"] == "en" and out["reply"].startswith("Sure Madesh, I've set a reminder")
    assert "tomorrow at 5:00 PM" in out["reply"] and not has_tamil(out["reply"])


def test_language_can_switch_mid_conversation(madesh):
    a = madesh.say("hello")
    b = madesh.say("vanakkam")
    c = madesh.say("வணக்கம்")
    assert (a["style"], b["style"], c["style"]) == ("en", "tg", "ta")
    assert has_tamil(c["reply"]) and not has_tamil(a["reply"])


def test_bare_english_word_after_tanglish_stays_tanglish(madesh):
    madesh.say("Enaku reminder set pannu.")
    out = madesh.say("meeting")
    assert out["style"] == "tg" and "remind pannanum" in out["reply"]


def test_every_reply_carries_speech_segments_for_the_right_voices(madesh):
    out = madesh.say("Wensday, nalaiku 9 mani meeting remind pannu.")
    langs = {s["lang"] for s in out["speech"]}
    assert langs == {"ta", "en"}                       # Tanglish words -> Tamil voice, English words -> English voice
    assert {s["voice"] for s in out["speech"]} == {"ta-IN-PallaviNeural", "en-IN-NeerjaNeural"}


# ------------------------------------------------------------ multi-turn slot filling
def test_reminder_slot_filling_across_three_turns(madesh):
    assert "eppo remind pannanum" in madesh.say("Enaku reminder set pannu.")["reply"]
    assert madesh.get("/reminders").json() == []                       # nothing created yet
    assert "eppo remind pannanum" in madesh.say("meeting")["reply"]     # got the subject, still needs a time
    done = madesh.say("nalaiku 9 mani")
    assert done["reply"] == "Sure Madesh, nalaiku morning 9:00 AM-ku meeting reminder set panniten."
    assert len(madesh.get("/reminders").json()) == 1


def test_time_only_then_subject(madesh):
    assert "enna remind pannanum" in madesh.say("nalaiku 9 mani remind pannu")["reply"]
    assert "reminder set panniten" in madesh.say("dentist appointment")["reply"]
    assert madesh.get("/reminders").json()[0]["title"] == "dentist appointment"


def test_date_without_time_asks_for_the_time_and_keeps_the_date(madesh):
    assert "enna time-ku" in madesh.say("nalaiku meeting remind pannu")["reply"]
    assert "reminder set panniten" in madesh.say("4 mani")["reply"]
    due = madesh.get("/reminders").json()[0]["due_at"]
    assert due[11:16] == "10:30"   # 4 (PM heuristic -> 16:00 IST) == 10:30Z


def test_a_new_command_abandons_the_pending_question(madesh):
    madesh.say("Enaku reminder set pannu.")
    out = madesh.say("add task buy milk")
    assert out["intent"] == "task_create"
    assert madesh.get("/tasks").json()[0]["title"] == "buy milk"
    assert madesh.get("/reminders").json() == []


def test_no_cancels_a_pending_question(madesh):
    madesh.say("Enaku reminder set pannu.")
    assert madesh.say("venam")["intent"] == "stop"
    assert madesh.say("meeting")["intent"] != "reminder_create"


def test_call_needs_a_contact_then_dials(madesh):
    assert "Yaarukku call pannanum" in madesh.say("Call pannu da.")["reply"]
    out = madesh.say("amma")
    assert out["data"] == {"action": "dial", "contact": "amma"}


# ------------------------------------------------------------ email confirmation gate
class RecordingMailer:
    name = "recording"

    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    async def send(self, session, user, draft):
        self.sent.append((draft.recipient, draft.subject, draft.body))
        return self.ok


def test_email_is_never_sent_without_confirmation():
    mailer = RecordingMailer()
    with running(mailer=mailer) as c:
        from .conftest import Person
        p = Person(c, "a@x.com", "Madesh")
        p.say("send a mail to client and mention quotation ready")
        p.say("thanks")                                   # unrelated turns must not send it
        p.say("what time is it")
        assert mailer.sent == []
        status = p.say("Mail send pannitiya?")
        assert status["intent"] == "email_status" and "Innum illa" in status["reply"]     # asked, but not sent


def test_review_then_send_flow_and_status_question():
    mailer = RecordingMailer()
    with running(mailer=mailer) as c:
        from .conftest import Person
        p = Person(c, "a@x.com", "Madesh")
        p.say("client ku mail anuppu, quotation ready nu sollu")
        shown = p.say("review pannanum")
        assert "To: client" in shown["reply"] and "Quotation ready" in shown["reply"] and mailer.sent == []
        sent = p.say("seri anuppu")
        assert sent["reply"] == "Send panniten, Madesh. client ku mail poiduchu." and len(mailer.sent) == 1
        assert p.say("Mail send pannitiya?")["reply"].startswith("Aama, Madesh")


def test_direct_send_and_decline():
    mailer = RecordingMailer()
    with running(mailer=mailer) as c:
        from .conftest import Person
        p = Person(c, "a@x.com", "Madesh")
        p.say("send a mail to boss and say running late")
        assert "Sent, Madesh" in p.say("send it directly")["reply"] and len(mailer.sent) == 1
        p.say("send a mail to boss and say ignore that")
        assert p.say("no")["intent"] == "email_discard" and len(mailer.sent) == 1     # declined -> nothing sent


def test_unconnected_mail_is_queued_not_falsely_reported_sent():
    with running(mailer=NullSender()) as c:
        from .conftest import Person
        p = Person(c, "a@x.com", "Madesh")
        p.say("send a mail to client and say hi")
        out = p.say("yes")
        assert "saved the draft" in out["reply"] and out["data"]["status"] == "queued"


def test_email_asks_for_missing_recipient_then_body(madesh):
    assert "Yaarukku mail anuppanum" in madesh.say("Mail send pannu")["reply"]
    assert "enna mail anuppanum" in madesh.say("ravi")["reply"]
    assert madesh.say("meeting postponed nu sollu")["reply"].startswith("Mail draft ready")


# ------------------------------------------------------------ calendar
def test_calendar_create_query_conflict_and_update(madesh):
    made = madesh.say("meeting nalaiku 3 mani schedule pannu")
    assert made["intent"] == "calendar_create" and "nalaiku afternoon 3:00 PM-ku" in made["reply"]
    assert "Unga next event" in madesh.say("Meeting eppo start aagum?")["reply"]
    clash = madesh.say("meeting nalaiku 3 mani schedule pannu")
    assert "clash" in clash["reply"]
    assert "Edha maathanum" in madesh.say("Schedule update pannunga.")["reply"]
    moved = madesh.say("nalaiku 5 mani")
    assert moved["intent"] == "schedule_update" and "nalaiku evening 5:00 PM-ku" in moved["reply"]


def test_calendar_query_for_a_day_lists_events(madesh):
    madesh.say("meeting inniku 11 pm schedule pannu")
    out = madesh.say("what's on my schedule today")
    assert out["intent"] == "calendar_query" and out["reply"].startswith("Your schedule") and "meeting" in out["reply"].lower()


# ------------------------------------------------------------ tasks / notes / goals
def test_task_lifecycle_in_tanglish(madesh):
    assert "Task add panniten" in madesh.say("task add pannu buy milk")["reply"]
    assert "buy milk" in madesh.say("task list kaattu")["reply"]
    assert "Done nu mark panniten" in madesh.say("buy milk task mudinchidichu")["reply"]
    assert "Open tasks edhuvum illa" in madesh.say("task list kaattu")["reply"]


def test_note_and_goal_via_voice(madesh):
    madesh.say("note eduthuko: project idea about voice UI")
    assert "voice UI" in madesh.say("search notes voice")["reply"]
    assert "Goal set panniten" in madesh.say("goal set pannu learn tamil typing")["reply"]
    assert "learn tamil typing" in madesh.say("goals kaattu")["reply"]


def test_plan_day_orders_tasks_by_importance(madesh):
    madesh.post("/tasks", {"title": "Low thing", "priority": 1})
    madesh.post("/tasks", {"title": "Big thing", "priority": 4})
    reply = madesh.say("inniku plan enna")["reply"]
    assert reply.index("Big thing") < reply.index("Low thing")


# ------------------------------------------------------------ memory-driven personalisation
def test_learns_and_uses_the_users_name():
    with running() as c:
        from .conftest import Person
        p = Person(c, "x@x.com", "")
        assert "Nice to meet you, Ravi" in p.say("my name is ravi")["reply"]
        assert p.say("thanks")["reply"] == "You're welcome, Ravi."


def test_tamil_name_statement_and_language_preference(madesh):
    assert "Nice to meet you, Kumar" in madesh.say("en peyar kumar")["reply"]
    assert madesh.say("speak in tamil")["intent"] == "language_pref"
    out = madesh.say("hello there")                       # English input, but the user asked for Tamil
    assert out["style"] == "ta" and has_tamil(out["reply"])


def test_remember_fact_is_acknowledged_and_stored(madesh):
    assert madesh.say("remember that my wifi is at the office")["intent"] == "remember_fact"
    texts = [m["text"] for m in madesh.get("/memories").json()]
    assert any("wifi" in t for t in texts)


# ------------------------------------------------------------ offline fallback + resilience
def test_unknown_request_falls_back_gracefully_when_offline(madesh):
    out = madesh.say("explain quantum entanglement simply")
    assert out["tier"] == "offline" and out["intent"] == "unknown" and "offline mode" in out["reply"]


def test_offline_fallback_reply_is_localised(madesh):
    assert "offline mode la" in madesh.say("epdi quantum computing work aagum nu vilakku")["reply"]


def test_conversation_history_is_persisted(madesh):
    madesh.say("hello")
    madesh.say("thanks")
    convs = madesh.get("/conversations").json()
    assert len(convs) == 1
    msgs = madesh.get(f"/conversations/{convs[0]['id']}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
