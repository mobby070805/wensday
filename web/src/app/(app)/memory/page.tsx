"use client";

import { useState } from "react";
import { QuickAdd } from "@/components/QuickAdd";
import { api } from "@/lib/api";
import type { Memory } from "@/lib/types";
import { useResource } from "@/lib/useResource";

export default function MemoryPage() {
  const { items, error, create, remove, refetch } = useResource<Memory>("/memories");
  const [confirm, setConfirm] = useState(false);
  async function exportAll() {
    const data = await api.get<unknown>("/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    Object.assign(document.createElement("a"), { href: url, download: "wensday-export.json" }).click();
    URL.revokeObjectURL(url);
  }
  return (
    <>
      <h1>Memory</h1>
      <p className="muted">What Wensday remembers about you. You're in control — delete anything, or everything.</p>
      <QuickAdd placeholder="Tell Wensday something to remember…" onAdd={(text) => create({ text, kind: "fact", importance: 0.8 })} />
      {error && <p className="error">{error}</p>}
      {items.length === 0 && <p className="muted">Nothing remembered yet.</p>}
      <ul className="list">
        {items.map((m) => (
          <li key={m.id}>
            <span className="title">{m.text}</span>
            <span className="tag">{m.kind}</span>
            <button className="btn small danger" onClick={() => remove(m.id)}>Forget</button>
          </li>
        ))}
      </ul>
      <div className="row" style={{ marginTop: 20 }}>
        <button className="btn" onClick={exportAll}>Export my data</button>
        {!confirm ? <button className="btn danger" onClick={() => setConfirm(true)}>Forget everything…</button> : (
          <>
            <span className="error">Delete all memories permanently?</span>
            <button className="btn danger" onClick={async () => { await api.del("/memories"); setConfirm(false); await refetch(); }}>Yes, forget all</button>
            <button className="btn" onClick={() => setConfirm(false)}>Cancel</button>
          </>
        )}
      </div>
    </>
  );
}
