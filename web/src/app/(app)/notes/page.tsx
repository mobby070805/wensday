"use client";

import { useState } from "react";
import { QuickAdd } from "@/components/QuickAdd";
import type { Note } from "@/lib/types";
import { useResource } from "@/lib/useResource";

export default function NotesPage() {
  const { items, error, create, update, remove } = useResource<Note>("/notes");
  const [q, setQ] = useState("");
  const shown = items.filter((n) => !q || `${n.title} ${n.body}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <h1>Notes</h1>
      <QuickAdd placeholder="Take a note…" onAdd={(body) => create({ body })} />
      <input className="input" style={{ marginBottom: 14 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search notes" aria-label="Search notes" />
      {error && <p className="error">{error}</p>}
      <div className="grid two">
        {shown.map((n) => (
          <article key={n.id} className="card">
            <div className="row"><strong className="spacer">{n.pinned ? "📌 " : ""}{n.title || "Untitled"}</strong>{n.kind !== "note" && <span className="tag">{n.kind}</span>}</div>
            <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{n.body}</p>
            <div className="row">
              <button className="btn small" onClick={() => update(n.id, { pinned: !n.pinned })}>{n.pinned ? "Unpin" : "Pin"}</button>
              <button className="btn small danger" onClick={() => remove(n.id)}>Delete</button>
            </div>
          </article>
        ))}
      </div>
      {shown.length === 0 && <p className="muted">No notes.</p>}
    </>
  );
}
