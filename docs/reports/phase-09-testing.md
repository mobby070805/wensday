# Phase 9 — Testing suite · **85 %**

**Delivered:** 312 backend tests + 25 web tests, all passing; ~25 Dart tests written but not run. Full breakdown, method and gaps: [testing.md](../testing.md). CI runs all suites ([ci.yml](../../.github/workflows/ci.yml)).

**Highlights**
- The brief's own utterances are asserted **verbatim end-to-end** (e.g. `"Sure Madesh, nalaiku morning 9:00 AM-ku meeting reminder set panniten."`, `"Mail draft ready. Review panna venduma illa direct send panna venduma?"`, `"Okay. Inniku schedule la important tasks mattum prioritize panren."`).
- Security properties are tests, not intentions: tenant isolation across every resource type, refresh-token replay revoking all sessions, token-type confusion, no account enumeration on login, OAuth `state` forgery, tokens encrypted at rest, plugin scope revocation, the LLM never being offered `send_email`, email never sent without confirmation.
- Concurrency: two workers racing on one reminder → exactly one fires; parallel 401s share one token refresh (web and Dart).
- Tests are hermetic (no network) and deterministic (fixed clock for NLU; mocked transports).

**Method note:** several failures were *test* bugs (wrong expectations, sloppy `or` assertions, a spy that only recorded the last message) and were fixed in the tests — but the tests also exposed **at least twelve real product bugs** (phases 3, 6, 7 list them): the CRUD body-annotation bug, unknown-intent dispatch, recurrence drift/catch-up, ranking, the fuzzy-match and skeleton collisions (`vilakku`/`ilakku`, `amma`/`aama`, `Jerry`/`seri`), English content words diluting Tanglish detection, the language-stickiness rule overriding real Tanglish, the lone "epdi" triggering how-are-you, template keyword collisions, the embedder's stop-word list, and "call me later" learned as a name.

**Gaps:** no browser E2E, load, soak or chaos tests · no PostgreSQL/Redis/Qdrant integration tests (SQLite and in-process fallbacks only) · no mobile integration tests · no NLU accuracy benchmark on real user utterances · no speech-quality evaluation with native speakers · no coverage measurement configured.
