"""Extract explicit user facts from Tamil / English / Tanglish utterances.

    "my name is Madesh"                    "en peyar Madesh"                 "என் பெயர் மதேஷ்"
    "call me Mads"                         "ennai Mads nu koopidu"
    "I love filter coffee"                 "enaku filter coffee romba pidikkum"
    "speak in Tamil"                       "tamil la pesu"                   "தமிழில் பேசு"
    "remember that my anniversary is 5 Dec"  "amma birthday March 3 nyabagam vechuko"
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_I = re.I


@dataclass(frozen=True)
class Fact:
    type: str          # name | like | language | remember
    key: str           # preference key or "" for free-text
    value: str
    text: str          # natural-language memory text
    importance: float


# "call me later / back / tomorrow" is a request, not a name
_NOT_NAMES = {"later", "back", "tomorrow", "tonight", "today", "now", "soon", "please", "when", "maybe", "again", "if", "at", "in", "on",
              "anytime", "asap", "first", "after", "before", "then", "sir", "madam", "ok", "okay", "da", "di", "the", "a"}

_LANG_WORDS = {"tamil": "ta", "english": "en", "tanglish": "tanglish", "தமிழ்": "ta", "தமிழில்": "ta"}


def extract_facts(text: str) -> list[Fact]:
    t = text.strip()
    out: list[Fact] = []

    for rx in (
        r"\b(?:my name is|i am called|i'm called|call me)\s+([A-Za-z][\w'-]{1,30})",
        r"\b(?:en peyar|en per|ennoda peyar|en name)\s+([A-Za-z][\w'-]{1,30})",
        r"\bennai\s+([A-Za-z][\w'-]{1,30})\s+(?:nu|nnu)\s+(?:koopidu|koopidunga|kooppidu|kupidu)",
        r"என் (?:பெயர்|பேர்)\s+(\S+)",
        r"என்னை\s+(\S+)\s+(?:ன்னு|என்று)\s+(?:கூப்பிடு|அழை)",
    ):
        m = re.search(rx, t, _I)
        if m and m.group(1).strip(".,!?").lower() not in _NOT_NAMES:
            name = m.group(1).strip(".,!?").title()
            out.append(Fact("name", "name", name, f"The user's name is {name}.", 0.95))
            break

    for rx in (
        r"\b(?:speak|reply|talk|respond)\s+(?:to me\s+)?in\s+(tamil|english|tanglish)\b",
        r"\b(tamil|english|tanglish)\s+(?:la|le)\s+(?:pesu|pesunga|sollu|reply|pesuven)\b",
        r"(தமிழில்|தமிழ்)\s+(?:பேசு|பேசுங்க)",
    ):
        m = re.search(rx, t, _I)
        if m:
            lang = _LANG_WORDS[m.group(1).lower()]
            out.append(Fact("language", "language", lang, f"The user prefers replies in {lang}.", 0.9))
            break

    for rx in (
        r"\bi\s+(?:really\s+)?(?:like|love|prefer|enjoy)\s+(.+?)[.!]*$",
        r"\benaku\s+(.+?)\s+(?:romba\s+)?(?:pidikkum|pidikum|pudikkum|pudikum)\b",
        r"எனக்கு\s+(.+?)\s+(?:ரொம்ப\s+)?பிடிக்கும்",
    ):
        m = re.search(rx, t, _I)
        if m:
            thing = m.group(1).strip(" .,!?")
            if thing and len(thing) < 80:
                out.append(Fact("like", "", thing, f"The user likes {thing}.", 0.7))
                break

    for rx in (
        r"\bremember (?:that\s+)?(.+?)[.!]*$",
        r"(.+?)\s+(?:nyabagam|gnabagam|ninaivula|ninaivil)\s+(?:vechuko|vachuko|vechikko|vachiko|vechukko)\b",
        r"(.+?)\s+நினைவில்\s+வைத்துக்கொள்",
    ):
        m = re.search(rx, t, _I)
        if m:
            body = m.group(1).strip(" .,!?")
            if body:
                out.append(Fact("remember", "", body, body[0].upper() + body[1:] + ".", 0.9))
                break
    return out
