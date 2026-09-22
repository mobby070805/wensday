/** Pure helpers for the voice layer (no browser APIs, so they are unit-testable). */
import type { Style } from "./types";

// Speech recognisers routinely mishear the wake word, and Tamil recognisers write it in Tamil script.
const WAKE_FORMS = ["wensday", "wednesday", "vensday", "wendsday", "winsday", "wenzday", "hey wensday", "ok wensday", "வென்ஸ்டே", "வெனஸ்டே", "வெட்னஸ்டே"];

const norm = (s: string) => s.toLowerCase().trim();

export function hasWakeWord(text: string): boolean {
  const t = norm(text);
  return WAKE_FORMS.some((w) => t.startsWith(w) || t.includes(` ${w}`));
}

/** Remove a leading wake word ("Wensday, nalaiku 9 mani…" -> "nalaiku 9 mani…"). */
export function stripWakeWord(text: string): string {
  const t = text.trim();
  const low = t.toLowerCase();
  for (const w of [...WAKE_FORMS].sort((a, b) => b.length - a.length)) {
    if (low.startsWith(w)) return t.slice(w.length).replace(/^[\s,.:;!-]+/, "");
  }
  return t;
}

const TAMIL = /[஀-௿]/;

/** Which recognition locale to use for the next utterance. */
export function recognitionLocale(pref: "auto" | "ta-IN" | "en-IN", lastStyle: Style | null): "ta-IN" | "en-IN" {
  if (pref !== "auto") return pref;
  return lastStyle === "ta" ? "ta-IN" : "en-IN"; // en-IN copes best with Tanglish; switch to Tamil once the user is speaking Tamil
}

export interface VoiceLike {
  name: string;
  lang: string;
}

// Names of common female neural/system voices, and markers of male ones.
const FEMALE_HINTS = ["female", "pallavi", "neerja", "heera", "priya", "kalpana", "veena", "lekha", "google தமிழ்", "google हिन्दी", "google uk english female", "samantha", "zira"];
const MALE_HINTS = ["male", "valluvar", "prabhat", "hemant", "ravi", "rishi", "david", "mark"];

/**
 * Choose the most suitable *female* voice for `lang` ("ta" | "en") from the platform's voice list.
 * Preference order: server-advertised hints > known female names > any in-language voice that is not
 * known-male > any in-language voice.
 */
export function pickVoice<T extends VoiceLike>(voices: T[], lang: "ta" | "en", hints: string[] = []): T | null {
  const inLang = voices.filter((v) => v.lang.toLowerCase().startsWith(lang));
  const en = lang === "en" ? [...inLang.filter((v) => v.lang.toLowerCase() === "en-in"), ...inLang.filter((v) => v.lang.toLowerCase() !== "en-in")] : inLang;
  const pool = en.length ? en : inLang;
  if (!pool.length) return null;
  const has = (v: T, list: string[]) => list.some((h) => v.name.toLowerCase().includes(h.toLowerCase()));
  return (
    pool.find((v) => has(v, hints)) ??
    pool.find((v) => has(v, FEMALE_HINTS)) ??
    pool.find((v) => !has(v, MALE_HINTS)) ??
    pool[0]
  );
}

export function containsTamil(s: string): boolean {
  return TAMIL.test(s);
}

/** Speech rate slightly slower for Tamil, which most voices render quickly. */
export function rateFor(lang: "ta" | "en", base = 1): number {
  return Math.min(2, Math.max(0.5, lang === "ta" ? base * 0.95 : base));
}
