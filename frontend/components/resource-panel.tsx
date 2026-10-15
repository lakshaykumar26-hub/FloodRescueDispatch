"use client";

import type { Boat, GroundTeam } from "../types";

interface Props {
  boats: Boat[];
  teams: GroundTeam[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  disconnectedIds: string[];
}

export default function ResourcePanel({ boats, teams, selectedId, onSelect, disconnectedIds }: Props) {
  const disc = new Set(disconnectedIds);
  const selBoat = boats.find((b) => b.boat_id === selectedId) ?? null;
  const selTeam = teams.find((t) => t.team_id === selectedId) ?? null;
  const renderRow = (id: string, icon: string, status: string, extra: string) => (
    <li key={id}>
      <button
        onClick={() => onSelect(id === selectedId ? null : id)}
        className={`request-row ${id === selectedId ? "is-selected" : ""}`}
      >
        <span className="boat-icon">{icon}</span>
        <span className="row-main"><strong>{id} <small>{extra}</small></strong><small>{status}{disc.has(id) ? " 📡✕" : ""}</small></span>
        <span className={`boat-status boat-${status.toLowerCase()}`}>{status}</span>
      </button>
    </li>
  );
  return (
    <section className="list-card">
      <div className="section-heading compact-heading">
        <div><h2>Resources ({boats.length} boats · {teams.length} teams)</h2><p>Fuel, mission and recovery state</p></div>
        <span className="count-pill">{boats.length + teams.length}</span>
      </div>
      {(selBoat ?? selTeam) && (
        <div className="detail-card">
          {selBoat && (
            <>
              <div className="detail-title">
                <strong>{selBoat.boat_id}</strong>
                <button className="detail-close" onClick={() => onSelect(null)} aria-label="Clear selection">✕</button>
              </div>
              <dl className="detail-grid">
                <dt>Status</dt><dd>{selBoat.status}{disc.has(selBoat.boat_id) ? " (disconnected)" : ""}</dd>
                <dt>Node</dt><dd>{selBoat.node_id}</dd>
                <dt>Mission</dt><dd>{selBoat.assignment_id ?? "—"}</dd>
                <dt>Capacity</dt><dd>{selBoat.capacity} (aboard {selBoat.passengers})</dd>
                <dt>Fuel</dt><dd>{selBoat.fuel.toFixed(0)} / reserve {selBoat.fuel_reserve.toFixed(0)}</dd>
                <dt>Recovery</dt><dd>{selBoat.needs_recovery ? "NEEDED 🛟" : "—"}</dd>
              </dl>
              {(selBoat.status === "FAILED" || selBoat.needs_recovery) && (
                <p className="detail-note">Recovery: a recovery incident (REC-{selBoat.boat_id}-…) carries stranded passengers; servicing boat boards them at this node.</p>
              )}
            </>
          )}
          {selTeam && (
            <>
              <div className="detail-title">
                <strong>{selTeam.team_id}</strong>
                <button className="detail-close" onClick={() => onSelect(null)} aria-label="Clear selection">✕</button>
              </div>
              <dl className="detail-grid">
                <dt>Status</dt><dd>{selTeam.status}</dd>
                <dt>Node</dt><dd>{selTeam.node_id}</dd>
                <dt>Mission</dt><dd>{selTeam.assignment_id ?? "—"}</dd>
                <dt>Capabilities</dt><dd>{selTeam.capabilities.join("+")}</dd>
              </dl>
            </>
          )}
        </div>
      )}
      <ul className="request-list">
        {boats.map((b) => renderRow(b.boat_id, "⛵", b.status, `@${b.node_id} fuel ${b.fuel.toFixed(0)}`))}
        {teams.map((t) => renderRow(t.team_id, "▲", t.status, `@${t.node_id}`))}
      </ul>
    </section>
  );
}
