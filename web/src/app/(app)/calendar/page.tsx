"use client";

import { QuickAdd, localToIso } from "@/components/QuickAdd";
import type { CalEvent } from "@/lib/types";
import { useResource } from "@/lib/useResource";

export default function CalendarPage() {
  const { items, error, create, remove } = useResource<CalEvent>("/events");
  const upcoming = items.filter((e) => new Date(e.end_at) > new Date());
  const days = new Map<string, CalEvent[]>();
  for (const e of upcoming) {
    const k = new Date(e.start_at).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
    days.set(k, [...(days.get(k) ?? []), e]);
  }
  return (
    <>
      <h1>Calendar</h1>
      <QuickAdd
        placeholder="New event…"
        onAdd={(title, start) => create({ title, start_at: localToIso(start) })}
        extra={(v, set) => <input className="input" style={{ width: 210 }} type="datetime-local" required value={v} onChange={(e) => set(e.target.value)} aria-label="Starts" />}
      />
      {error && <p className="error">{error}</p>}
      {upcoming.length === 0 && <p className="muted">Nothing scheduled.</p>}
      {[...days].map(([day, evs]) => (
        <section key={day} style={{ marginBottom: 18 }}>
          <h2>{day}</h2>
          <ul className="list">
            {evs.map((e) => (
              <li key={e.id}>
                <span className="tag">{new Date(e.start_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
                <span className="title">{e.title}{e.location && <span className="muted"> · {e.location}</span>}</span>
                {e.source === "google" && <span className="tag">Google</span>}
                <button className="btn small danger" onClick={() => remove(e.id)}>Delete</button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}
