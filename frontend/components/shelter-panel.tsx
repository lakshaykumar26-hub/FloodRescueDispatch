"use client";

import type { Shelter } from "../types";

export default function ShelterPanel({ shelters }: { shelters: Shelter[] }) {
  return (
    <section className="list-card">
      <div className="section-heading compact-heading">
        <div><h2>Shelters ({shelters.length})</h2><p>People housed / total spaces</p></div>
      </div>
      <ul className="shelter-list">
        {shelters.map((s) => {
          const reserved = Object.values(s.reservations).reduce((a, b) => a + b, 0);
          const remaining = s.capacity - s.occupancy - reserved;
          const pct = Math.min(100, Math.max(0, ((s.occupancy + reserved) / Math.max(1, s.capacity)) * 100));
          return (
            <li key={s.shelter_id}>
              <span className="shelter-icon">+</span>
              <span className="row-main">
                <strong>{s.shelter_id}</strong>
                <small>@{s.node_id} · occ {s.occupancy}/{s.capacity} · reserved {reserved}{Object.keys(s.reservations).length > 0 && ` (${Object.keys(s.reservations).join(", ")})`}</small>
                <span className="capacity-track"><i style={{ width: `${pct}%` }} /></span>
                <small>{s.accepting ? `open · ${remaining} left` : "FULL"}</small>
              </span>
              <span className="capacity-label"><strong>{s.occupancy}</strong><span> / {s.capacity}<br />occupied</span></span>
            </li>
          );
        })}
        {shelters.length === 0 && <li className="empty-state">No shelters.</li>}
      </ul>
    </section>
  );
}
