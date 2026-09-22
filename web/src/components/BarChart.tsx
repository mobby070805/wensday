"use client";

import { useState } from "react";

export interface Bar {
  label: string;      // x-axis / row label
  value: number;
  detail?: string;    // longer text for tooltip + table (e.g. full date)
}

const W = 640, H = 200, PAD = { l: 30, r: 8, t: 12, b: 26 };

/**
 * Single-series column chart. One series -> one hue, no legend (the title names it).
 * Thin bars with a 4px rounded data end, 2px gaps, a recessive grid, a hover tooltip, and a table view
 * so nothing depends on colour or on being able to see the plot.
 */
export function ColumnChart({ title, unit, bars }: { title: string; unit: string; bars: Bar[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const max = Math.max(1, ...bars.map((b) => b.value));
  const top = Math.max(4, Math.ceil(max / 4) * 4);        // round the axis to a friendly number so ticks are integers
  const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
  const slot = iw / Math.max(1, bars.length);
  const bw = Math.min(28, slot - 2);                       // 2px surface gap between neighbouring bars
  const y = (v: number) => PAD.t + ih - (v / top) * ih;
  const ticks = [0, top / 2, top];
  const every = Math.ceil(bars.length / 7);                // label ~7 x positions, never every bar

  return (
    <figure className="card" style={{ margin: 0 }}>
      <div className="row">
        <figcaption style={{ fontWeight: 600 }}>{title}</figcaption>
        <span className="spacer" />
        <button className="btn small" onClick={() => setTable(!table)} aria-pressed={table}>{table ? "Chart" : "Table"}</button>
      </div>
      {table ? (
        <table style={{ width: "100%", marginTop: 10, borderCollapse: "collapse" }}>
          <thead><tr><th align="left">Day</th><th align="right">{unit}</th></tr></thead>
          <tbody>{bars.map((b) => <tr key={b.label + b.detail}><td>{b.detail ?? b.label}</td><td align="right">{b.value}</td></tr>)}</tbody>
        </table>
      ) : (
        <div style={{ position: "relative" }}>
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}: ${bars.map((b) => `${b.detail ?? b.label} ${b.value}`).join(", ")}`} style={{ width: "100%", height: "auto" }}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="rgba(120,180,255,0.14)" strokeWidth={1} />
                <text x={PAD.l - 6} y={y(t) + 4} textAnchor="end" fontSize={11} fill="#8ea2c4">{t}</text>
              </g>
            ))}
            {bars.map((b, i) => {
              const x = PAD.l + slot * i + (slot - bw) / 2;
              const h = Math.max(b.value ? 2 : 0, (b.value / top) * ih);
              return (
                <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} tabIndex={0}>
                  <rect x={PAD.l + slot * i} y={PAD.t} width={slot} height={ih} fill="transparent" />{/* hit target larger than the mark */}
                  {b.value > 0 && <path d={roundTop(x, y(b.value), bw, h, 4)} fill="#38d9c8" opacity={hover === null || hover === i ? 1 : 0.55} />}
                  {i % every === 0 && <text x={x + bw / 2} y={H - 8} textAnchor="middle" fontSize={11} fill="#8ea2c4">{b.label}</text>}
                </g>
              );
            })}
          </svg>
          {hover !== null && (
            <div role="tooltip" style={{ position: "absolute", left: `${((PAD.l + slot * hover + slot / 2) / W) * 100}%`, top: 0, transform: "translate(-50%, -6px)", background: "#0d1424", border: "1px solid rgba(120,180,255,0.3)", borderRadius: 8, padding: "4px 8px", fontSize: 12, pointerEvents: "none", whiteSpace: "nowrap" }}>
              {bars[hover].detail ?? bars[hover].label}: <b>{bars[hover].value}</b> {unit}
            </div>
          )}
        </div>
      )}
    </figure>
  );
}

/** Column with only its top (data end) corners rounded; the base stays square on the axis. */
export function roundTop(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`;
}

/** Horizontal share bars with direct labels (used instead of a pie for ≤ 4 categories). */
export function ShareBars({ title, rows }: { title: string; rows: { label: string; value: number }[] }) {
  const total = rows.reduce((s, r) => s + r.value, 0);
  return (
    <figure className="card" style={{ margin: 0 }}>
      <figcaption style={{ fontWeight: 600, marginBottom: 10 }}>{title}</figcaption>
      {total === 0 ? <p className="muted">No conversations yet.</p> : (
        <div style={{ display: "grid", gap: 10 }}>
          {rows.map((r) => (
            <div key={r.label}>
              <div className="row"><span>{r.label}</span><span className="spacer" /><span className="muted">{r.value} · {Math.round((100 * r.value) / total)}%</span></div>
              <div className="bar" role="img" aria-label={`${r.label}: ${Math.round((100 * r.value) / total)}%`}><i style={{ width: `${(100 * r.value) / total}%` }} /></div>
            </div>
          ))}
        </div>
      )}
    </figure>
  );
}
