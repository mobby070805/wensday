"""Split a reply into language runs so each run is spoken by the right voice.

Tamil script            -> Tamil voice
Tanglish words          -> transliterated to Tamil script -> Tamil voice
English words / names   -> English (en-IN) voice
Numbers/times/symbols   -> attach to the neighbouring run (so "9:00 AM-ku" isn't cut into pieces)
"""
from __future__ import annotations

import re

from app.config import Settings
from app.i18n import lexicon
from app.i18n.normalize import is_tamil_token
from app.schemas import SpeechSegment
from .translit import transliterate_word

_TOKEN = re.compile(r"\s+|[஀-௿]+|[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:[:.]\d+)?|[^\sA-Za-z\d஀-௿]")


def _classify(tok: str, style: str) -> str | None:
    if is_tamil_token(tok):
        return "ta"
    if tok[0].isalpha():
        if style != "en" and lexicon.is_tanglish_word(tok):
            return "ta"
        return "en"
    return None  # number / punctuation


def split_speech(reply: str, style: str, settings: Settings) -> list[SpeechSegment]:
    runs: list[list] = []  # [lang, text]
    for m in _TOKEN.finditer(reply):
        tok = m.group(0)
        if tok.isspace():
            if runs:
                runs[-1][1] += tok
            continue
        lang = _classify(tok, style)
        if lang is None:
            if runs:
                runs[-1][1] += tok
            else:
                runs.append(["", tok])
            continue
        text = transliterate_word(tok) if lang == "ta" and not is_tamil_token(tok) else tok
        if runs and runs[-1][0] in ("", lang):
            runs[-1][0] = lang
            runs[-1][1] += text
        else:
            runs.append([lang, text])
    segs = []
    for lang, text in runs:
        text = text.strip()
        if text:
            lang = lang or ("ta" if style == "ta" else "en")
            segs.append(SpeechSegment(text=text, lang=lang, voice=settings.voice_ta if lang == "ta" else settings.voice_en))
    return segs


def to_ssml(segments: list[SpeechSegment], rate: str = "default") -> str:
    """Azure-style SSML with per-run voices (also usable by other SSML-capable TTS)."""
    from xml.sax.saxutils import escape

    body = "".join(
        f'<voice name="{s.voice}"><lang xml:lang="{"ta-IN" if s.lang == "ta" else "en-IN"}">'
        f'<prosody rate="{rate}">{escape(s.text)}</prosody></lang></voice>' for s in segments)
    return f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-IN">{body}</speak>'
