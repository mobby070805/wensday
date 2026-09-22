"use client";

import { Chat } from "@/components/Chat";
import { uiLang } from "@/components/Shell";
import { Orb } from "@/components/Orb";
import { useAuth } from "@/lib/auth";
import { useResource } from "@/lib/useResource";
import type { Reminder, Task } from "@/lib/types";
import { t } from "@/lib/ui-strings";

const fmt = (iso: string) => new Date(iso).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });

export default function AssistantPage() {
  const { user } = useAuth();
  const lang = uiLang(user?.language);
  const tasks = useResource<Task>("/tasks", "?status=open&limit=5");
  const reminders = useResource<Reminder>("/reminders", "?status=pending&limit=5");
  const first = (user?.name || "").split(" ")[0];
  return (
    <>
      <h1>{first ? `Vanakkam, ${first}` : "Vanakkam"}</h1>
      <div className="assistant">
        <div className="grid">
          <Orb lang={lang} />
          <Chat lang={lang} />
        </div>
        <div className="grid">
          <section className="card">
            <h2>{t(lang, "reminders")}</h2>
            {reminders.items.length === 0 ? <p className="muted">{t(lang, "empty")}</p> : (
              <ul className="list">{reminders.items.map((r) => <li key={r.id}><span className="title">{r.title}</span><span className="tag">{fmt(r.due_at)}</span></li>)}</ul>
            )}
          </section>
          <section className="card">
            <h2>{t(lang, "openTasks")}</h2>
            {tasks.items.length === 0 ? <p className="muted">{t(lang, "empty")}</p> : (
              <ul className="list">{tasks.items.map((x) => <li key={x.id}><span className="title">{x.title}</span>{x.priority >= 3 && <span className="tag">P{x.priority}</span>}</li>)}</ul>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
