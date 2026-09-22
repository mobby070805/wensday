"""Tiny cache/rate-limit abstraction: Redis when configured, in-memory otherwise."""
from __future__ import annotations

import logging
import time
from typing import Protocol

log = logging.getLogger("wensday.cache")


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
    """A `RedisCache` that stops being reachable mid-session (network blip, Redis restart,
    failover) must not take the API down with it: every operation falls back to a local,
    per-replica `MemoryCache` for the duration of the outage rather than raising. This matters
    because `incr_window` backs the rate-limit dependency used on almost every route — an
    unhandled exception there would 500 the whole API on any Redis hiccup.

    The fallback is per-replica and resets when Redis recovers (the next successful call wins),
    which is the right trade-off for a rate limiter: slightly looser limits during an outage
    beat an outage of the whole product.
    """

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis

        # protocol=2 (RESP2) is explicit and deliberate: redis-py defaults to negotiating RESP3
        # via a HELLO handshake on connect, which only Redis >= 6.0 understands. Anything older,
        # or many "Redis-compatible" managed services, reject HELLO outright -- verified against
        # a real redis-server 5.0.14.1: every single call silently fell back to the in-process
        # cache without RESP2 pinned, because the very first connection attempt failed. RESP2 is
        # understood by every Redis version and every compatible service; we use no RESP3-only
        # feature (client-side caching, push messages), so there is no downside to pinning it.
        self._r = aioredis.from_url(url, decode_responses=True, protocol=2)
        self._fallback = MemoryCache()
        self._healthy = True  # only used to throttle logging, not to gate behaviour

    def _note(self, ok: bool, exc: Exception | None = None) -> None:
        if ok and not self._healthy:
            log.warning("Redis connection recovered")
        elif not ok and self._healthy:
            log.warning("Redis unreachable; falling back to local per-replica cache: %s", exc)
        self._healthy = ok

    async def incr_window(self, key: str, window_s: int) -> int:
        try:
            n = await self._r.incr(key)
            if n == 1:
                await self._r.expire(key, window_s)
            self._note(True)
            return int(n)
        except Exception as e:  # noqa: BLE001 - any Redis failure degrades, never propagates
            self._note(False, e)
            return await self._fallback.incr_window(key, window_s)

    async def get(self, key: str) -> str | None:
        try:
            v = await self._r.get(key)
            self._note(True)
            return v
        except Exception as e:  # noqa: BLE001
            self._note(False, e)
            return await self._fallback.get(key)

    async def set(self, key: str, value: str, ttl_s: int | None = None) -> None:
        try:
            await self._r.set(key, value, ex=ttl_s)
            self._note(True)
        except Exception as e:  # noqa: BLE001
            self._note(False, e)
            await self._fallback.set(key, value, ttl_s)


def make_cache(redis_url: str | None) -> Cache:
    if redis_url:
        try:
            return RedisCache(redis_url)
        except Exception:  # noqa: BLE001 - redis package missing -> degrade gracefully
            pass
    return MemoryCache()
