"""Tiny cache/rate-limit abstraction: Redis when configured, in-memory otherwise."""
from __future__ import annotations

import time
from typing import Protocol


class Cache(Protocol):
    async def incr_window(self, key: str, window_s: int) -> int: ...
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_s: int | None = None) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self._windows: dict[str, tuple[int, float]] = {}

    async def incr_window(self, key: str, window_s: int) -> int:
        now = time.monotonic()
        count, start = self._windows.get(key, (0, now))
        if now - start >= window_s:
            count, start = 0, now
        count += 1
        self._windows[key] = (count, start)
        return count

    async def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if not item:
            return None
        value, exp = item
        if exp is not None and exp < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl_s: int | None = None) -> None:
        self._data[key] = (value, time.monotonic() + ttl_s if ttl_s else None)


class RedisCache:
    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis

        self._r = aioredis.from_url(url, decode_responses=True)

    async def incr_window(self, key: str, window_s: int) -> int:
        n = await self._r.incr(key)
        if n == 1:
            await self._r.expire(key, window_s)
        return int(n)

    async def get(self, key: str) -> str | None:
        return await self._r.get(key)

    async def set(self, key: str, value: str, ttl_s: int | None = None) -> None:
        await self._r.set(key, value, ex=ttl_s)


def make_cache(redis_url: str | None) -> Cache:
    if redis_url:
        try:
            return RedisCache(redis_url)
        except Exception:  # noqa: BLE001 - redis package missing -> degrade gracefully
            pass
    return MemoryCache()
