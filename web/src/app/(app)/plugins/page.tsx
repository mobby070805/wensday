"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { PluginInfo } from "@/lib/types";

export default function PluginsPage() {
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.get<PluginInfo[]>("/plugins").then(setPlugins, (e) => setError(String(e.message ?? e))), []);
  useEffect(() => { void load(); }, [load]);

  return (
    <>
      <h1>Plugins</h1>
      <p className="muted">Plugins add abilities. Each one only gets the permissions you grant.</p>
      {error && <p className="error">{error}</p>}
      <div className="grid two">
        {plugins.map((p) => (
          <article key={p.name} className="card">
            <div className="row"><strong className="spacer">{p.name}</strong><span className="tag">v{p.version}</span></div>
            <p>{p.description}</p>
            <p className="muted" style={{ fontSize: 13 }}>Permissions: {p.scopes.join(", ") || "none"} · Tools: {p.tools.join(", ")}</p>
            {p.name === "weather" && p.enabled === false && <p className="muted" style={{ fontSize: 13 }}>Default city: Chennai (change it in Settings → after enabling).</p>}
            <button className={`btn ${p.enabled ? "" : "primary"}`} onClick={async () => { await api.post(`/plugins/${p.name}/${p.enabled ? "disable" : "enable"}`, {}); await load(); }}>
              {p.enabled ? "Disable" : "Enable & grant permissions"}
            </button>
          </article>
        ))}
      </div>
    </>
  );
}
