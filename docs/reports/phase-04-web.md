# Phase 4 — Web frontend · **80 %**

**Delivered** (`web/`, Next.js 15 + TypeScript strict, ~1.7 k lines): sign-in/registration + Google · OAuth callback that scrubs tokens from the URL · assistant screen (voice orb with listening/thinking/speaking states, transcript, typed input, hands-free wake-word mode, push-to-talk on Space, barge-in, mute) · pages for tasks, reminders, calendar, notes, goals, memory (with export and "forget everything"), plugins (enable/disable), settings (name, reply language, timezone, voice info), dashboard (KPIs, 14-day completion chart with tooltip + table view, language-mix bars, goal progress) · realtime socket with reconnect/backoff and refresh on `4401` · UI chrome in English and Tamil · PWA manifest · security headers.

**Design notes:** dark "HUD" theme with a calm teal accent; charts follow the dataviz rules (single hue for one series, thin bars with rounded data ends, recessive grid, tooltip, table alternative, direct-labelled share bars instead of a pie); keyboard-operable, `aria-live` status, reduced-motion respected.

**Verified:** `tsc --noEmit` clean · 25 vitest tests (single-flight token refresh incl. the parallel-401 case, sign-out on failed refresh, wake-word stripping incl. "Wednesday" mis-hearing, female-voice selection, recognition-locale choice, EN↔TA UI-string parity, chart geometry) · `next build` succeeds (13 routes, ≈105–115 kB first-load JS).

**Not verified — be aware:** the UI has **never been opened in a browser**. Layout, the microphone flow, speech synthesis and the realtime socket in a real browser are unchecked. Web Speech API works only in Chromium browsers.

**Gaps:** no document-upload / meeting-summary / email-inbox screens (the API exists; use `/docs` or add UI) · no workflow editor UI · no account/password screens · no browser E2E tests (Playwright is the recommended next step) · access tokens are kept in `localStorage` (simple, but XSS-exposed — moving to httpOnly cookies + CSRF protection is a hardening item) · no service worker (installable manifest only, not offline).
