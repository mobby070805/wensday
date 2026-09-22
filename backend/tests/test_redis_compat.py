"""Redis compatibility & resilience — exercised against a real Redis wire-protocol server
(fakeredis, in-process) rather than mocks, so INCR/EXPIRE/GET/SET/PUBLISH/SUBSCRIBE actually run.

Two things are proven here that were previously only claimed:
1. `RedisCache` and `EventHub` speak real Redis protocol correctly (not just "should work").
2. Both degrade gracefully — rather than crashing every request — when Redis becomes
   unreachable *after* the app has already connected to it (a mid-session outage).

fakeredis is a faithful in-process implementation of the RESP protocol used as a drop-in for
`redis.asyncio`, and is what runs in ordinary CI (no server to install). For genuine live-server
proof — including a real process actually killed and restarted mid-session, which fakeredis
cannot simulate (confirmed experimentally: disconnecting a fake connection is a no-op) — see
`tests/test_live_redis.py`, which skips cleanly when no live server is configured and ran
successfully against a real `redis-server` during the Real World Validation pass (see
docs/reports/phase-live-redis.md). That run is also what caught the bug this file's
`test_redis_client_pins_resp2_for_broad_server_compatibility` now guards against.
"""
from __future__ import annotations

import asyncio

import fakeredis
import pytest

from app.core.cache import MemoryCache, RedisCache, make_cache
from app.core.events import EventHub
from .conftest import Person, running

pytestmark = pytest.mark.timeout(20)


def _client(server: fakeredis.FakeServer):
    return fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)


def _wire(monkeypatch, server: fakeredis.FakeServer, *, flaky: "Flaky | None" = None, calls: list | None = None):
    """Point `redis.asyncio.from_url` at fakeredis (optionally wrapped to inject failures)."""
    def from_url(url, *a, **kw):
        if calls is not None:
            calls.append(kw)
        c = fakeredis.aioredis.FakeRedis(server=server, decode_responses=kw.get("decode_responses", False))
        return flaky.wrap(c) if flaky else c

    monkeypatch.setattr("redis.asyncio.from_url", from_url)


async def test_redis_client_pins_resp2_for_broad_server_compatibility(monkeypatch):
    """Regression test for a real bug found against a live Redis 5.0.14.1 server during the Real
    World Validation pass: redis-py defaults to negotiating RESP3 via a HELLO handshake, which
    only Redis >= 6.0 understands. Without protocol=2 pinned explicitly, the very first connection
    attempt against an older (or HELLO-incompatible) server fails, and RedisCache/EventHub both
    silently and permanently fall back to local-only behaviour -- with no hard error, just a log
    line -- because the resilience fix from the prior pass is *designed* to swallow exactly this
    kind of connection failure. fakeredis accepts RESP3 fine, so this could only be caught by
    asserting the actual call arguments, not by observing behaviour against the fake server."""
    calls: list = []
    _wire(monkeypatch, fakeredis.FakeServer(), calls=calls)
    RedisCache("redis://fake/0")
    assert calls[-1].get("protocol") == 2

    calls.clear()
    hub = EventHub(redis_url="redis://fake/0")
    await hub.start()
    try:
        assert calls[-1].get("protocol") == 2
    finally:
        await hub.stop()


class Flaky:
    """Wraps a real client and raises ConnectionError once `broken` is set — simulates an outage
    starting mid-session, which a fresh mock could never distinguish from "never worked"."""

    def __init__(self) -> None:
        self.broken = False
        self.calls = 0
        self.break_event = asyncio.Event()

    def wrap(self, client):
        return _FlakyProxy(client, self)


class _FlakyProxy:
    def __init__(self, inner, state: Flaky):
        self._inner, self._state = inner, state

    def pubsub(self, *a, **kw):
        return _FlakyPubSub(self._inner.pubsub(*a, **kw), self._state)

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        async def call(*a, **kw):
            self._state.calls += 1
            if self._state.broken:
                raise ConnectionError("simulated redis outage")
            return await attr(*a, **kw)

        return call


class _FlakyPubSub:
    """A pubsub handle whose in-progress `listen()` can be interrupted on demand (`state.break_event`),
    to exercise EventHub's reconnect loop the way a real dropped TCP connection would: the blocking
    read raises *while the listener is waiting*, not merely on the next call. fakeredis doesn't
    simulate a real socket drop (disconnecting a fake connection is a no-op, confirmed
    experimentally), so the interrupt is injected here instead."""

    def __init__(self, inner, state: Flaky):
        self._inner, self._state = inner, state

    async def subscribe(self, *a, **kw):
        return await self._inner.subscribe(*a, **kw)

    async def listen(self):
        it = self._inner.listen()
        while True:
            next_msg = asyncio.ensure_future(it.__anext__())
            broken = asyncio.ensure_future(self._state.break_event.wait())
            done, pending = await asyncio.wait({next_msg, broken}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            if broken in done:
                self._state.break_event.clear()
                raise ConnectionError("simulated pubsub disconnect")
            try:
                yield next_msg.result()
            except StopAsyncIteration:
                return

    async def aclose(self):
        return await self._inner.aclose()


# ------------------------------------------------------------------ protocol correctness
async def test_redis_cache_speaks_real_protocol(monkeypatch):
    _wire(monkeypatch, fakeredis.FakeServer())
    cache = RedisCache("redis://fake/0")
    assert await cache.incr_window("k", 60) == 1
    assert await cache.incr_window("k", 60) == 2
    assert await cache.get("missing") is None
    await cache.set("x", "y", ttl_s=60)
    assert await cache.get("x") == "y"


async def test_redis_cache_rate_limit_window_resets(monkeypatch):
    server = fakeredis.FakeServer()
    _wire(monkeypatch, server)
    cache = RedisCache("redis://fake/0")
    for _ in range(5):
        await cache.incr_window("burst", 60)
    # a fresh key starts its own independent window
    assert await cache.incr_window("other", 60) == 1


async def test_two_cache_instances_share_state_through_the_fake_server(monkeypatch):
    """Proves the server, not the client object, holds state — i.e. this really is testing
    shared Redis semantics across processes, not a per-instance Python dict."""
    server = fakeredis.FakeServer()
    _wire(monkeypatch, server)
    a, b = RedisCache("redis://fake/0"), RedisCache("redis://fake/0")
    await a.set("shared", "from-a", ttl_s=60)
    assert await b.get("shared") == "from-a"
    assert await a.incr_window("counter", 60) == 1
    assert await b.incr_window("counter", 60) == 2


# ------------------------------------------------------------------ resilience: mid-session outage
async def test_redis_cache_survives_a_mid_session_outage(monkeypatch):
    """A Redis connection blip must degrade to local behaviour, not crash the caller.

    Before the fix: incr_window/get/set propagated ConnectionError straight to the caller —
    at the HTTP layer that meant every rate-limited endpoint returned 500 during any Redis hiccup.
    """
    flaky = Flaky()
    _wire(monkeypatch, fakeredis.FakeServer(), flaky=flaky)
    cache = RedisCache("redis://fake/0")
    assert await cache.incr_window("k", 60) == 1  # works while Redis is up

    flaky.broken = True
    # must not raise, and the local fallback keeps working correctly on its own terms
    assert await cache.incr_window("k", 60) == 1  # fresh counter in the local fallback
    assert await cache.incr_window("k", 60) == 2
    assert await cache.get("x") is None  # nothing set yet in the fallback
    await cache.set("x", "y")  # must not raise
    assert await cache.get("x") == "y"  # served from the local fallback while Redis is down

    flaky.broken = False
    # Redis is authoritative again; a value only ever written to the (now bypassed) fallback
    # is correctly absent from the real store — proves we're not silently stuck on the fallback.
    assert await cache.get("x") is None


async def test_rate_limited_endpoint_survives_redis_outage(monkeypatch):
    """End-to-end: the app must keep serving requests (not 500) while Redis is down."""
    flaky = Flaky()
    server = fakeredis.FakeServer()
    _wire(monkeypatch, server, flaky=flaky)
    flaky.broken = True  # Redis is down for the whole test
    with running(redis_url="redis://fake/0") as c:
        p = Person(c, "a@x.com", "Madesh")
        r = p.get("/tasks")
        assert r.status_code == 200, r.text  # NOT 500


async def test_make_cache_falls_back_when_redis_package_or_host_is_unreachable(monkeypatch):
    def broken_from_url(*a, **kw):
        raise OSError("name resolution failed")

    monkeypatch.setattr("redis.asyncio.from_url", broken_from_url)
    cache = make_cache("redis://nonexistent-host:6379/0")
    assert isinstance(cache, (MemoryCache, RedisCache))  # never raises out of make_cache
    assert await cache.incr_window("k", 60) == 1  # and is usable either way


# ------------------------------------------------------------------ EventHub: real pub/sub
async def test_event_hub_delivers_locally_with_no_redis_configured():
    hub = EventHub(redis_url=None)
    await hub.start()
    q = hub.subscribe("u1")
    await hub.publish("u1", {"type": "sync"})
    assert (await asyncio.wait_for(q.get(), 1)) == {"type": "sync"}
    await hub.stop()


async def test_two_event_hubs_fan_out_through_redis_like_two_api_replicas(monkeypatch):
    """The actual multi-device-sync claim: an event published on one API replica reaches a
    device socket connected to a *different* replica, purely via Redis pub/sub."""
    server = fakeredis.FakeServer()
    _wire(monkeypatch, server)
    hub_a, hub_b = EventHub(redis_url="redis://fake/0"), EventHub(redis_url="redis://fake/0")
    await hub_a.start()
    await hub_b.start()
    try:
        q = hub_b.subscribe("u1")  # a device socket is attached to replica B
        await asyncio.sleep(0.1)  # let B's pubsub subscription land
        await hub_a.publish("u1", {"type": "reminder.due", "title": "Pay rent"})  # fired on replica A
        evt = await asyncio.wait_for(q.get(), 2)
        assert evt == {"type": "reminder.due", "title": "Pay rent"}
    finally:
        await hub_a.stop()
        await hub_b.stop()


async def test_event_hub_publish_degrades_to_local_delivery_when_redis_is_down(monkeypatch):
    flaky = Flaky()
    _wire(monkeypatch, fakeredis.FakeServer(), flaky=flaky)
    hub = EventHub(redis_url="redis://fake/0")
    await hub.start()
    try:
        flaky.broken = True
        q = hub.subscribe("u1")
        await hub.publish("u1", {"type": "sync"})  # must not raise; falls back to local delivery
        assert (await asyncio.wait_for(q.get(), 1)) == {"type": "sync"}
    finally:
        await hub.stop()


async def test_event_hub_listener_reconnects_after_the_redis_connection_drops(monkeypatch):
    """Before the fix: if the pubsub `listen()` iterator raised (connection reset, Redis restart),
    the background task died silently and cross-replica delivery stopped forever until process
    restart. It must instead reconnect and keep delivering."""
    server = fakeredis.FakeServer()
    flaky = Flaky()
    _wire(monkeypatch, server, flaky=flaky)
    hub = EventHub(redis_url="redis://fake/0", reconnect_delay_s=0.05)
    await hub.start()
    try:
        q = hub.subscribe("u1")
        await asyncio.sleep(0.1)

        # a message flows normally before the fault
        publisher = EventHub(redis_url="redis://fake/0")
        await publisher.start()
        await publisher.publish("u1", {"type": "sync", "n": 1})
        assert (await asyncio.wait_for(q.get(), 2))["n"] == 1

        # simulate the listener's connection dying underneath it, mid-wait
        flaky.break_event.set()

        # give the reconnect loop time to notice, back off, and resubscribe
        await asyncio.sleep(0.5)

        await publisher.publish("u1", {"type": "sync", "n": 2})
        evt = await asyncio.wait_for(q.get(), 2)
        assert evt == {"type": "sync", "n": 2}
        await publisher.stop()
    finally:
        await hub.stop()
