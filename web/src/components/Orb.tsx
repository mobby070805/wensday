"use client";

import { useAssistant } from "@/lib/assistant";
import { t, type UiLang } from "@/lib/ui-strings";

/** The voice orb: tap (or press Space) to speak; tap again while it is speaking to interrupt. */
export function Orb({ lang }: { lang: UiLang }) {
  const { voiceState, interim, toggleListening, handsFree, setHandsFree, muted, setMuted, speechPref, setSpeechPref } = useAssistant();
  const label = voiceState === "idle" ? t(lang, "tapToSpeak") : voiceState === "listening" ? t(lang, "listening") : voiceState === "thinking" ? t(lang, "thinking") : t(lang, "speaking");
  return (
    <div className="card stage">
      <button className={`orb ${voiceState}`} onClick={toggleListening} aria-label={label} aria-pressed={voiceState === "listening"} />
      <div className="status" role="status" aria-live="polite">{label}</div>
      <div className="interim" aria-live="off">{interim}</div>
      <div className="row wrap" style={{ justifyContent: "center" }}>
        <label className="row muted"><input type="checkbox" checked={handsFree} onChange={(e) => setHandsFree(e.target.checked)} />{t(lang, "handsFree")}</label>
        <label className="row muted"><input type="checkbox" checked={muted} onChange={(e) => setMuted(e.target.checked)} />Mute voice</label>
        <select className="input" style={{ width: "auto" }} value={speechPref} onChange={(e) => setSpeechPref(e.target.value as "auto" | "ta-IN" | "en-IN")} aria-label="Speech recognition language">
          <option value="auto">Listen: auto</option>
          <option value="en-IN">Listen: English / Tanglish</option>
          <option value="ta-IN">Listen: தமிழ்</option>
        </select>
      </div>
    </div>
  );
}
