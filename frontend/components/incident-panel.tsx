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
    <section className="list-card">
      <div className="section-heading compact-heading">
        <div><h2>Incidents ({incidents.length})</h2><p>Sorted by urgency · select for detail</p></div>
        <span className="count-pill">{incidents.length}</span>
      </div>
      {sel && (
        <div className="detail-card">
          <div className="detail-title">
            <strong>{sel.incident_id}</strong>
            <button className="detail-close" onClick={() => onSelect(null)} aria-label="Clear selection">✕</button>
          </div>
          <dl className="detail-grid">
            <dt>Node</dt><dd>{sel.node_id}</dd>
            <dt>Urgency</dt><dd>U{sel.urgency}</dd>
            <dt>Demand</dt><dd>{sel.people} people</dd>
            <dt>Wait</dt><dd>{Math.max(0, tick - sel.created_tick)} ticks (since {sel.created_tick})</dd>
            <dt>Status</dt><dd>{sel.status}</dd>
            <dt>Needs</dt><dd>{sel.required_capabilities.join("+") || "—"}</dd>
            <dt>Kind</dt><dd>{sel.kind}{sel.caused_by ? ` ← ${sel.caused_by}` : ""}</dd>
            <dt>Confidence</dt><dd>{sel.report_confidence.toFixed(2)}</dd>
          </dl>
        </div>
      )}
      <ul className="request-list">
        {sorted.map((i) => (
          <li key={i.incident_id}>
            <button
              onClick={() => onSelect(i.incident_id === selectedId ? null : i.incident_id)}
              className={`request-row ${i.incident_id === selectedId ? "is-selected" : ""}`}
            >
              <span className={`urgency-mark urgency-${i.urgency}`} />
              <span className="row-main"><strong>U{i.urgency} {i.incident_id} <small>@{i.node_id} ×{i.people}</small></strong></span>
              <span className={`request-status status-${i.status.toLowerCase()}`}>{i.status}</span>
            </button>
          </li>
        ))}
        {sorted.length === 0 && <li className="empty-state">No incidents.</li>}
      </ul>
    </section>
  );
}
