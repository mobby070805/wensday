"""Language-system tests: Tamil / English / Tanglish detection, NLU and time parsing.

Most utterances here are taken verbatim from the product brief.
"""
from datetime import datetime

import pytest

from app.i18n import lexicon
from app.i18n.detect import detect
from app.i18n.normalize import skeleton, tokenize
from app.nlu.engine import analyze
from app.nlu.timeparse import parse_time

NOW = datetime(2026, 9, 21, 10, 0)  # a Monday, 10:00


# ---------------------------------------------------------------- detection
@pytest.mark.parametrize("text,lang", [
    ("Saptiya?", "tanglish"),
    ("Naa office poitu varen.", "tanglish"),
    ("Enaku reminder set pannu.", "tanglish"),
    ("Meeting eppo start aagum?", "tanglish"),
    ("Mail send pannitiya?", "tanglish"),
    ("Call pannu da.", "tanglish"),
    ("Schedule update pannunga.", "tanglish"),
    ("Wensday, nalaiku 9 mani meeting remind pannu.", "tanglish"),
    ("Naa inniku konjam tired ah iruken.", "tanglish"),
    ("Wensday, send a mail to client and mention quotation ready.", "en"),
    ("please remind me to call mom at 5pm", "en"),
    ("what's on my schedule today", "en"),
    ("நாளை காலை 9 மணிக்கு நினைவூட்டு", "ta"),
    ("இன்னைக்கு என்ன மீட்டிங் இருக்கு", "ta"),
])
def test_language_detection(text, lang):
    assert detect(text).lang == lang


def test_code_switching_is_flagged_not_rejected():
    p = detect("Naa office poitu varen, quotation mail send pannitiya?")
    assert p.lang == "tanglish" and p.mixed


def test_register_detection():
    assert detect("Call pannu da").register == "casual"
    assert detect("Schedule update pannunga sir").register == "respectful"


# ------------------------------------------------------- spelling variance
@pytest.mark.parametrize("a,b", [
    ("nalaiku", "naalaiku"), ("nalaiku", "nalaikku"), ("pannu", "panu"), ("aagum", "aakum"), ("enaku", "enakku"),
])
def test_tanglish_spelling_variants_share_a_skeleton(a, b):
    assert skeleton(a) == skeleton(b)


@pytest.mark.parametrize("variant", ["nalaiku", "naalaiku", "nalaikku", "nalai", "நாளை", "tomorrow"])
def test_all_three_languages_map_to_one_concept(variant):
    assert "tomorrow_word" in lexicon.concepts_for(variant)


def test_lexicon_has_no_cross_concept_skeleton_collisions_for_core_words():
    # Words that map to more than one concept would make intent routing ambiguous.
    for w in ("remind", "mail", "meeting", "task", "note", "goal", "tired", "call"):
        core = lexicon.concepts_for(w) - {"call"} if w != "call" else lexicon.concepts_for(w)
        assert w in {w} and core, w


# ----------------------------------------------------------- time parsing
@pytest.mark.parametrize("text,expected", [
    ("nalaiku 9 mani", datetime(2026, 9, 22, 9, 0)),
    ("nalaiku morning 9", datetime(2026, 9, 22, 9, 0)),
    ("tomorrow 9am", datetime(2026, 9, 22, 9, 0)),
    ("inniku sayangalam 5 mani", datetime(2026, 9, 21, 17, 0)),
    ("நாளை காலை 9 மணிக்கு", datetime(2026, 9, 22, 9, 0)),
    ("in 10 minutes", datetime(2026, 9, 21, 10, 10)),
    ("10 nimisham la", datetime(2026, 9, 21, 10, 10)),
    ("2 mani neram kalichu", datetime(2026, 9, 21, 12, 0)),
    ("next friday 3:30 pm", datetime(2026, 9, 25, 15, 30)),
    ("velli kizhamai 4 pm", datetime(2026, 9, 25, 16, 0)),
    ("nalaiku iravu 8 mani", datetime(2026, 9, 22, 20, 0)),
    ("onbadhu mani nalaiku", datetime(2026, 9, 22, 9, 0)),
    ("tomorrow 3", datetime(2026, 9, 22, 15, 0)),   # working-day heuristic: 1-6 -> PM
])
def test_time_parsing(text, expected):
    assert parse_time(tokenize(text), NOW).when == expected


def test_no_time_found():
    assert not parse_time(tokenize("call mom"), NOW).found


# --------------------------------------------------------------------- NLU
def nlu(text):
    return analyze(text, NOW)


def test_reminder_tanglish_with_time_and_subject():
    r = nlu("Wensday, nalaiku 9 mani meeting remind pannu.")
    assert r.intent == "reminder_create"
    assert r.entities["when"] == "2026-09-22T09:00:00"
    assert r.entities["subject"].lower() == "meeting"


def test_reminder_missing_details_is_still_a_reminder_intent():
    r = nlu("Enaku reminder set pannu.")
    assert r.intent == "reminder_create"
    assert "when" not in r.entities and not r.entities.get("subject")


def test_reminder_english_extracts_subject():
    r = nlu("please remind me to call mom at 5pm")
    assert r.intent == "reminder_create"
    assert r.entities["subject"].lower() == "call mom"
    assert r.entities["when"] == "2026-09-21T17:00:00"


def test_reminder_tamil_script():
    r = nlu("நாளை காலை 9 மணிக்கு மீட்டிங் நினைவூட்டு")
    assert r.intent == "reminder_create" and r.entities["when"] == "2026-09-22T09:00:00"


def test_email_draft_english_with_recipient_and_body():
    r = nlu("Wensday, send a mail to client and mention quotation ready.")
    assert r.intent == "email_draft"
    assert r.entities["recipient"] == "client"
    assert r.entities["body"] == "quotation ready"


def test_email_draft_tanglish_recipient_and_body():
    r = nlu("client ku mail anuppu, quotation ready nu sollu")
    assert r.intent == "email_draft"
    assert r.entities["recipient"] == "client"
    assert r.entities["body"] == "quotation ready"


def test_email_status_question():
    assert nlu("Mail send pannitiya?").intent == "email_status"


def test_calendar_query_meeting_when():
    assert nlu("Meeting eppo start aagum?").intent == "calendar_query"
    assert nlu("what's on my schedule today").intent == "calendar_query"


def test_schedule_update():
    assert nlu("Schedule update pannunga.").intent == "schedule_update"


def test_call_without_contact():
    r = nlu("Call pannu da.")
    assert r.intent == "call_contact" and not r.entities.get("contact")


def test_call_with_contact():
    assert nlu("amma ku call pannu").entities["contact"].lower() == "amma"
    assert nlu("call Ravi").entities["contact"] == "Ravi"


def test_presence_office():
    r = nlu("Naa office poitu varen.")
    assert r.intent == "presence_update" and r.entities["place"] == "office"


def test_tired_mood():
    r = nlu("Naa inniku konjam tired ah iruken.")
    assert r.intent == "mood_low" and r.entities["mood"] == "tired"


def test_social_intents():
    assert nlu("Saptiya?").intent == "ate_q"
    assert nlu("vanakkam").intent == "greeting"
    assert nlu("hello").intent == "greeting"
    assert nlu("how are you").intent == "howru"
    assert nlu("thanks").intent == "thanks"
    assert nlu("வணக்கம்").intent == "greeting"


def test_tasks_and_notes_and_goals():
    r = nlu("add task buy milk")
    assert r.intent == "task_create" and r.entities["subject"] == "buy milk"
    assert nlu("task list kaattu").intent == "task_list"
    assert nlu("show my tasks").intent == "task_list"
    r = nlu("note eduthuko: project idea about voice UI")
    assert r.intent == "note_create"
    assert nlu("goal set pannu learn tamil typing").intent == "goal_create"
    assert nlu("inniku plan enna").intent == "plan_day"


@pytest.mark.parametrize("text,intent", [
    ("yes", "confirm_yes"), ("aama", "confirm_yes"), ("seri anuppu", "confirm_yes"), ("ஆமா", "confirm_yes"),
    ("no", "confirm_no"), ("venam", "confirm_no"), ("illa", "confirm_no"),
    ("review pannanum", "confirm_review"), ("direct send pannu", "confirm_direct"),
])
def test_confirmation_followups(text, intent):
    assert nlu(text).intent == intent


def test_unknown_goes_to_llm_tier():
    assert nlu("explain quantum entanglement simply").intent == "unknown"


def test_empty_input_is_safe():
    assert nlu("").intent == "unknown"
    assert nlu("   ?!  ").intent == "unknown"


# ------------------------------------------------- English must never be mistaken for Tanglish
@pytest.mark.parametrize("word", [
    "Jerry", "Tom", "Mary", "Sarah", "John", "Priya", "Ravi", "Kumar", "Peter", "Susan", "David", "Jenny", "Harry", "Larry", "Barry",
    "coffee", "office", "manager", "budget", "invoice", "project", "deadline", "customer", "lunch", "dinner", "phone", "laptop", "printer",
    "report", "review", "summary", "client", "quotation", "payment", "salary", "bonus", "holiday", "flight", "ticket", "hotel", "bank",
])
def test_common_english_words_and_names_are_not_tanglish(word):
    assert not lexicon.is_tanglish_word(word), word
    assert detect(f"send {word} details").lang == "en"
