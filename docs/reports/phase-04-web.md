# Phase 4 — Web frontend · **85 %**

**Delivered** (`web/`, Next.js 15 + TypeScript strict, ~1.7 k lines): sign-in/registration + Google · OAuth callback that scrubs tokens from the URL · assistant screen (voice orb with listening/thinking/speaking states, transcript, typed input, hands-free wake-word mode, push-to-talk on Space, barge-in, mute) · pages for tasks, reminders, calendar, notes, goals, memory (with export and "forget everything"), plugins (enable/disable), settings (name, reply language, timezone, voice info), dashboard (KPIs, 14-day completion chart with tooltip + table view, language-mix bars, goal progress) · realtime socket with reconnect/backoff and refresh on `4401` · UI chrome in English and Tamil · PWA manifest · security headers.

**Design notes:** dark "HUD" theme with a calm teal accent; charts follow the dataviz rules (single hue for one series, thin bars with rounded data ends, recessive grid, tooltip, table alternative, direct-labelled share bars instead of a pie); keyboard-operable, `aria-live` status, reduced-motion respected.

**Verified:** `tsc --noEmit` clean · 25 vitest tests (single-flight token refresh incl. the parallel-401 case, sign-out on failed refresh, wake-word stripping incl. "Wednesday" mis-hearing, female-voice selection, recognition-locale choice, EN↔TA UI-string parity, chart geometry) · `next build` succeeds (13 routes, ≈105–115 kB first-load JS) · **as of the Real World Validation pass, a real Chromium browser driving the real production build against the real backend** — see the addendum below.

**Not verified — be aware:** voice specifically. Chromium's bundled build has no speech-recognition backend and no real microphone exists in this or any CI environment, so the Web Speech API paths (the orb's listening state, wake word, hands-free mode, actual speech synthesis) remain unverified by any automated test — a human with Chrome/Edge and a microphone is still required for that. Web Speech API works only in Chromium browsers.

**Gaps:** no document-upload / meeting-summary / email-inbox screens (the API exists; use `/docs` or add UI) · no workflow editor UI · no account/password screens · access tokens are kept in `localStorage` (simple, but XSS-exposed — moving to httpOnly cookies + CSRF protection is a hardening item) · no service worker (installable manifest only, not offline) · E2E coverage exists for login/register/chat/tasks/dashboard but not yet calendar/notes/goals/memory/plugins/settings.

---

## Addendum — Production Completion Mode: real browser validation

**Found: a real, production-reachable crash**, only discoverable by executing the actual code in an actual browser. Sending a chat message crashed the whole page ("Application error: a client-side exception has occurred") due to `Chat.tsx`'s scroll-into-view `useEffect` using an implicit-return arrow function — a class of bug TypeScript's `void`-return special-casing cannot detect statically, so `tsc --noEmit` and `next build` both passed cleanly on the buggy code throughout. Confirmed *not* a dev-mode-only artifact by reproducing it against the actual `next build && next start` production output, then fixed and confirmed fixed by bisection (explicit block body, no return statement; rebuilt; crash gone). Full findings, method, and evidence: [phase-browser.md](phase-browser.md).

**Delivered:** Playwright installed with a real Chromium binary (no credentials needed); `web/e2e/smoke.spec.ts` (5 tests) drives real registration, a real typed chat turn against the real backend's offline rule engine, real task creation, and dashboard rendering — all against the real production build. Wired into CI as a new `e2e` job that starts the real backend and real web app and gates image builds on the suite passing, so this bug class cannot silently recur.

This closes the repeatedly-flagged "the web app has never been opened in a browser" gap for everything except voice, which structurally requires a human with a real microphone.
