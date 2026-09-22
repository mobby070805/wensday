"""Best-effort Tanglish (romanised Tamil) -> Tamil script transliteration for TTS.

A Tamil neural voice reads Tamil script naturally but spells out Latin letters, so Tanglish
words are transliterated before synthesis. The mapping is deliberately approximate
(Tamil has no t/d or n/N distinction in Latin spelling); it targets *pronounceability*.
"""
from __future__ import annotations

_PULLI = "்"
_CONS = [  # longest match first
    ("nj", "ஞ"), ("ng", "ங"), ("zh", "ழ"), ("th", "த"), ("dh", "த"), ("ch", "ச"), ("sh", "ஷ"), ("kh", "க"), ("gh", "க"),
    ("k", "க"), ("g", "க"), ("s", "ச"), ("j", "ஜ"), ("t", "ட"), ("d", "ட"), ("n", "ன"), ("p", "ப"), ("b", "ப"),
    ("m", "ம"), ("y", "ய"), ("r", "ர"), ("l", "ல"), ("v", "வ"), ("w", "வ"), ("h", "ஹ"), ("f", "ப"), ("c", "க"),
    ("q", "க"), ("x", "க்ஸ"), ("z", "ழ"),
]
_VOWELS = [  # (latin, independent, dependent sign)
    ("aa", "ஆ", "ா"), ("ee", "ஈ", "ீ"), ("ii", "ஈ", "ீ"), ("oo", "ஊ", "ூ"), ("uu", "ஊ", "ூ"),
    ("ai", "ஐ", "ை"), ("au", "ஔ", "ௌ"), ("ei", "ஐ", "ை"),
    ("a", "அ", ""), ("i", "இ", "ி"), ("u", "உ", "ு"), ("e", "எ", "ெ"), ("o", "ஒ", "ொ"),
]


def _match(table, s: str, i: int):
    for entry in table:
        if s.startswith(entry[0], i):
            return entry
    return None


def transliterate_word(word: str) -> str:
    w = word.lower()
    out: list[str] = []
    i = 0
    prev_cons: str | None = None  # a consonant awaiting its vowel sign
    while i < len(w):
        v = _match(_VOWELS, w, i)
        if v:
            latin, indep, sign = v
            out.append(sign if prev_cons is not None else indep)  # "a" after a consonant is inherent: sign is ""
            prev_cons = None
            i += len(latin)
            continue
        c = _match(_CONS, w, i)
        if not c:
            i += 1  # digits/punctuation are handled by the caller
            continue
        latin, tamil = c
        if prev_cons is not None:
            out.append(_PULLI)  # consonant cluster: previous consonant loses its vowel
        out.append(tamil)  # a repeated consonant (nn, kk, tt…) is a geminate: pulli was added above
        prev_cons = tamil
        i += len(latin)
    if prev_cons is not None:
        out.append(_PULLI)  # word-final consonant
    return "".join(out)


def transliterate(text: str) -> str:
    return " ".join(transliterate_word(w) for w in text.split())
