"""Per-utterance language detection: Tamil script, English, or Tanglish.

Tanglish (Tamil in Latin letters) can't be detected by script, so we score
Tanglish-lexicon hits against English function-word hits. Code-switching is a
first-class outcome (`mixed=True`), not an error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from . import lexicon
from .normalize import is_tamil_char, is_tamil_token, words

Lang = Literal["ta", "en", "tanglish"]

_CASUAL = {"da", "di", "dei", "machan", "bro", "pa", "ma", "டா", "டி", "மச்சான்"}
_RESPECT = {"sir", "madam", "ma'am", "neenga", "nenga", "unga", "please", "pannunga", "sollunga", "நீங்கள்", "நீங்க", "தயவுசெய்து"}


@dataclass(frozen=True)
class LangProfile:
    lang: Lang
    mixed: bool = False          # code-switching between Tamil-ish and English in one utterance
    register: str = "neutral"    # casual | respectful | neutral
    confidence: float = 0.5
    scores: dict = field(default_factory=dict)

    @property
    def style(self) -> str:
        """Reply style key used by the persona layer: ta | en | tg."""
        if self.lang == "ta":
            return "ta"
        if self.lang == "en":
            return "en"
        return "tg"


def detect(text: str) -> LangProfile:
    toks = words(text)
    if not toks:
        return LangProfile("en", confidence=0.0)

    letters = [c for c in text if c.isalpha()]
    tamil_letters = sum(1 for c in letters if is_tamil_char(c))
    tamil_share = tamil_letters / len(letters) if letters else 0.0

    latin = [t for t in toks if not is_tamil_token(t) and not t.isdigit() and t[0].isalpha()]
    tamil_toks = [t for t in toks if is_tamil_token(t)]

    tg_hits = sum(1 for t in latin if lexicon.is_tanglish_word(t))
    en_hits = sum(1 for t in latin if t.lower() in lexicon.english_function_words() and t.lower() not in lexicon.tanglish_words())
    en_other = len(latin) - tg_hits - en_hits  # unknown Latin words: usually English content words

    low = {t.lower() for t in toks}
    register = "neutral"
    if low & _CASUAL:
        register = "casual"
    elif low & _RESPECT:
        register = "respectful"

    scores = {"tamil_share": round(tamil_share, 2), "tg": tg_hits, "en": en_hits, "other": en_other}

    if tamil_share >= 0.5:
        mixed = len(latin) >= 2
        return LangProfile("ta", mixed, register, min(1.0, 0.6 + tamil_share * 0.4), scores)

    if tamil_toks:  # a little Tamil script among Latin words -> treat as Tanglish-style mixing
        return LangProfile("tanglish", True, register, 0.7, scores)

    if tg_hits == 0:
        return LangProfile("en", False, register, min(1.0, 0.6 + 0.1 * en_hits), scores)

    # Tanglish when Tamil-marker density is meaningful relative to function-word English
    total = tg_hits + en_hits
    ratio = tg_hits / total if total else 1.0
    if ratio >= 0.34 or tg_hits >= 2 or len(toks) <= 3:
        mixed = (en_hits + en_other) > 0
        return LangProfile("tanglish", mixed, register, min(1.0, 0.5 + 0.15 * tg_hits), scores)
    return LangProfile("en", True, register, 0.5, scores)


def detect_conversation(recent: list[LangProfile]) -> LangProfile | None:
    """Smooth over short/ambiguous turns: return the majority style of recent profiles."""
    if not recent:
        return None
    counts: dict[str, int] = {}
    for p in recent:
        counts[p.lang] = counts.get(p.lang, 0) + 1
    top = max(counts, key=counts.get)
    return next(p for p in reversed(recent) if p.lang == top)
