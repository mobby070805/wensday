"""Rule-based NLU: utterance -> intent + entities, for Tamil, English and Tanglish.

This is "tier 1" understanding. It is fast, deterministic, works offline, and
handles the everyday command surface ("nalaiku 9 mani meeting remind pannu").
Anything it can't classify (`unknown`) is escalated to the LLM tier by the agent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.i18n import lexicon
from app.i18n.detect import LangProfile, detect
from app.i18n.normalize import is_tamil_token, tokenize
from .timeparse import TimeSpec, parse_time

_QWORDS = {"when", "what", "who", "where", "why", "how"}
_STRIP = {"remind", "add", "task", "note", "goal", "please", "filler", "do", "v_take", "v_add", "note_taking", "v_write", "draft", "schedule", "v_tell", "v_keep"}
_EDGE = {"filler", "self", "please", "and", "you", "do", "yes"}
_COMMAND = {"remind", "mail", "task", "note", "goal", "meeting", "schedule", "call", "plan", "message", "search"}

_PHRASES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bhow\s+(are|r)\s+(you|u)\b|\bhow'?s\s+it\s+going\b|\bwhat'?s\s+up\b|\bepd?i\s+iruk+(a|inga|ing?ala)\b|எப்படி\s+இருக்க"), "howru"),
    (re.compile(r"\bgood\s+(morning|evening|afternoon)\b|\bgm\b|காலை வணக்கம்|\bkaalai vanakkam\b"), "greet"),
    (re.compile(r"\bgood\s*night\b|\bgn\b|\bsee\s+you\b|\bta\s*ta\b"), "bye"),
    (re.compile(r"\bwhat\s+can\s+you\s+do\b|\bwhat\s+do\s+you\s+do\b|\benna\s+(panna|pannuva)\s+mudiyum\b|என்ன\s+செய்ய\s+முடியும்"), "help"),
    (re.compile(r"\bthank\s+you\b|\bthanks?\b"), "thanks"),
    (re.compile(r"\bnever\s*mind\b|\bleave\s+it\b|\bforget\s+it\b"), "stop"),
    (re.compile(r"\bwhat\s+time\b|\btime\s+enna\b|\bnow\s+time\b|\bmani\s+enna\b|மணி\s+என்ன|நேரம்\s+என்ன"), "time"),
    (re.compile(r"\bwhat\s+(is\s+)?(the\s+)?date\b|\bwhat\s+day\b|\bindru\s+enna\s+(date|thethi|naal)\b|இன்று\s+என்ன\s+(தேதி|கிழமை)"), "date"),
    (re.compile(r"\bmy\s+day\b|\bday\s+plan\b|\bplan\s+(my|the)\s+day\b"), "plan"),
]


@dataclass
class NLUResult:
    intent: str
    confidence: float
    text: str
    lang: LangProfile
    entities: dict = field(default_factory=dict)
    concepts: set[str] = field(default_factory=set)

    @property
    def is_command(self) -> bool:
        return self.intent != "unknown"


def _word_tokens(text: str) -> list[str]:
    return [t for t in tokenize(text) if t[0].isalnum() or is_tamil_token(t)]


def _strip_case(tok: str) -> str:
    low = tok.lower()
    for suf in ("kku", "ku"):
        if low.endswith(suf) and len(low) > len(suf) + 2:
            return tok[: -len(suf)]
    if tok.endswith("க்கு"):
        return tok[: -3]
    return tok


def _subject(words: list[str], tags: list[set[str]], consumed: set[int], extra_strip: set[str] = frozenset()) -> str:
    strip = _STRIP | set(extra_strip)
    protected = {"meeting", "call", "mail"} - set(extra_strip)  # content words unless the caller says otherwise
    keep: list[tuple[str, set[str]]] = []
    for i, (w, t) in enumerate(zip(words, tags)):
        if i in consumed:
            continue
        if t & strip and not (t & protected):
            continue
        keep.append((w, t))
    while keep and keep[0][1] & _EDGE and not keep[0][1] & protected:
        keep.pop(0)
    while keep and keep[-1][1] & _EDGE and not keep[-1][1] & protected:
        keep.pop()
    return " ".join(w for w, _ in keep).strip()


_EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_BODY_EN = re.compile(r"(?:mention|saying|say|that|regarding|about|tell\s+(?:him|her|them)(?:\s+that)?)\s+(.+)$", re.I)
_BODY_TG_NU = re.compile(r"^(.+?)\s*(?:nu|nnu|னு|ன்னு)\s+(?:sollu|solli|sollunga|mention|type|eluthu|ezhuthu|எழுது|சொல்லு|சொல்லுங்க)", re.I)
_BODY_TG_MENTION = re.compile(r"^(.+?)\s+mention\s+(?:pannu|panu|pannunga)", re.I)
_SEG_SPLIT = re.compile(r",|;|\b(?:and|aprom|apuram|appuram|then)\b", re.I)
_RECIP_EN = re.compile(r"\b(?:to|for)\s+(?:the\s+|my\s+)?([\w.@-]+)", re.I)
_DETERMINERS = {"me", "myself", "the", "a", "an", "my", "him", "her", "them", "it"}


def _mail_entities(text: str, words: list[str], tags: list[set[str]], consumed: set[int]) -> dict:
    ent: dict = {}
    m = _EMAIL_RX.search(text)
    if m:
        ent["recipient"] = m.group(0)
    else:
        for i, w in enumerate(words):
            low = w.lower()
            if i in consumed or is_tamil_token(w) and not w.endswith("க்கு"):
                continue
            if low in {"ku", "kku"} and i > 0 and not tags[i - 1] & {"self", "filler", "mail"}:
                ent["recipient"] = words[i - 1]
                break
            if w.endswith("க்கு") and not tags[i] & {"self"}:
                ent["recipient"] = _strip_case(w)
                break
            if (low.endswith("ku") or low.endswith("kku")) and not tags[i] & {"self", "filler", "tomorrow_word", "today_word", "mail"}:
                stem = _strip_case(w)
                if stem.lower() not in lexicon.tanglish_words() and stem.lower() not in lexicon.english_words():
                    ent["recipient"] = stem
                    break
        if "recipient" not in ent:
            r = _RECIP_EN.search(text)
            if r and r.group(1).lower() not in _DETERMINERS:
                ent["recipient"] = r.group(1)
    for seg in _SEG_SPLIT.split(text):
        seg = seg.strip()
        for rx in (_BODY_EN, _BODY_TG_NU, _BODY_TG_MENTION):
            b = rx.search(seg)
            if b:
                body = b.group(1).strip(" .?!")
                if body and body.lower() != ent.get("recipient", "").lower():
                    ent["body"] = body
                break
        if "body" in ent:
            break
    return ent


def _time_entities(spec: TimeSpec) -> dict:
    if not spec.found:
        return {}
    return {
        "when": spec.when.isoformat(),
        "has_time": spec.has_time,
        "has_date": spec.has_date,
        "relative": spec.relative,
        "part": spec.part,
    }


def analyze(text: str, now: datetime | None = None, profile: LangProfile | None = None) -> NLUResult:
    now = now or datetime.now()
    profile = profile or detect(text)
    words = _word_tokens(text)
    low_text = " ".join(words).lower()
    tags = [lexicon.concepts_for(w) for w in words]
    c: set[str] = set().union(*tags) if tags else set()
    for rx, concept in _PHRASES:
        if rx.search(low_text) or rx.search(text.lower()):
            c.add(concept)

    spec = parse_time(words, now)
    q = "?" in text or bool(c & _QWORDS) or any(lexicon.looks_like_question(w) for w in words)
    ent: dict = _time_entities(spec)
    consumed = spec.consumed

    def done(intent: str, conf: float = 0.9, **more) -> NLUResult:
        ent.update({k: v for k, v in more.items() if v not in (None, "")})
        return NLUResult(intent, conf, text, profile, ent, c)

    content = c - {"filler", "self", "you", "please", "and", "howru", "how", "what", "when", "who", "where", "why"}
    n = len(words)
    has_cmd = bool(c & _COMMAND)

    # ---- short confirmations / choices (used for pending-action follow-ups)
    if n <= 4 and not has_cmd and not spec.found:
        if "review" in c and not c & {"yes"}:
            return done("confirm_review")
        if content & {"direct"} or (content & {"yes"} and content & {"send", "v_send"}):
            return done("confirm_direct" if "direct" in c else "confirm_yes")
        if content & {"yes"} and not content - {"yes", "do", "send", "v_send", "direct"}:
            return done("confirm_yes")
        if content & {"no", "stop"} and not content - {"no", "stop", "do", "send", "v_send", "delete"}:
            return done("confirm_no")

    # ---- social
    if not has_cmd:
        if "ate_q" in c:
            return done("ate_q")
        if "howru" in c and (q or "you" in c or n <= 3):
            return done("howru")
        if "help" in c:
            return done("help")
        if "thanks" in c:
            return done("thanks")
        if "bye" in c:
            return done("bye")
        if "greet" in c and n <= 4:
            return done("greeting")

    # ---- email
    if "mail" in c:
        if q and c & {"send", "v_send", "done", "do"} and not c & {"draft", "v_write"} and not ent.get("body"):
            return done("email_status")
        if c & {"send", "v_send", "draft", "v_write", "do", "add", "v_add", "review"} or n <= 3:
            return done("email_draft", **_mail_entities(text, words, tags, consumed))
    # ---- reminders
    if "remind" in c:
        if (c & {"show", "v_show", "what", "which"} or ("when" in c and not spec.found)) and not spec.found:
            return done("reminder_list")
        return done("reminder_create", subject=_subject(words, tags, consumed))
    # ---- calendar
    if c & {"meeting", "schedule"}:
        if c & {"update", "v_change"}:
            return done("schedule_update", subject=_subject(words, tags, consumed, {"update", "v_change", "meeting"}))
        if q or c & {"show", "v_show", "v_see"}:
            return done("calendar_query", subject=_subject(words, tags, consumed, {"meeting", "start", "when", "what"}))
        if "meeting" in c and (spec.found or c & {"add", "v_add", "do"}):
            return done("calendar_create", subject=_subject(words, tags, consumed))
        if "schedule" in c and "meeting" not in c and not spec.found:
            return done("calendar_query")
        if "meeting" in c:
            return done("calendar_create", 0.7, subject=_subject(words, tags, consumed))
    # ---- tasks
    if "task" in c:
        if c & {"done", "v_finish"}:
            return done("task_complete", subject=_subject(words, tags, consumed, {"done", "v_finish"}))
        if c & {"add", "v_add", "do", "v_take"} and _subject(words, tags, consumed, {"done"}):
            return done("task_create", subject=_subject(words, tags, consumed))
        return done("task_list") if q or c & {"show", "v_show", "what"} or not _subject(words, tags, consumed) else done("task_create", subject=_subject(words, tags, consumed))
    # ---- notes
    if "note" in c or "note_taking" in c:
        if c & {"search", "v_search", "show", "v_show", "what", "find"} and "v_take" not in c:
            return done("note_search", query=_subject(words, tags, consumed, {"search", "v_search", "show", "v_show", "what"}))
        return done("note_create", subject=_subject(words, tags, consumed))
    # ---- goals
    if "goal" in c:
        if c & {"add", "v_add", "do", "v_take"}:
            return done("goal_create", subject=_subject(words, tags, consumed))
        return done("goal_list")
    # ---- productivity
    if "plan" in c:
        return done("plan_day")
    if "tired" in c or "stressed" in c:
        return done("mood_low", mood="tired" if "tired" in c else "stressed")
    # ---- presence: "naa office poitu varen"
    if c & {"v_go"}:
        place = "office" if "office" in c else "home" if "home" in c else next((w.lower() for w, t in zip(words, tags) if "place" in t), None)
        if place:
            return done("presence_update", place=place, returning="v_come" in c)
        if c & {"v_come"}:
            return done("bye")
    # ---- calls
    if "call" in c and not c & {"meeting"}:
        contact = _subject(words, tags, consumed, {"call", "v_call", "self", "you"})
        return done("call_contact", contact=_strip_case(contact) if contact else None)
    if "v_call" in c:
        contact = _subject(words, tags, consumed, {"v_call", "self", "you"})
        return done("call_contact", contact=_strip_case(contact) if contact else None)
    # ---- utilities
    if "time" in c and (q or "what" in c):
        return done("time_now")
    if "date" in c and (q or "what" in c):
        return done("date_now")
    if "weather" in c:
        return done("weather")
    if "stop" in c and n <= 3:
        return done("stop")
    if "greet" in c:
        return done("greeting", 0.7)
    if "howru" in c:
        return done("howru", 0.7)
    if "summarize" in c:
        return done("summarize", 0.7, subject=_subject(words, tags, consumed, {"summarize"}))
    return NLUResult("unknown", 0.0, text, profile, ent, c)


def free_text(text: str, now: datetime | None = None) -> str:
    """The 'payload' of a bare answer (e.g. the reply "meeting" to "what should I remind you about?"):
    the utterance minus time expressions and edge filler."""
    words = _word_tokens(text)
    tags = [lexicon.concepts_for(w) for w in words]
    spec = parse_time(words, now or datetime.now())
    return _subject(words, tags, spec.consumed)
