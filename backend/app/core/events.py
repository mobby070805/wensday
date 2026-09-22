"""Per-user event hub: pushes change/reminder events to every connected device.

In-process by default; when a Redis URL is configured, publish() also fans out through
Redis pub/sub so multiple API replicas deliver to each other's sockets.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

log = logging.getLogger("wensday.events")


class EventHub:
    def __init__(self, redis_url: str | None = None):
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._redis_url = redis_url
        self._redis = None
        self._pump: asyncio.Task | None = None

    async def start(self) -> None:
        if not self._redis_url:
            return
        try:
            import redis.asyncio as aioredis  # optional dependency

            self._redis = aioredis.from_url(self._redis_url)
            self._pump = asyncio.create_task(self._listen())
        except Exception:  # noqa: BLE001 - fall back to in-process delivery
            log.warning("redis unavailable; events stay in-process", exc_info=True)
            self._redis = None

    async def stop(self) -> None:
        if self._pump:
            self._pump.cancel()
        if self._redis:
            await self._redis.aclose()

    def subscribe(self, user_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs[user_id].add(q)
        return q

    def unsubscribe(self, user_id: str, q: asyncio.Queue) -> None:
        self._subs[user_id].discard(q)
        if not self._subs[user_id]:
            self._subs.pop(user_id, None)

    def _deliver_local(self, user_id: str, event: dict[str, Any]) -> None:
        for q in list(self._subs.get(user_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # slow consumer: drop oldest
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:  # noqa: BLE001
                    pass

    async def publish(self, user_id: str, event: dict[str, Any]) -> None:
        if self._redis:
            try:
                await self._redis.publish("wensday:events", json.dumps({"u": user_id, "e": event}))
                return
            except Exception:  # noqa: BLE001
                log.warning("redis publish failed; delivering locally", exc_info=True)
        self._deliver_local(user_id, event)

    async def _listen(self) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe("wensday:events")
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                try:
                    data = json.loads(msg["data"])
                    self._deliver_local(data["u"], data["e"])
                except Exception:  # noqa: BLE001
                    log.exception("bad event payload")
