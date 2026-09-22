"""Text normalisation for Tamil script, Tanglish (romanised Tamil) and English.

Tanglish has no standard spelling ("nalaiku", "naalaiku", "nalaikku" are all the
same word), so lexicon lookup goes through a phonetic *skeleton* rather than the
raw spelling.
"""
from __future__ import annotations

import re
import unicodedata

TAMIL_RANGE = (0x0B80, 0x0BFF)
_TOKEN_RE = re.compile(r"[஀-௿]+|[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?::\d{2})?(?:\.\d{2})?|[?!.,:;]")
_TAMIL_DIGITS = str.maketrans("௦௧௨௩௪௫௬௭௮௯", "0123456789")


def is_tamil_char(ch: str) -> bool:
    return TAMIL_RANGE[0] <= ord(ch) <= TAMIL_RANGE[1]


def is_tamil_token(tok: str) -> bool:
    return any(is_tamil_char(c) for c in tok)


def clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    text = text.translate(_TAMIL_DIGITS)
    # split "9am" / "9pm" / "9mani" into "9 am" so the tokenizer sees them separately
    text = re.sub(r"(\d)([A-Za-z஀-௿])", r"\1 \2", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str) -> list[str]:
    """Tokens keep original case; punctuation is returned as its own token."""
    return _TOKEN_RE.findall(clean(text))


def words(text: str) -> list[str]:
    return [t for t in tokenize(text) if t[0].isalnum() or is_tamil_token(t)]


_DIGRAPHS = (
    ("zh", "l"), ("th", "t"), ("dh", "t"), ("bh", "b"), ("kh", "k"), ("gh", "k"),
    ("sh", "s"), ("ch", "s"), ("ph", "p"), ("ny", "n"),
)
_LONG_VOWELS = (("aa", "a"), ("ee", "i"), ("ii", "i"), ("oo", "u"), ("uu", "u"), ("ei", "ai"), ("ay", "ai"))
# NB: "j" is deliberately NOT merged with "s": that made English names like "Jerry" collide with "seri".
_CONS_MAP = str.maketrans({"d": "t", "g": "k", "b": "p", "w": "v", "y": "i", "e": "i", "o": "u", "z": "l"})


def skeleton(word: str) -> str:
    """Phonetic skeleton for fuzzy Tanglish matching.

    nalaiku / naalaiku / nalaikku -> "nalaiku";  pannu / panu -> "panu";
    aagum / aakum -> "akum".
    """
    w = word.lower().replace("'", "").replace("-", "")
    for a, b in _DIGRAPHS:
        w = w.replace(a, b)
    for a, b in _LONG_VOWELS:
        w = w.replace(a, b)
    w = w.translate(_CONS_MAP)
    w = re.sub(r"(.)\1+", r"\1", w)  # collapse doubled letters
    return w


# Suffixes glued onto a stem in casual Tanglish ("officela", "meetingku", "mailah")
_TG_SUFFIXES = ("kku", "ku", "la", "lay", "ah", "aa", "a", "nu", "nnu", "um", "oda", "ode", "kum", "ala", "in")
_TA_SUFFIXES = ("க்கு", "க்கும்", "ஐ", "ஆ", "ல்", "இல்", "இலே", "யில்", "ில்", "உம்", "ம்", "னு", "ன்னு", "ஓடு", "ோடு")


def stems(token: str) -> list[str]:
    """Candidate stems of *token*, most specific first (the token itself is first)."""
    out = [token]
    low = token.lower()
    suffixes = _TA_SUFFIXES if is_tamil_token(token) else _TG_SUFFIXES
    for suf in suffixes:
        if len(low) > len(suf) + 2 and low.endswith(suf):
            out.append(low[: -len(suf)])
    return out
