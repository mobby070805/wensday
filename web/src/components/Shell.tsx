"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { AssistantProvider, useAssistant } from "@/lib/assistant";
import { useAuth } from "@/lib/auth";
import { t, type UiKey, type UiLang } from "@/lib/ui-strings";

const NAV: { href: string; key: UiKey }[] = [
  { href: "/", key: "assistant" },
  { href: "/dashboard", key: "dashboard" },
  { href: "/tasks", key: "tasks" },
  { href: "/reminders", key: "reminders" },
  { href: "/calendar", key: "calendar" },
  { href: "/notes", key: "notes" },
  { href: "/goals", key: "goals" },
  { href: "/memory", key: "memory" },
  { href: "/plugins", key: "plugins" },
  { href: "/settings", key: "settings" },
];

export function uiLang(language: string | undefined): UiLang {
  return language === "ta" ? "ta" : "en";
}

function Frame({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const { connected } = useAssistant();
  const path = usePathname();
  const lang = uiLang(user?.language);
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand"><i />WENSDAY</div>
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className={path === n.href ? "active" : ""} aria-current={path === n.href ? "page" : undefined}>
              {t(lang, n.key)}
            </Link>
          ))}
        </nav>
        <div className="foot">
          <span><span className={`dot ${connected ? "on" : ""}`} />{t(lang, connected ? "online" : "offline")}</span>
          <span>{user?.name || user?.email}</span>
          <button className="btn small" onClick={() => void logout()}>{t(lang, "signOut")}</button>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

/** Route guard + providers for every signed-in page. */
export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);
  if (loading || !user) return <div className="login"><span className="muted">Loading…</span></div>;
  return (
    <AssistantProvider>
      <Frame>{children}</Frame>
    </AssistantProvider>
  );
}
