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
  const renderRow = (id: string, label: string, status: string, extra: string) => (
    <li key={id}>
      <button
        onClick={() => onSelect(id === selectedId ? null : id)}
        className={`flex w-full items-center justify-between rounded px-2 py-1 text-left hover:bg-slate-800 ${id === selectedId ? "bg-slate-800 ring-1 ring-emerald-400" : "bg-slate-950"}`}
      >
        <span>{label} <span className="text-slate-400">{extra}</span></span>
        <span className="text-slate-400">{status}{disc.has(id) ? " 📡✕" : ""}</span>
      </button>
    </li>
  );
  return (
    <div className="rounded border border-slate-700 bg-slate-900 p-3">
      <h2 className="mb-2 text-sm font-semibold">Resources ({boats.length} boats · {teams.length} teams)</h2>
      {(selBoat ?? selTeam) && (
        <div className="mb-2 rounded bg-slate-800 p-2 text-xs">
          {selBoat && (
            <>
              <div className="flex items-center justify-between">
                <strong>{selBoat.boat_id}</strong>
                <button className="text-slate-400 hover:text-white" onClick={() => onSelect(null)}>✕</button>
              </div>
              <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5">
                <dt className="text-slate-400">Status</dt><dd>{selBoat.status}{disc.has(selBoat.boat_id) ? " (disconnected)" : ""}</dd>
                <dt className="text-slate-400">Node</dt><dd>{selBoat.node_id}</dd>
                <dt className="text-slate-400">Mission</dt><dd>{selBoat.assignment_id ?? "—"}</dd>
                <dt className="text-slate-400">Capacity</dt><dd>{selBoat.capacity} (aboard {selBoat.passengers})</dd>
                <dt className="text-slate-400">Fuel</dt><dd>{selBoat.fuel.toFixed(0)} / reserve {selBoat.fuel_reserve.toFixed(0)}</dd>
                <dt className="text-slate-400">Recovery</dt><dd>{selBoat.needs_recovery ? "NEEDED 🛟" : "—"}</dd>
              </dl>
              {(selBoat.status === "FAILED" || selBoat.needs_recovery) && (
                <p className="mt-1 text-amber-300">Recovery: a recovery incident (REC-{selBoat.boat_id}-…) carries stranded passengers; servicing boat boards them at this node.</p>
              )}
            </>
          )}
          {selTeam && (
            <>
              <div className="flex items-center justify-between">
                <strong>{selTeam.team_id}</strong>
                <button className="text-slate-400 hover:text-white" onClick={() => onSelect(null)}>✕</button>
              </div>
              <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5">
                <dt className="text-slate-400">Status</dt><dd>{selTeam.status}</dd>
                <dt className="text-slate-400">Node</dt><dd>{selTeam.node_id}</dd>
                <dt className="text-slate-400">Mission</dt><dd>{selTeam.assignment_id ?? "—"}</dd>
                <dt className="text-slate-400">Capabilities</dt><dd>{selTeam.capabilities.join("+")}</dd>
              </dl>
            </>
          )}
        </div>
      )}
      <ul className="max-h-56 space-y-1 overflow-y-auto text-xs">
        {boats.map((b) => renderRow(b.boat_id, `⛵ ${b.boat_id}`, b.status, `@${b.node_id} fuel ${b.fuel.toFixed(0)}`))}
        {teams.map((t) => renderRow(t.team_id, `▲ ${t.team_id}`, t.status, `@${t.node_id}`))}
      </ul>
    </div>
  );
}
