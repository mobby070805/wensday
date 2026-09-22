# Real-environment integration validation checklist

One entry per integration named in the Real World Validation mission. For each: what "validated" means concretely, whether it was possible in this environment, and the result.

| Integration | What validation means | Possible here? | Result |
|---|---|:-:|---|
| **PostgreSQL** | Real `alembic upgrade head`/`downgrade base` against a live server; the actual app (not a script) performing real CRUD, UNIQUE-constraint conflicts, `ON DELETE CASCADE`, UTF-8/JSON round-trips | ✅ Yes — portable binaries, no admin/Docker needed | **Done — see [phase-live-postgres.md](phase-live-postgres.md).** 6 new tests, all passing against real PostgreSQL 16.4. |
| **Redis** | The app's actual `RedisCache`/`EventHub` against a live `redis-server`, including a genuine kill-and-restart | ✅ Yes — portable binary, no admin/Docker needed | **Done — see [phase-live-redis.md](phase-live-redis.md).** Found and fixed a real bug (RESP3/HELLO incompatibility). 4 new tests, all passing against a real, killed-and-restarted server. |
| **Gmail** (send) | OAuth consent completed by a real Google account, a real message delivered to a real inbox | ❌ No — needs a Google Cloud OAuth client, a real Google account, and an interactive browser consent flow. None are available in a non-interactive sandboxed CLI session. | **Not done.** Covered only by `tests/test_integrations.py` against a mocked Google (14 tests, wire-format-accurate but never touches a real Google server). See "What real validation would need" below. |
| **Google Calendar** | Same OAuth flow; a real event synced both directions with a real calendar | ❌ No — same blocker as Gmail | **Not done.** Same mocked coverage as Gmail. |
| **Browser automation** | The actual web app, in an actual browser, doing actual DOM/JS things — not just `npm run build` succeeding | ✅ Partially — Playwright is installable without any credentials | **Attempted this pass — see [phase-browser.md](phase-browser.md)** for what was and wasn't possible without a running backend + real speech APIs. |
| **Voice providers (STT/TTS: Azure, Whisper)** | A real API key, a real audio sample, a real transcription/synthesis response | ❌ No — needs an Azure Speech subscription or a reachable Whisper-compatible endpoint and a network path to it; neither exists here | **Not done.** Covered only by `tests/test_voice.py` against mocked HTTP (28+ tests assert exact request/response shapes per provider's documented API, but never call the real service). |
| **Anthropic / OpenAI-compatible LLM** | A real API key, a real completion | ❌ No — no API key available | **Not done.** Covered only by `tests/test_llm.py` against mocked HTTP (wire-format-accurate for both Anthropic's and OpenAI's actual documented request/response shapes). |

## What real validation of the blocked integrations would need

These are not skipped by choice — they require things a sandboxed, non-interactive CLI session structurally cannot obtain:

1. **Gmail / Google Calendar** — a Google Cloud project with an OAuth 2.0 client, `WENSDAY_GOOGLE_CLIENT_ID`/`_SECRET` set, and a human completing the browser consent screen once (`GET /api/v1/auth/google/login`). After that one manual step, everything downstream (`sync_calendar`, `GmailSender.send`) is regular HTTP the app already makes correctly against Google's documented API — the risk is entirely in that first OAuth handshake, which is exactly what can't be exercised without a browser and a real account.
2. **Azure Speech / Whisper** — an Azure Speech resource key + region, or a reachable OpenAI-compatible `/audio/transcriptions` endpoint (self-hosted Whisper, or OpenAI's own key), then a short recorded audio sample.
3. **Anthropic / OpenAI** — an API key. Given one, `docs/setup.md` already documents exactly how to point the app at it; no code changes would be needed.

None of these three require code changes to validate — they require credentials and, for #1, one human clicking "Allow." Whoever has an actual Google Cloud project / Azure subscription / Anthropic key should be the one to run through `docs/setup.md` once with real values and confirm — the app's side of each integration is already implemented and unit-tested against the documented wire formats; what's unverified is specifically the credential exchange and the real service's actual behavior, not the app's logic.

## Method note

PostgreSQL and Redis were validated using **portable, no-install binaries** (official EDB PostgreSQL 16.4 binaries zip; a maintained Windows build of the real Redis 5.0.14.1 server), run as unprivileged background processes on non-default ports. This was necessary because Chocolatey's system-wide install requires admin rights not available in this environment, and no Docker daemon is available either. Both servers are genuinely the real software — not emulators or mocks — and this approach is reusable by anyone without admin/Docker access.
