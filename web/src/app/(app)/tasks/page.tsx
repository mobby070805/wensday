"use client";

import { useState } from "react";
import { QuickAdd, localToIso } from "@/components/QuickAdd";
import type { Task } from "@/lib/types";
import { useResource } from "@/lib/useResource";

export default function TasksPage() {
  const [show, setShow] = useState<"open" | "done">("open");
  const { items, loading, error, create, update, remove } = useResource<Task>("/tasks", `?status=${show}`);
  return (
    <>
      <h1>Tasks</h1>
      <QuickAdd
        placeholder="Add a task… (e.g. buy milk)"
        onAdd={(title, due) => create({ title, ...(due ? { due_at: localToIso(due) } : {}) })}
        extra={(v, set) => <input className="input" style={{ width: 210 }} type="datetime-local" value={v} onChange={(e) => set(e.target.value)} aria-label="Due" />}
      />
      <div className="row" style={{ marginBottom: 12 }}>
        {(["open", "done"] as const).map((s) => <button key={s} className={`btn small ${show === s ? "primary" : ""}`} onClick={() => setShow(s)}>{s}</button>)}
      </div>
      {error && <p className="error">{error}</p>}
      {!loading && items.length === 0 && <p className="muted">Nothing here yet.</p>}
      <ul className="list">
        {items.map((t) => (
          <li key={t.id} className={t.status === "done" ? "done" : ""}>
            <input type="checkbox" checked={t.status === "done"} onChange={() => update(t.id, { status: t.status === "done" ? "open" : "done" })} aria-label={`Mark ${t.title} ${t.status === "done" ? "open" : "done"}`} />
            <span className="title">{t.title}</span>
            {t.due_at && <span className="tag">{new Date(t.due_at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>}
            <select className="input" style={{ width: 76 }} value={t.priority} onChange={(e) => update(t.id, { priority: Number(e.target.value) })} aria-label="Priority">
              {[1, 2, 3, 4].map((p) => <option key={p} value={p}>P{p}</option>)}
            </select>
            <button className="btn small danger" onClick={() => remove(t.id)}>Delete</button>
          </li>
        ))}
      </ul>
    </>
  );
}
