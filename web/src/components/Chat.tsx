"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAssistant } from "@/lib/assistant";
import { t, type UiLang } from "@/lib/ui-strings";

const STYLE_LABEL = { en: "English", tg: "Tanglish", ta: "தமிழ்" } as const;

export function Chat({ lang }: { lang: UiLang }) {
  const { messages, send, error, clearError } = useAssistant();
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [messages]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const v = text;
    setText("");
    void send(v);
  }

  return (
    <div className="card">
      <div className="chat" role="log" aria-live="polite" aria-label="Conversation">
        {messages.length === 0 && <p className="muted">Try: “Wensday, nalaiku 9 mani meeting remind pannu.”</p>}
        {messages.map((m) => (
          <div key={m.id} className={`bubble ${m.role}`}>
            {m.text}
            {m.role === "assistant" && m.style && <small>{STYLE_LABEL[m.style]}{m.tier === "llm" ? " · AI" : m.tier === "offline" ? " · offline" : ""}</small>}
          </div>
        ))}
        <div ref={end} />
      </div>
      {error && <div className="error" role="alert" onClick={clearError}>{error}</div>}
      <form className="composer" onSubmit={submit}>
        <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder={t(lang, "typeMessage")} aria-label="Message" lang="ta" />
        <button className="btn primary" disabled={!text.trim()}>{t(lang, "send")}</button>
      </form>
    </div>
  );
}
