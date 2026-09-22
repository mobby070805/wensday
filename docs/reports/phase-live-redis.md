# Real World Validation — Redis

**Setup:** a maintained Windows build of the real Redis server (tporadowski/redis, v5.0.14.1 — the actual `redis-server` C binary, not a reimplementation), downloaded as a portable zip (no install needed), started on `localhost:56379`. Genuine Redis server process, not a mock, not fakeredis.

## What was tested

1. **`RedisCache`/`EventHub` against a live server**: real `INCR`/`EXPIRE`, real TTL expiry (waited out the clock, not simulated), real `PUBLISH`/`SUBSCRIBE` between two independent `EventHub` instances (standing in for two API replica pods).
2. **The resilience fix from the previous session, against an actual failure**: the real `redis-server.exe` process was killed (`SIGTERM`, confirmed dead via `proc.wait()`), not simulated — something the fakeredis-based tests explicitly documented as impossible ("disconnecting a fake connection is a no-op, confirmed experimentally").
3. Recovery after restarting the killed process on the same port.

## What failed

**A real bug, found only because a real server was used.** The first live connection attempt failed:

```
Redis unreachable; falling back to local per-replica cache: unknown command `HELLO`, with args beginning with: `3`
```

`redis-py` 8.1.0 defaults to negotiating the RESP3 protocol via a `HELLO 3` handshake on connect. Redis added `HELLO`/RESP3 in version 6.0; the 5.0.14.1 server used here predates it and rejects the command outright. **Because last session's resilience fix is deliberately designed to swallow exactly this kind of connection failure and fall back to local behaviour, every single Redis operation silently ran against the in-process fallback instead of the real server — with no hard error, just one WARNING log line.** Confirmed directly: `redis-cli GET k1` after the "successful" run showed the key was never actually written to the real server.

This matters beyond this one old binary: any Redis-compatible managed service that doesn't fully implement RESP3/`HELLO` would trigger the identical silent failure in production, and an operator watching only for hard errors (not scanning WARNING logs) would never notice their Redis-backed rate limiting and cross-replica sync had quietly stopped working.

## What was fixed

`RedisCache` and `EventHub` (`app/core/cache.py`, `app/core/events.py`) now construct their Redis client with `protocol=2` explicitly, pinning RESP2 — understood by every Redis version and every Redis-compatible service, since the app uses no RESP3-only feature (client-side caching hints, push messages).

## What evidence proves it works

Re-running the identical script after the fix, against the same real server:

```
incr_window x3: [1, 2, 3]
get after set: world
get after real TTL expiry (should be None): None
pubsub received via hub_b (published from hub_a): {'type': 'reminder.due', 'title': 'Real redis test'}

$ redis-cli keys '*'
k1
$ redis-cli get k1
3                                          <- genuinely in real Redis this time, not the fallback
```

**Kill-and-restart, against the real process:**
```
--- BEFORE kill: incr_window: 1, pubsub received: {'n': 1}          (real Redis, confirmed)
--- KILLING redis-server.exe (pid=5340) now ---
process confirmed dead, exit code: 1
--- DURING outage: incr_window during outage (served by local fallback): 1    <- did not raise
--- RESTARTING redis-server.exe on the same port ---
--- AFTER restart: get(recovered) from real redis after restart: yes          <- genuinely round-tripped through the NEW process
--- AFTER restart: EventHub reconnected and delivered after restart: True     <- pubsub listener actually reconnected
=== ALL LIVE-KILL CHECKS PASSED ===
```

`tests/test_redis_compat.py::test_redis_client_pins_resp2_for_broad_server_compatibility` — a fast, always-run regression test (no live server needed) asserting `protocol=2` is passed; confirmed red without the fix, green with it. `tests/test_live_redis.py` — 4 tests including the kill-and-restart scenario as a permanent, reusable asset; skip cleanly (`4 skipped`) with no live server configured, all pass (`4 passed`) against the real server, including the two destructive kill/restart tests (gated separately behind `WENSDAY_LIVE_REDIS_SERVER_EXE` since they need their own throwaway server to safely kill).

## What risk remains

- Verified against Redis 5.0.14.1 on Windows. Production will typically run Redis 7.x on Linux (the `docker-compose.yml`/Kubernetes manifests specify `redis:7-alpine`) — not re-verified against that exact version, though RESP2 compatibility is unconditional across all Redis versions by protocol design, which is precisely why it was chosen as the fix.
- No TLS, AUTH/password, or Redis Cluster/Sentinel topology was tested — only a single unauthenticated local instance.
- The kill/restart test simulates a clean process termination (`SIGTERM`); a truly abrupt failure (power loss, OOM-kill) or a network partition (host reachable, port unresponsive) were not tested and could behave differently at the TCP level.
