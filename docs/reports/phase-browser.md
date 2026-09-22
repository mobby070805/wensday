# Real World Validation — Browser automation

**Setup:** Playwright (`@playwright/test`) with a real Chromium binary, driving the real Next.js app — first the dev server, then (once a dev-mode-only artifact was ruled out) the actual production build (`next build && next start`) — against the real FastAPI backend (SQLite, offline rule engine, no LLM key needed for the scenarios tested).

## What was tested

Five scenarios in `web/e2e/smoke.spec.ts`, each driving a real browser through real user actions against real running servers:

1. The login page renders with zero console/page errors.
2. A user registers through the real form, lands on the assistant page, types a message, and receives the exact reply the backend's offline rule engine is supposed to produce for that input.
3. A task is added through the real Tasks page UI and appears in the list.
4. The dashboard renders its charts with zero console/page errors.
5. A wrong password produces the real "invalid email or password" error from the real backend.

## What failed

**A real, production-reachable bug**, found only because a real browser executed the real code: submitting a chat message crashed the entire page with "Application error: a client-side exception has occurred." Root cause, confirmed by bisection (not guesswork): `web/src/components/Chat.tsx` had

```ts
useEffect(() => end.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [messages]);
```

an **implicit-return arrow function** as the effect callback. This is a well-known React footgun: `useEffect` callbacks must return either `undefined` or a cleanup function, and an implicit-return body evaluates and returns whatever its expression produces on every invocation. Confirmed empirically:

- First reproduced against `next dev` (React StrictMode + Fast Refresh), where it looked like it might be a dev-only artifact.
- **Still reproduced against the actual production build** (`next build && next start`) — ruling that out. This is a real bug reachable in production, not a development-only quirk.
- Bisected by rewriting the effect with an explicit block body and no return statement; rebuilt; crash gone.

**Why static analysis never caught this**: `useEffect`'s TypeScript type is `() => void | Destructor`. TypeScript's special-cased handling of `void`-typed return positions means *any* expression is assignable there — `tsc --noEmit` cannot distinguish "returns undefined" from "returns something React will try to call as a cleanup function" by design. `npm run typecheck` and `next build` both passed cleanly on the buggy code the entire time. Only executing the actual code in an actual browser exposed it.

Two additional test failures turned out to be test-authoring issues, not app bugs (confirmed by reading the real DOM state at failure via Playwright's accessibility snapshot):
- `getByText(reply, { exact: true })` failed because the reply bubble also contains a sibling `<small>` style-badge element, so the container's full text content is the reply concatenated with the badge text — the reply itself was correctly present.
- `getByRole("alert")` matched two elements: the app's own error `div` and Next.js's own (always-present, empty) route announcer, which also carries `role="alert"`.

## What was fixed

`Chat.tsx`'s effect now has an explicit block body:
```ts
useEffect(() => {
  end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
}, [messages]);
```
A repository-wide search (`useEffect\(\(\) =>\s*[^{]`) confirmed this was the *only* implicit-return effect in the codebase — no other instances to fix.

The two test-authoring issues were fixed in `smoke.spec.ts` (drop `exact: true`; scope the alert check to the app's own `.error` class instead of the bare ARIA role).

## What evidence proves it works

```
Running 5 tests using 1 worker
  ok 1 login page renders with no console errors
  ok 2 a real user can register, land on the assistant page, and get a real reply
  ok 3 tasks page: a real task can be added through the real UI and appears in the list
  ok 4 dashboard renders charts without console errors
  ok 5 wrong password shows a real error from the real backend
5 passed (5.2s)
```
All five against the real production build. `web/e2e/smoke.spec.ts` is now committed as a permanent regression suite and wired into CI (`.github/workflows/ci.yml`'s new `e2e` job: starts the real backend, builds and starts the real web app, runs the real Playwright suite against both, gates image builds on it passing) — this bug class cannot recur silently.

## What risk remains

- **Voice is explicitly not covered.** Chromium's bundled build has no speech-recognition backend, and no real microphone exists in this (or any CI) environment — the Web Speech API paths (`voice.ts`, the orb's listening state, wake word, hands-free mode) remain unverified by any automated test. This is the single largest remaining gap in the web app and can only be closed by a human testing with Chrome/Edge and a real microphone.
- Only Chromium was tested (no Firefox/Safari/WebKit — this app targets Chromium-family browsers for Web Speech API support anyway, per `docs/language-system.md`).
- No mobile-viewport or touch-interaction testing.
- No accessibility audit beyond what Playwright's locator strategy incidentally exercises (ARIA roles/labels needed to exist for the tests to find elements at all, which is a weak but non-zero signal).
- The five scenarios cover navigation, forms, and the non-voice chat path — not every page (calendar, notes, goals, memory, plugins, settings) has a dedicated E2E test yet.
