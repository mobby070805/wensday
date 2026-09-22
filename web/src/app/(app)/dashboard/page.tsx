"use client";

import { useCallback, useEffect, useState } from "react";
import { ColumnChart, ShareBars } from "@/components/BarChart";
import { uiLang } from "@/components/Shell";
import { api } from "@/lib/api";
import { useAssistant } from "@/lib/assistant";
import { useAuth } from "@/lib/auth";
import type { Dashboard } from "@/lib/types";
import { t } from "@/lib/ui-strings";

const LANG_NAMES: Record<string, string> = { en: "English", tanglish: "Tanglish", ta: "தமிழ் (Tamil)" };

export default function DashboardPage() {
  const { user } = useAuth();
  const { syncTick } = useAssistant();
  const lang = uiLang(user?.language);
  const [d, setD] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<{ headline: string; completed: number; open: number } | null>(null);

  const load = useCallback(async () => {
    try {
      setD(await api.get<Dashboard>("/analytics/dashboard"));
      setReview(await api.get("/analytics/weekly-review"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, []);
  useEffect(() => { void load(); }, [load, syncTick]);

  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Loading…</p>;

  const bars = d.tasks.completed_series.map((s) => {
    const day = new Date(s.date + "T00:00:00");
    return { label: day.toLocaleDateString([], { day: "numeric", month: "short" }), detail: day.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }), value: s.completed };
  });

  return (
    <>
      <h1>{t(lang, "dashboard")}</h1>
      {review && <p className="muted" style={{ marginTop: -8 }}>{review.headline}</p>}
      <div className="grid stats" style={{ marginBottom: 16 }}>
        <div className="card stat"><b>{d.tasks.open}</b><span>{t(lang, "openTasks")}</span></div>
        <div className="card stat"><b style={{ color: d.tasks.overdue ? "var(--warn)" : undefined }}>{d.tasks.overdue}</b><span>{t(lang, "overdue")}</span></div>
        <div className="card stat"><b>{d.streak_days}</b><span>{t(lang, "streak")}</span></div>
        <div className="card stat"><b>{d.reminders_fired}</b><span>Reminders delivered</span></div>
      </div>
      <div className="grid two">
        <ColumnChart title="Tasks completed per day (last 14 days)" unit="completed" bars={bars} />
        <ShareBars title="Languages you speak with Wensday (30 days)" rows={Object.entries(d.language_usage).map(([k, v]) => ({ label: LANG_NAMES[k] ?? k, value: v })).sort((a, b) => b.value - a.value)} />
        <section className="card" style={{ gridColumn: "1 / -1" }}>
          <h2>{t(lang, "goals")}</h2>
          {d.goals.length === 0 ? <p className="muted">{t(lang, "empty")}</p> : (
            <div style={{ display: "grid", gap: 12 }}>
              {d.goals.map((g) => (
                <div key={g.title}>
                  <div className="row"><span>{g.title}</span><span className="spacer" /><span className="muted">{g.progress}%</span></div>
                  <div className="bar" role="progressbar" aria-valuenow={g.progress} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${g.progress}%` }} /></div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
