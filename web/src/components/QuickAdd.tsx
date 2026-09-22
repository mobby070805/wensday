"use client";

import { useState, type FormEvent, type ReactNode } from "react";

/** A one-line "add" form with optional extra fields. */
export function QuickAdd({ placeholder, onAdd, extra, button = "Add" }: {
  placeholder: string;
  onAdd: (text: string, extra: string) => Promise<void>;
  extra?: (value: string, set: (v: string) => void) => ReactNode;
  button?: string;
}) {
  const [text, setText] = useState("");
  const [more, setMore] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await onAdd(text.trim(), more);
      setText("");
      setMore("");
    } catch (x) {
      setErr(x instanceof Error ? x.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="row wrap" style={{ marginBottom: 14 }}>
      <input className="input" style={{ flex: 1, minWidth: 200 }} value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} aria-label={placeholder} lang="ta" />
      {extra?.(more, setMore)}
      <button className="btn primary" disabled={busy || !text.trim()}>{button}</button>
      {err && <span className="error" role="alert">{err}</span>}
    </form>
  );
}

/** <input type="datetime-local"> value (local wall-clock) -> ISO string with the browser's UTC offset. */
export function localToIso(v: string): string {
  return new Date(v).toISOString();
}
