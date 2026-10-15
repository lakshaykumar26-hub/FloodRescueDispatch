"use client";

import type { Incident } from "../types";

interface Props {
  incidents: Incident[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  tick: number;
}

export default function IncidentPanel({ incidents, selectedId, onSelect, tick }: Props) {
  const sorted = [...incidents].sort((a, b) => b.urgency - a.urgency || a.created_tick - b.created_tick);
  const sel = incidents.find((i) => i.incident_id === selectedId) ?? null;
  return (
    <div className="rounded border border-slate-700 bg-slate-900 p-3">
      <h2 className="mb-2 text-sm font-semibold">Incidents ({incidents.length})</h2>
      {sel && (
        <div className="mb-2 rounded bg-slate-800 p-2 text-xs">
          <div className="flex items-center justify-between">
            <strong>{sel.incident_id}</strong>
            <button className="text-slate-400 hover:text-white" onClick={() => onSelect(null)}>✕</button>
          </div>
          <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5">
            <dt className="text-slate-400">Node</dt><dd>{sel.node_id}</dd>
            <dt className="text-slate-400">Urgency</dt><dd>U{sel.urgency}</dd>
            <dt className="text-slate-400">Demand</dt><dd>{sel.people} people</dd>
            <dt className="text-slate-400">Wait</dt><dd>{Math.max(0, tick - sel.created_tick)} ticks (since {sel.created_tick})</dd>
            <dt className="text-slate-400">Status</dt><dd>{sel.status}</dd>
            <dt className="text-slate-400">Needs</dt><dd>{sel.required_capabilities.join("+") || "—"}</dd>
            <dt className="text-slate-400">Kind</dt><dd>{sel.kind}{sel.caused_by ? ` ← ${sel.caused_by}` : ""}</dd>
            <dt className="text-slate-400">Confidence</dt><dd>{sel.report_confidence.toFixed(2)}</dd>
          </dl>
        </div>
      )}
      <ul className="max-h-56 space-y-1 overflow-y-auto text-xs">
        {sorted.map((i) => (
          <li key={i.incident_id}>
            <button
              onClick={() => onSelect(i.incident_id === selectedId ? null : i.incident_id)}
              className={`flex w-full items-center justify-between rounded px-2 py-1 text-left hover:bg-slate-800 ${i.incident_id === selectedId ? "bg-slate-800 ring-1 ring-emerald-400" : "bg-slate-950"}`}
            >
              <span>U{i.urgency} {i.incident_id} <span className="text-slate-400">@{i.node_id} ×{i.people}</span></span>
              <span className="text-slate-400">{i.status}</span>
            </button>
          </li>
        ))}
        {sorted.length === 0 && <li className="text-slate-400">No incidents.</li>}
      </ul>
    </div>
  );
}
