# Phase 8 — Integrations & plugins · **75 %**

**Delivered:** Google OAuth2 with **incremental consent** (login uses `openid email profile` only; Calendar/Gmail scopes are requested per feature), signed short-lived `state`, account linking to a signed-in user, unverified-email rejection, **tokens encrypted at rest** (Fernet) with transparent refresh · Google Calendar two-way sync (idempotent by `external_id`, all-day events, pushes local-only events) · Gmail send (RFC-822, only to real addresses — a name like "client" stays *queued* rather than guessed) and unread-inbox summary · browser assistance as **client actions** (open URL / web search / summarise supplied page text; http(s) only) · plugin SDK with declared scopes, per-user enablement, call-time enforcement, LLM-visibility gating · two bundled plugins (weather via Open-Meteo, browser) · custom workflows (phrase and daily-schedule triggers; `{{today_5pm}}`-style variables; confirmation-gated tools rejected; stops at first failure) · [plugin guide](../plugins.md).

**Tests:** `test_integrations.py` 14 (mocked Google end to end) · plugin permission and workflow tests in `test_api.py`.

**Gaps**
- Nothing has talked to real Google, Open-Meteo or Gmail; request shapes are asserted against mocks. Google's OAuth app verification (required for Gmail scopes in production) is an operational task.
- **Plugins are trusted code**, not sandboxed (scopes gate the tool API, not Python). Do not load unreviewed third-party plugins. Process isolation + signing are roadmap items.
- Calendar sync is pull-on-demand (`POST /integrations/google/calendar/sync`); no webhook/push channel, no deletion propagation from Google, no recurring-event expansion beyond what Google's `singleEvents` returns.
- No Microsoft/Outlook, WhatsApp, Slack or smart-home integrations. "Call pannu" returns a `dial` action for the client (mobile does not yet launch the dialer — `url_launcher` is a dependency but unused).
- Email: no reply-to-thread, attachments or labels.
