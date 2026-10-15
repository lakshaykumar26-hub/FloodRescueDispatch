"use client";

import type { Shelter } from "../types";

export default function ShelterPanel({ shelters }: { shelters: Shelter[] }) {
  return (
    <div className="rounded border border-slate-700 bg-slate-900 p-3">
      <h2 className="mb-2 text-sm font-semibold">Shelters ({shelters.length})</h2>
      <ul className="space-y-1 text-xs">
        {shelters.map((s) => {
          const reserved = Object.values(s.reservations).reduce((a, b) => a + b, 0);
          const remaining = s.capacity - s.occupancy - reserved;
          return (
            <li key={s.shelter_id} className="rounded bg-slate-950 px-2 py-1">
              <div className="flex items-center justify-between">
                <strong>🏠 {s.shelter_id}</strong>
                <span className={s.accepting ? "text-emerald-300" : "text-red-300"}>
                  {s.accepting ? `open · ${remaining} left` : "FULL"}
                </span>
              </div>
              <div className="text-slate-400">
                @{s.node_id} · occ {s.occupancy}/{s.capacity} · reserved {reserved}
                {Object.keys(s.reservations).length > 0 && ` (${Object.keys(s.reservations).join(", ")})`}
              </div>
              <div className="mt-1 h-1.5 rounded bg-slate-800">
                <div
                  className={`h-1.5 rounded ${remaining <= 0 ? "bg-red-500" : "bg-emerald-500"}`}
                  style={{ width: `${Math.min(100, Math.max(0, ((s.occupancy + reserved) / Math.max(1, s.capacity)) * 100))}%` }}
                />
              </div>
            </li>
          );
        })}
        {shelters.length === 0 && <li className="text-slate-400">No shelters.</li>}
      </ul>
    </div>
  );
}
