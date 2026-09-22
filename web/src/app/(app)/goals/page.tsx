"use client";

import { useState } from "react";
import { QuickAdd } from "@/components/QuickAdd";
import { api } from "@/lib/api";
import type { Goal } from "@/lib/types";
import { useResource } from "@/lib/useResource";

export default function GoalsPage() {
  const { items, error, create, remove, refetch } = useResource<Goal>("/goals");
  const [ms, setMs] = useState<Record<string, string>>({});
  return (
    <>
      <h1>Goals</h1>
      <QuickAdd placeholder="A goal you want to reach…" onAdd={(title) => create({ title })} />
      {error && <p className="error">{error}</p>}
      {items.length === 0 && <p className="muted">No goals yet.</p>}
      <div className="grid two">
        {items.map((g) => (
          <article key={g.id} className="card">
            <div className="row"><strong className="spacer">{g.title}</strong><span className="tag">{g.progress}%</span></div>
            <div className="bar" style={{ margin: "10px 0" }} role="progressbar" aria-valuenow={g.progress} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${g.progress}%` }} /></div>
            <ul className="list">
              {g.milestones.map((m) => (
                <li key={m.id} className={m.done ? "done" : ""}>
                  <input type="checkbox" checked={m.done} onChange={async () => { await api.post(`/goals/${g.id}/milestones/${m.id}/toggle`); await refetch(); }} aria-label={m.title} />
                  <span className="title">{m.title}</span>
                </li>
              ))}
            </ul>
            <form className="row" style={{ marginTop: 10 }} onSubmit={async (e) => { e.preventDefault(); const v = ms[g.id]?.trim(); if (!v) return; await api.post(`/goals/${g.id}/milestones`, { title: v }); setMs({ ...ms, [g.id]: "" }); await refetch(); }}>
              <input className="input" placeholder="Add milestone" value={ms[g.id] ?? ""} onChange={(e) => setMs({ ...ms, [g.id]: e.target.value })} aria-label="Add milestone" />
              <button className="btn small">Add</button>
              <button type="button" className="btn small danger" onClick={() => remove(g.id)}>Delete</button>
            </form>
          </article>
        ))}
      </div>
    </>
  );
}
