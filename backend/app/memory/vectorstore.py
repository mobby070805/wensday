"""Vector stores: in-process (dev/test/offline) and Qdrant (production, via its REST API)."""
from __future__ import annotations

import uuid
from typing import Protocol

import httpx

from .embeddings import cosine

Hit = tuple[str, float, dict]  # (id, score, payload)


class VectorStore(Protocol):
    persistent: bool

    async def upsert(self, collection: str, id: str, vector: list[float], payload: dict) -> None: ...
    async def search(self, collection: str, vector: list[float], k: int, where: dict) -> list[Hit]: ...
    async def delete(self, collection: str, id: str) -> None: ...


class InMemoryVectorStore:
    persistent = False  # rebuilt from the database on start (see MemoryEngine.reindex)

    def __init__(self) -> None:
        self._c: dict[str, dict[str, tuple[list[float], dict]]] = {}

    async def upsert(self, collection, id, vector, payload):
        self._c.setdefault(collection, {})[id] = (vector, payload)

    async def search(self, collection, vector, k, where):
        hits = [(i, cosine(vector, v), p) for i, (v, p) in self._c.get(collection, {}).items()
                if all(p.get(key) == val for key, val in where.items())]
        return sorted(hits, key=lambda h: h[1], reverse=True)[:k]

    async def delete(self, collection, id):
        self._c.get(collection, {}).pop(id, None)


class QdrantStore:
    persistent = True

    def __init__(self, client: httpx.AsyncClient, url: str, api_key: str | None = None, dim: int = 256):
        self._c, self._base, self._dim = client, url.rstrip("/"), dim
        self._headers = {"api-key": api_key} if api_key else {}
        self._ready: set[str] = set()

    @staticmethod
    def _pid(id: str) -> str:  # Qdrant point ids must be UUIDs or ints
        return str(uuid.UUID(id)) if len(id) == 32 else str(uuid.uuid5(uuid.NAMESPACE_OID, id))

    async def _ensure(self, collection: str) -> None:
        if collection in self._ready:
            return
        r = await self._c.get(f"{self._base}/collections/{collection}", headers=self._headers)
        if r.status_code == 404:
            r = await self._c.put(f"{self._base}/collections/{collection}", headers=self._headers,
                                  json={"vectors": {"size": self._dim, "distance": "Cosine"}})
        r.raise_for_status()
        self._ready.add(collection)

    async def upsert(self, collection, id, vector, payload):
        await self._ensure(collection)
        r = await self._c.put(f"{self._base}/collections/{collection}/points?wait=true", headers=self._headers,
                              json={"points": [{"id": self._pid(id), "vector": vector, "payload": {**payload, "_id": id}}]})
        r.raise_for_status()

    async def search(self, collection, vector, k, where):
        await self._ensure(collection)
        body = {"vector": vector, "limit": k, "with_payload": True,
                "filter": {"must": [{"key": key, "match": {"value": val}} for key, val in where.items()]}}
        r = await self._c.post(f"{self._base}/collections/{collection}/points/search", headers=self._headers, json=body)
        r.raise_for_status()
        return [(h["payload"]["_id"], h["score"], h["payload"]) for h in r.json()["result"]]

    async def delete(self, collection, id):
        await self._ensure(collection)
        r = await self._c.post(f"{self._base}/collections/{collection}/points/delete?wait=true", headers=self._headers,
                               json={"points": [self._pid(id)]})
        r.raise_for_status()
