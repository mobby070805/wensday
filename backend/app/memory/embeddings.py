"""Embedders.

`HashingEmbedder` is the offline default and is deliberately *language-aware*: Tanglish
tokens are reduced to their phonetic skeleton and lexicon concepts are added as extra
features, so "nalaiku"/"naalaiku"/"tomorrow"/"நாளை" and "remind"/"ninaivootu" land close
together without any network call. Use `OpenAICompatEmbedder` for higher-quality vectors.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx

from app.i18n import lexicon
from app.i18n.normalize import is_tamil_token, skeleton

_WORD = re.compile(r"[஀-௿]+|[A-Za-z]+|\d+")
# Function words only: content words such as "meeting", "remind" or "tomorrow" carry the meaning
# (and are the concept anchors that tie Tanglish / Tamil / English together), so they must be kept.
_STOP = lexicon.english_function_words() | {"da", "di", "ku", "la", "ah", "nu", "wensday"}


class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _h(feature: str) -> int:
    return int.from_bytes(hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "big")


class HashingEmbedder:
    def __init__(self, dim: int = 256):
        self.dim = dim

    def features(self, text: str) -> list[tuple[str, float]]:
        feats: list[tuple[str, float]] = []
        for w in _WORD.findall(text):
            lw = w.lower()
            if lw in _STOP and not is_tamil_token(w):
                continue
            if is_tamil_token(w):
                feats.append(("t:" + lw, 1.0))
            else:
                sk = skeleton(lw)
                feats.append(("w:" + sk, 1.0))
                if len(sk) >= 5:
                    feats += [("g:" + sk[i:i + 3], 0.3) for i in range(len(sk) - 2)]
            for c in lexicon.concepts_for(w):
                if c not in {"filler", "self", "you", "and", "please"}:
                    feats.append(("c:" + c, 1.2))
        return feats

    def embed_one(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for f, weight in self.features(text):
            h = _h(f)
            v[h % self.dim] += weight if (h >> 40) & 1 else -weight
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class OpenAICompatEmbedder:
    def __init__(self, client: httpx.AsyncClient, api_key: str | None, base_url: str, model: str, dim: int):
        self._c, self._key, self._base, self._model, self.dim = client, api_key, base_url.rstrip("/"), model, dim
        self._fallback = HashingEmbedder(dim)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            r = await self._c.post(f"{self._base}/embeddings", json={"model": self._model, "input": texts}, timeout=30,
                                   headers={"Authorization": f"Bearer {self._key}"} if self._key else {})
            r.raise_for_status()
            vecs = [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
            self.dim = len(vecs[0])
            return vecs
        except (httpx.HTTPError, KeyError, ValueError, IndexError):
            return await self._fallback.embed(texts)  # degrade, don't fail the turn


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)
