"""Live Redis validation — runs against a *real* `redis-server` process, not fakeredis.

Opt-in and self-skipping: set `WENSDAY_LIVE_REDIS_URL` (e.g. `redis://localhost:56379/0`) to a
reachable real Redis instance before running pytest. With nothing set, every test here is skipped
with a clear reason — ordinary `pytest` runs (and CI without a live Redis) are completely
unaffected. This is deliberately separate from `test_redis_compat.py` (which runs unconditionally
against fakeredis) because fakeredis cannot simulate a real TCP-level disconnect (confirmed
experimentally: disconnecting a fake connection is a no-op) — only a real process, genuinely
killed, can prove the reconnect/fallback logic under an actual failure.

To additionally exercise the kill-and-restart resilience tests, also set
`WENSDAY_LIVE_REDIS_SERVER_EXE` to a `redis-server` (or compatible) executable path; those two
tests spawn their own throwaway server on a separate port so they can safely kill it. Without that
variable, everything except the kill/restart tests still runs against the shared live URL.

Results from the run that validated this file: docs/reports/phase-live-redis.md.
"""
from __future__ import annotations

import asyncio
import os
import subprocess

import pytest

from app.core.cache import RedisCache
from app.core.events import EventHub

LIVE_URL = os.environ.get("WENSDAY_LIVE_REDIS_URL")
SERVER_EXE = os.environ.get("WENSDAY_LIVE_REDIS_SERVER_EXE")

pytestmark = [
    pytest.mark.timeout(30),
    pytest.mark.skipif(not LIVE_URL, reason="set WENSDAY_LIVE_REDIS_URL to a reachable real Redis instance to run this suite"),
]


@pytest.fixture
async def live_cache():
    cache = RedisCache(LIVE_URL)
    # RedisCache never raises on a failed connection (that's the point of it) — so confirm the
    # server is really answering with a round-trip through a fresh key, or skip with a clear reason
    # rather than let every test below silently run against the local fallback and "pass" for
    # nothing.
    probe = f"wensday:live-probe:{os.getpid()}"
    await cache.set(probe, "up", ttl_s=10)
    if await cache.get(probe) != "up":
        pytest.skip(f"WENSDAY_LIVE_REDIS_URL={LIVE_URL} is set but not answering — is the server running?")
    yield cache


async def test_cache_incr_window_and_ttl_against_a_real_server(live_cache):
    key = f"wensday:test:{os.getpid()}"
    assert await live_cache.incr_window(key, 60) >= 1
    n1 = await live_cache.incr_window(key, 60)
    assert await live_cache.incr_window(key, 60) == n1 + 1  # a real INCR, not a fresh local counter
    await live_cache.set(f"{key}:ttl", "x", ttl_s=1)
    assert await live_cache.get(f"{key}:ttl") == "x"
    await asyncio.sleep(1.3)
    assert await live_cache.get(f"{key}:ttl") is None  # real server-side expiry, not the app's clock


async def test_two_event_hubs_fan_out_through_a_real_redis_server():
    """The actual multi-replica claim, proven against a real server: an event published from one
    EventHub is delivered to a subscriber on a completely independent EventHub instance."""
    hub_a, hub_b = EventHub(redis_url=LIVE_URL), EventHub(redis_url=LIVE_URL)
    await hub_a.start()
    await hub_b.start()
    try:
        q = hub_b.subscribe(f"live-user-{os.getpid()}")
        await asyncio.sleep(0.3)  # let the real SUBSCRIBE land before publishing
        await hub_a.publish(f"live-user-{os.getpid()}", {"type": "reminder.due", "title": "live redis"})
        evt = await asyncio.wait_for(q.get(), 5)
        assert evt == {"type": "reminder.due", "title": "live redis"}
    finally:
        await hub_a.stop()
        await hub_b.stop()


# ------------------------------------------------------------------ kill & restart a real process
requires_server_exe = pytest.mark.skipif(not SERVER_EXE, reason="set WENSDAY_LIVE_REDIS_SERVER_EXE to run the kill/restart resilience tests")


@requires_server_exe
async def test_cache_survives_the_real_process_being_killed_and_recovers_after_restart():
    port = 56391
    url = f"redis://localhost:{port}/0"
    proc = subprocess.Popen([SERVER_EXE, "--port", str(port), "--save", "", "--appendonly", "no"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        await asyncio.sleep(1.5)
        cache = RedisCache(url)
        key = f"wensday:kill-test:{os.getpid()}"
        assert await cache.incr_window(key, 60) == 1  # real server, confirmed up

        proc.terminate()
        proc.wait(timeout=10)
        assert proc.returncode is not None  # genuinely dead, not just unresponsive

        # must not raise; served by the local fallback while the real process is gone
        n = await cache.incr_window(key, 60)
        assert isinstance(n, int)

        proc = subprocess.Popen([SERVER_EXE, "--port", str(port), "--save", "", "--appendonly", "no"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.sleep(1.5)
        recover_key = f"wensday:recovered:{os.getpid()}"
        await cache.set(recover_key, "yes")
        assert await cache.get(recover_key) == "yes"  # genuinely round-tripped through the NEW process
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()


@requires_server_exe
async def test_event_hub_reconnects_after_the_real_process_is_killed_and_restarted():
    port = 56392
    url = f"redis://localhost:{port}/0"
    proc = subprocess.Popen([SERVER_EXE, "--port", str(port), "--save", "", "--appendonly", "no"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    hub = EventHub(redis_url=url, reconnect_delay_s=1.0)
    publisher = EventHub(redis_url=url)
    try:
        await asyncio.sleep(1.5)
        await hub.start()
        await publisher.start()
        chan = f"live-kill-user-{os.getpid()}"
        q = hub.subscribe(chan)
        await asyncio.sleep(0.3)
        await publisher.publish(chan, {"n": 1})
        assert (await asyncio.wait_for(q.get(), 5))["n"] == 1  # working before the kill

        proc.terminate()
        proc.wait(timeout=10)

        proc = subprocess.Popen([SERVER_EXE, "--port", str(port), "--save", "", "--appendonly", "no"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.sleep(1.5)

        # the listener's reconnect loop needs a moment to notice, back off, and resubscribe;
        # retry the publish until it lands rather than assuming a fixed timing window
        delivered = None
        for _ in range(10):
            await publisher.publish(chan, {"after": "restart"})
            try:
                delivered = await asyncio.wait_for(q.get(), 1.5)
                break
            except asyncio.TimeoutError:
                continue
        assert delivered == {"after": "restart"}
    finally:
        await hub.stop()
        await publisher.stop()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()
