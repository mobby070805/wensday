"""Time-expression parsing for Tamil, English and Tanglish.

    "9 mani"                     "காலை 9 மணி"               "tomorrow 9am"
    "nalaiku morning 9"          "inniku sayangalam 5 mani" "in 10 minutes"
    "10 nimisham la"             "2 mani neram kalichu"     "next friday 3:30 pm"

Bare hours are resolved with a working-day heuristic (documented in docs/nlu.md):
1-6 -> PM, 7-11 -> AM, 12 -> noon, unless a day-part word is given.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.i18n.normalize import skeleton

_NUM_WORDS = {
    # english
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
    # tanglish (skeleton-keyed at lookup)
    "onnu": 1, "ondru": 1, "rendu": 2, "irandu": 2, "moonu": 3, "moondru": 3, "naalu": 4, "naangu": 4, "anju": 5, "ainthu": 5,
    "aaru": 6, "ezhu": 7, "elu": 7, "ettu": 8, "onbathu": 9, "onbadhu": 9, "pathu": 10, "pathinonnu": 11, "pannirendu": 12,
    # tamil script
    "ஒன்று": 1, "ஒண்ணு": 1, "இரண்டு": 2, "ரெண்டு": 2, "மூன்று": 3, "மூணு": 3, "நான்கு": 4, "நாலு": 4, "ஐந்து": 5, "அஞ்சு": 5,
    "ஆறு": 6, "ஏழு": 7, "எட்டு": 8, "ஒன்பது": 9, "ஒம்பது": 9, "பத்து": 10, "பதினொன்று": 11, "பன்னிரண்டு": 12,
}
_NUM_SKEL = {skeleton(k): v for k, v in _NUM_WORDS.items() if k.isascii()}

_TODAY = {"today", "tonight", "inniku", "innaiku", "inikku", "innaikku", "indru", "inniki", "இன்று", "இன்னிக்கு", "இன்னைக்கு", "இன்றைக்கு"}
_TOMORROW = {"tomorrow", "tmrw", "tomo", "nalaiku", "naalaiku", "nalaikku", "naalai", "nalai", "naale", "நாளை", "நாளைக்கு"}
_DAY_AFTER = {"marunaal", "மறுநாள்", "naalaimarunaal"}
_YESTERDAY = {"yesterday", "nettru", "netru", "நேற்று"}

_WEEKDAYS = {
    0: {"monday", "mon", "thingal", "thinkal", "thingatkizhamai", "திங்கள்", "திங்கட்கிழமை"},
    1: {"tuesday", "tue", "tues", "sevvai", "sevvaai", "செவ்வாய்", "செவ்வாய்க்கிழமை"},
    2: {"wednesday", "wed", "budhan", "puthan", "புதன்", "புதன்கிழமை"},
    3: {"thursday", "thu", "thur", "viyazhan", "viyalan", "vyazhan", "வியாழன்", "வியாழக்கிழமை"},
    4: {"friday", "fri", "velli", "வெள்ளி", "வெள்ளிக்கிழமை"},
    5: {"saturday", "sat", "sani", "சனி", "சனிக்கிழமை"},
    6: {"sunday", "sun", "gnayiru", "nyayiru", "ஞாயிறு", "ஞாயிற்றுக்கிழமை"},
}

# day-part -> (canonical, is_pm)
_PARTS = {
    "morning": ("morning", False), "kaalai": ("morning", False), "kalai": ("morning", False), "kaalaila": ("morning", False),
    "kalaila": ("morning", False), "காலை": ("morning", False), "காலையில்": ("morning", False), "am": ("morning", False),
    "afternoon": ("afternoon", True), "mathiyam": ("afternoon", True), "madhiyam": ("afternoon", True), "மதியம்": ("afternoon", True),
    "uchi": ("afternoon", True), "noon": ("afternoon", True),
    "evening": ("evening", True), "sayangalam": ("evening", True), "saayangalam": ("evening", True), "maalai": ("evening", True),
    "malai": ("evening", True), "மாலை": ("evening", True), "மாலையில்": ("evening", True),
    "night": ("night", True), "iravu": ("night", True), "raatri": ("night", True), "ratri": ("night", True), "இரவு": ("night", True),
    "pm": ("evening", True),
}
_HOUR_UNITS = {"mani", "மணி", "மணிக்கு", "baje", "oclock", "o'clock", "manikku", "manikkuu"}
_MIN_UNITS = {"min", "mins", "minute", "minutes", "nimisham", "nimidam", "nimishathula", "நிமிடம்", "நிமிடத்தில்", "நிமிஷம்"}
_NERAM = {"neram", "நேரம்"}
_PRE_REL = {"in", "after"}
_POST_REL = {"kalichu", "kazhichu", "kalithu", "கழித்து", "பிறகு", "piragu"}
_DUR_FILLER = {"la", "ila", "ல", "ல்", "இல்"}


@dataclass
class TimeSpec:
    when: datetime | None = None
    has_date: bool = False
    has_time: bool = False
    relative: bool = False
    day_offset: int | None = None
    consumed: set[int] = field(default_factory=set)
    part: str | None = None   # morning/afternoon/evening/night as the user said it

    @property
    def found(self) -> bool:
        return self.when is not None


def _num(tok: str) -> int | None:
    t = tok.lower()
    if t.isdigit():
        return int(t)
    if t in _NUM_WORDS:
        return _NUM_WORDS[t]
    return _NUM_SKEL.get(skeleton(t)) if t.isascii() and len(t) >= 3 else None


def _strip(tok: str) -> str:
    return tok.lower().strip(".,?!")


def _resolve_hour(hour: int, pm_hint: bool | None, part: str | None, explicit_day: bool) -> int:
    if hour > 12:
        return hour % 24
    if pm_hint is True:
        if part == "night" and hour == 12:
            return 0
        return hour if hour == 12 else hour + 12
    if pm_hint is False:
        return 0 if hour == 12 else hour
    # no hint: working-day heuristic
    if hour == 12:
        return 12
    if 1 <= hour <= 6:
        return hour + 12
    return hour


def parse_time(tokens: list[str], now: datetime) -> TimeSpec:
    """Parse the first time expression found in *tokens* (already tokenised, original case)."""
    spec = TimeSpec()
    low = [_strip(t) for t in tokens]
    n = len(low)

    # ---- relative durations: "in 10 minutes", "10 nimisham la", "2 mani neram kalichu"
    for i, t in enumerate(low):
        v = _num(t)
        if v is None or i + 1 >= n:
            continue
        nxt = low[i + 1]
        is_min = nxt in _MIN_UNITS
        is_hr = nxt in {"hour", "hours", "hr", "hrs"} or (nxt in {"mani", "மணி"} and i + 2 < n and low[i + 2] in _NERAM)
        if not (is_min or is_hr):
            continue
        prefix = i > 0 and low[i - 1] in _PRE_REL
        minutes = v if is_min else v * 60
        spec.when = (now + timedelta(minutes=minutes)).replace(second=0, microsecond=0)
        spec.relative = spec.has_time = spec.has_date = True
        spec.consumed |= {i, i + 1}
        if is_hr and nxt in {"mani", "மணி"}:
            spec.consumed.add(i + 2)
        if prefix:
            spec.consumed.add(i - 1)
        for j in range(i + 2, min(n, i + 5)):
            if low[j] in _POST_REL or low[j] in _DUR_FILLER:
                spec.consumed.add(j)
        return spec

    # ---- day words
    day_offset: int | None = None
    weekday: int | None = None
    for i, t in enumerate(low):
        if t in _TODAY:
            day_offset = 0
        elif t in _TOMORROW:
            day_offset = 1
        elif t in _DAY_AFTER:
            day_offset = 2
        elif t in _YESTERDAY:
            day_offset = -1
        else:
            for wd, names in _WEEKDAYS.items():
                if t in names or any(t == nm + "kizhamai" for nm in names):
                    weekday = wd
                    break
            else:
                continue
        spec.consumed.add(i)
        if i > 0 and low[i - 1] in {"next", "on", "adutha", "அடுத்த"}:
            spec.consumed.add(i - 1)
        if i + 1 < n and low[i + 1] in {"kizhamai", "kilamai", "kizhamaiyil", "கிழமை"}:
            spec.consumed.add(i + 1)
    # "nalaiku marunaal" / "day after tomorrow"
    joined = " ".join(low)
    if "day after tomorrow" in joined:
        day_offset = 2
        for i, t in enumerate(low):
            if t in {"day", "after", "tomorrow"}:
                spec.consumed.add(i)

    # ---- day part
    part: str | None = None
    pm_hint: bool | None = None
    for i, t in enumerate(low):
        if t in _PARTS and t not in {"am", "pm"}:
            part, pm_hint = _PARTS[t]
            spec.consumed.add(i)
            break

    # ---- clock time
    hour = minute = None
    for i, t in enumerate(low):
        m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", t)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))
            spec.consumed.add(i)
            if i + 1 < n and low[i + 1] in {"am", "pm"}:
                pm_hint = low[i + 1] == "pm"
                part = part or _PARTS[low[i + 1]][0]
                spec.consumed.add(i + 1)
            elif i + 1 < n and low[i + 1] in _HOUR_UNITS:
                spec.consumed.add(i + 1)
            break
        v = _num(t)
        if v is not None and 0 <= v <= 24 and i + 1 < n:
            nxt = low[i + 1]
            if nxt in {"am", "pm"}:
                hour, minute = v, 0
                pm_hint = nxt == "pm"
                part = part or _PARTS[nxt][0]
                spec.consumed |= {i, i + 1}
                break
            if nxt in _HOUR_UNITS and not (i + 2 < n and low[i + 2] in _NERAM):
                hour, minute = v, 0
                spec.consumed |= {i, i + 1}
                # "9 mani 30 nimisham" / "9 mani arai"
                if i + 2 < n and low[i + 2] in {"arai", "அரை", "half"}:
                    minute = 30
                    spec.consumed.add(i + 2)
                break
        # "at 9" / "at 5"
        if v is not None and 1 <= v <= 12 and i > 0 and low[i - 1] == "at":
            hour, minute = v, 0
            spec.consumed |= {i, i - 1}
            break

    # "tomorrow 3": bare number straight after a day word
    if hour is None and (day_offset is not None or weekday is not None):
        for i, t in enumerate(low):
            if (t in _TODAY or t in _TOMORROW or t in _DAY_AFTER or any(t in nm for nm in _WEEKDAYS.values())) and i + 1 < n:
                v = _num(low[i + 1])
                if v is not None and 1 <= v <= 12 and (i + 2 >= n or low[i + 2] not in _MIN_UNITS):
                    hour, minute = v, 0
                    spec.consumed.add(i + 1)
                    break

    # "morning 9" / "sayangalam 5": bare number right next to a day-part word
    if hour is None and part is not None:
        for i, t in enumerate(low):
            if t in _PARTS and t not in {"am", "pm"}:
                for j in (i + 1, i - 1):
                    v = _num(low[j]) if 0 <= j < n else None
                    if v is not None and 1 <= v <= 12 and j not in spec.consumed:
                        hour, minute = v, 0
                        spec.consumed.add(j)
                        break
                break

    if hour is None and day_offset is None and weekday is None and part is None:
        return spec

    base = now
    explicit_day = day_offset is not None or weekday is not None
    if day_offset is not None:
        base = now + timedelta(days=day_offset)
    elif weekday is not None:
        ahead = (weekday - now.weekday()) % 7 or 7
        base = now + timedelta(days=ahead)
    spec.day_offset = (base.date() - now.date()).days
    spec.has_date = explicit_day
    spec.part = part

    if hour is not None:
        h = _resolve_hour(hour, pm_hint, part, explicit_day)
        when = base.replace(hour=h, minute=minute or 0, second=0, microsecond=0)
        if not explicit_day and when <= now:
            # bare "9 mani" already past today: try the PM reading, else tomorrow
            if pm_hint is None and h < 12 and when.replace(hour=h + 12) > now:
                when = when.replace(hour=h + 12)
            else:
                when += timedelta(days=1)
        spec.when, spec.has_time = when, True
    elif part is not None:
        default_h = {"morning": 9, "afternoon": 13, "evening": 18, "night": 21}[part]
        spec.when = base.replace(hour=default_h, minute=0, second=0, microsecond=0)
        spec.has_time = False
    else:
        spec.when = base.replace(hour=9, minute=0, second=0, microsecond=0)
        spec.has_time = False
    return spec
