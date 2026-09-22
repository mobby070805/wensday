# The language system

Tamil, English and Tanglish are handled as three first-class surface forms of the *same* concepts. There is no translate-then-understand step, which is what makes offline mode, low latency and code-switching possible.

```
text ─► normalise ─► detect (ta | en | tanglish, mixed?, register)
     └► tokens ─► concepts (lexicon: Tamil script ≡ Tanglish ≡ English)  ─► intent + entities ─► reply in the user's style
```

## Detection — `app/i18n/detect.py`
| Signal | Outcome |
|---|---|
| ≥ 50 % of letters are Tamil script | `ta` (`mixed` if ≥ 2 Latin words) |
| some Tamil script among Latin words | `tanglish`, `mixed` |
| Tanglish lexicon hits vs English **function-word** hits | `tanglish` if ratio ≥ 0.34, or ≥ 2 hits, or a very short utterance; else `en` |
| `da / di / machan / pa` · `sir / madam / neenga / pannunga` | `register = casual / respectful` |

Two design lessons baked in: English *content* words (`task`, `remind`, `mail`) are routinely borrowed into Tanglish, so only true function words count as evidence for English — otherwise "task add pannu buy milk" reads as English. And a one- or two-word English reply ("meeting") after a Tanglish turn keeps the conversation's language instead of flipping.

**Reply style** mirrors the user: Tamil script → Tamil script · Tanglish or mixed → Tanglish · English → English. Override per request (`lang_hint`), per account (`language`), or by saying "speak in Tamil" / "english la pesu" (stored as a preference).

## Tanglish spelling variance — `app/i18n/normalize.py`
Tanglish has no standard spelling. Lookup goes through a phonetic *skeleton* (long vowels collapsed, doubled letters merged, `th/dh→t`, `ch/sh→s`, `zh→l`, voiced/unvoiced merged…):

`nalaiku = naalaiku = nalaikku` · `pannu = panu` · `aagum = aakum` · `enaku = enakku = ennaku`

Glued suffixes are stripped (`officela`, `meetingku`, `mailah`). Fuzzy matching is a last resort and requires the same first sound. Words that must *not* match are protected: `amma` (mother) vs `aama` (yes) is a hand-listed exact-only `kin` concept; 42 common English words and names are asserted never to read as Tanglish (skeleton collisions like `Jerry`≈`seri` were found and fixed by tests).

## Lexicon — `app/i18n/lexicon.py`
~60 concepts, each with English, Tanglish and Tamil-script forms side by side. Tanglish verbs are matched by pattern, because the morphology is productive: `pannu / panren / panniten / pannitiya / pannunga / pannanum` are all the "do" family.

## Time expressions — `app/nlu/timeparse.py`
`9 mani` · `காலை 9 மணி` · `nalaiku morning 9` · `inniku sayangalam 5 mani` · `tomorrow 9am` · `next friday 3:30 pm` · `velli kizhamai 4 pm` · `in 10 minutes` · `10 nimisham la` · `2 mani neram kalichu` · Tamil/Tanglish number words (`onbadhu mani`).

**Bare-hour heuristic** (no am/pm, no day part): 1–6 → PM, 7–11 → AM, 12 → noon. If the time has already passed today, it tries the PM reading, then tomorrow. It is a guess — which is why Wensday always reads the resolved time back ("nalaiku morning 9:00 AM-ku…") so a wrong guess is caught immediately.

## Intents — `app/nlu/engine.py`
reminders (create/list) · tasks (create/list/complete) · notes · goals · calendar (create/query/update, conflict detection) · email (draft → review/send, status question) · call · mood/coaching · day plan · presence ("naa office poitu varen") · social (greeting, "saptiya?", how-are-you, thanks, bye) · time/date · weather (plugin) · confirmations (`aama / seri / venam / review / direct`).

**Slot filling.** Missing details produce a question in the user's language and the next utterance fills the slot: `Enaku reminder set pannu` → "Enna, eppo remind pannanum?" → `meeting` → "meeting eppo remind pannanum?" → `nalaiku 9 mani` → done. A new command abandons the pending question; "venam/no" cancels it; it expires after 10 minutes.

**Confirmation gate.** `email_draft` never sends. It stores a pending action; only `aama / seri anuppu / direct send pannu / yes` (or "review pannanum" first) sends. The LLM is never given a send tool. If no mail provider is connected, or the recipient is a name rather than an address, the draft is honestly reported as *saved*, not sent.

## Persona — `app/i18n/persona.py`
68 replies (207 variants) authored separately for `en`, `tg` and `ta` (calm, respectful, "neenga" register — Wensday never says "da" back). Time phrasing is per style: `nalaiku morning 9:00 AM-ku` · `tomorrow at 9:00 AM` · `நாளை காலை 9:00 மணிக்கு`. Openers follow the brief verbatim ("Sure Madesh, …"; "Okay. Inniku schedule la…").

## Voice output for mixed replies — `app/voice/`
A Tamil neural voice reads Tamil script fluently but spells out Latin letters. So each reply is split into runs: Tamil script → Tamil voice · **Tanglish words → transliterated to Tamil script → Tamil voice** · English words/names → English (en-IN) voice · numbers/times stay attached to their neighbours. The result is returned as `speech[]` (for client TTS) and can be rendered as SSML with per-run `<voice>`/`<lang>` for Azure.

## LLM tier
When rules don't match, the LLM gets a system prompt with the same language-mirroring rules, the user's name, local time, preferences and recalled memories, plus the same tool registry (built-ins + the plugins the user enabled). Tool errors are returned to the model as data; a runaway tool loop is capped at 4 rounds; provider failure falls through to the offline reply.

## Known limitations (be aware)
- **Rule coverage is finite.** Unusual phrasings fall to the LLM tier; offline they get the "offline mode" message. Coverage was built from the brief's examples plus common variants, not from a corpus of real Chennai speech.
- **Tamil-script generation quality** (the `ta` templates and transliteration) was written by an AI and has not been reviewed by a native speaker. The transliterator is deliberately approximate (`ண/ன`, `ட/த` are not distinguished in Latin spelling); it targets pronounceability, not orthography. **Have a native speaker review `persona.py` and `voice/translit.py` before shipping to users.**
- **Speech recognition** of code-switched Tamil–English is a provider capability. The browser recogniser handles one locale per session (`en-IN` copes best with Tanglish; the UI switches to `ta-IN` when the user speaks Tamil). The Azure server path runs `ta-IN` and `en-IN` in parallel and keeps the more confident result; Whisper is biased with a Tanglish prompt. None of this was tested against real audio.
- The voice is "female" by *selection* of existing female voices (Pallavi / Neerja …), not a custom-trained voice.
- Numbers above twelve as Tamil words, dates like "next month", and durations like "half an hour" (`arai mani neram`) are not parsed yet.
