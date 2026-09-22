"use client";

import { QuickAdd, localToIso } from "@/components/QuickAdd";
import { useAuth } from "@/lib/auth";
import type { Reminder } from "@/lib/types";
import { useResource } from "@/lib/useResource";

const RECUR = ["none", "daily", "weekdays", "weekly", "monthly"];

export default function RemindersPage() {
  const { user } = useAuth();
  const { items, error, create, update } = useResource<Reminder>("/reminders", "?status=pending");
  const style = user?.language === "ta" ? "ta" : user?.language === "tanglish" ? "tg" : "en";
  return (
    <>
      <h1>Reminders</h1>
      <p className="muted">Or just say: “Wensday, nalaiku 9 mani meeting remind pannu.”</p>
      <QuickAdd
        placeholder="Remind me to…"
        onAdd={(title, when) => create({ title, due_at: localToIso(when), style })}
        extra={(v, set) => <input className="input" style={{ width: 210 }} type="datetime-local" required value={v} onChange={(e) => set(e.target.value)} aria-label="When" />}
      />
      {error && <p className="error">{error}</p>}
      {items.length === 0 && <p className="muted">No upcoming reminders.</p>}
      <ul className="list">
        {items.map((r) => (
          <li key={r.id}>
            <span className="title">{r.title}</span>
            <span className="tag">{new Date(r.due_at).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
            <select className="input" style={{ width: 120 }} value={r.recurrence} onChange={(e) => update(r.id, { recurrence: e.target.value })} aria-label="Repeat">
              {RECUR.map((x) => <option key={x}>{x}</option>)}
            </select>
            <button className="btn small danger" onClick={() => update(r.id, { status: "cancelled" })}>Cancel</button>
          </li>
        ))}
      </ul>
    </>
  );
}
