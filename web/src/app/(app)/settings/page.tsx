"use client";

import { useState, type FormEvent } from "react";
import { useAssistant } from "@/lib/assistant";
import { useAuth } from "@/lib/auth";

const TIMEZONES = ["Asia/Kolkata", "Asia/Colombo", "Asia/Singapore", "Asia/Dubai", "Europe/London", "America/New_York", "America/Los_Angeles", "Australia/Sydney"];

export default function SettingsPage() {
  const { user, updateProfile } = useAuth();
  const { voiceConfig } = useAssistant();
  const [name, setName] = useState(user?.name ?? "");
  const [tz, setTz] = useState(user?.timezone ?? "Asia/Kolkata");
  const [lang, setLang] = useState(user?.language ?? "auto");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await updateProfile({ name, timezone: tz, language: lang as "auto" });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (x) {
      setError(x instanceof Error ? x.message : "Could not save");
    }
  }

  return (
    <>
      <h1>Settings</h1>
      <form className="card" onSubmit={save} style={{ display: "grid", gap: 14, maxWidth: 520 }}>
        <label>What should Wensday call you?<input className="input" value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>Reply language
          <select className="input" value={lang} onChange={(e) => setLang(e.target.value as typeof lang)}>
            <option value="auto">Match me automatically (recommended)</option>
            <option value="en">Always English</option>
            <option value="tanglish">Always Tanglish</option>
            <option value="ta">Always தமிழ்</option>
          </select>
        </label>
        <label>Timezone
          <select className="input" value={tz} onChange={(e) => setTz(e.target.value)}>
            {[...new Set([tz, ...TIMEZONES])].map((z) => <option key={z}>{z}</option>)}
          </select>
        </label>
        {error && <div className="error" role="alert">{error}</div>}
        <div className="row"><button className="btn primary">Save</button>{saved && <span style={{ color: "var(--ok)" }}>Saved ✓</span>}</div>
      </form>
      <section className="card" style={{ marginTop: 16, maxWidth: 520 }}>
        <h2>Voice</h2>
        {voiceConfig ? (
          <ul className="muted" style={{ margin: 0, paddingLeft: 18 }}>
            <li>Speech recognition: <b>{voiceConfig.server_stt ? `server (${voiceConfig.stt})` : "this browser"}</b></li>
            <li>Speech output: <b>{voiceConfig.server_tts ? `server (${voiceConfig.tts})` : "this browser"}</b></li>
            <li>Female voices: {voiceConfig.voices.ta} (Tamil), {voiceConfig.voices.en} (English)</li>
            <li>Wake word: “{voiceConfig.wake_word}”</li>
          </ul>
        ) : <p className="muted">Loading…</p>}
        <p className="muted" style={{ fontSize: 13 }}>Tip: for the most natural Tamil voice, install a Tamil (India) voice in your OS, or ask your admin to enable the Azure speech provider.</p>
      </section>
    </>
  );
}
