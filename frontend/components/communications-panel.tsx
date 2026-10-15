"use client";

import type { CommsState } from "../types";

function badge(status: string): string {
  switch (status) {
    case "ACKED": return "bg-emerald-700";
    case "DELIVERED": return "bg-sky-700";
    case "QUEUED": return "bg-amber-700";
    case "RETRY": return "bg-orange-700";
    case "EXPIRED": return "bg-red-700";
    case "DROPPED": return "bg-slate-600";
    default: return "bg-slate-600";
  }
}

/** Truthful comms monitor: only renders what /communications + events report. Never conflates sent=delivered=acked. */
export default function CommunicationsPanel({ comms }: { comms: CommsState | null }) {
  if (!comms) return <div className="rounded border border-slate-700 bg-slate-900 p-3 text-xs text-slate-400">No comms data yet.</div>;
  return (
    <div className="rounded border border-slate-700 bg-slate-900 p-3">
      <h2 className="mb-2 text-sm font-semibold">Comms monitor <span className="text-xs font-normal text-slate-400">(tick {comms.tick})</span></h2>
      <div className="mb-2 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded bg-slate-950 p-2">
          <div className="font-semibold text-emerald-300">Connected ({comms.connected.length})</div>
          <div className="text-slate-300">{comms.connected.join(", ") || "—"}</div>
        </div>
        <div className="rounded bg-slate-950 p-2">
          <div className="font-semibold text-red-300">Disconnected ({comms.disconnected.length})</div>
          <div className="text-slate-300">{comms.disconnected.join(", ") || "—"}</div>
        </div>
      </div>
      <div className="mb-2 text-xs">Queue length: <strong>{comms.queue.length}</strong>
        {comms.partitions.length > 0 && (
          <span className="ml-2 rounded bg-red-800 px-1.5 py-0.5">⛔ partition: {comms.partitions.map((p) => `${p.agent_id} t${p.from_tick}→${p.to_tick ?? "…"}`).join("; ")}</span>
        )}
      </div>
      <h3 className="mb-1 text-xs font-semibold text-slate-300">Queued</h3>
      <ul className="mb-2 max-h-28 space-y-0.5 overflow-y-auto text-xs">
        {comms.queue.map((m) => (
          <li key={m.message_id} className="flex items-center gap-2 rounded bg-slate-950 px-2 py-0.5">
            <span className={`rounded px-1.5 py-0.5 text-[10px] ${badge(m.status)}`}>{m.status}</span>
            <span className="font-mono">{m.message_id}</span>
            <span className="text-slate-400">{m.type} {m.sender_id}→{m.recipient_id} t{m.created_at_tick} exp t{m.expires_at_tick}{typeof m.retries === "number" ? ` retry×${m.retries}` : ""}</span>
          </li>
        ))}
        {comms.queue.length === 0 && <li className="text-slate-500">Queue empty.</li>}
      </ul>
      <h3 className="mb-1 text-xs font-semibold text-slate-300">Recent messages ({comms.messages.length})</h3>
      <ul className="mb-2 max-h-28 space-y-0.5 overflow-y-auto text-xs">
        {comms.messages.slice(-20).map((m) => (
          <li key={m.message_id} className="flex items-center gap-2 rounded bg-slate-950 px-2 py-0.5">
            <span className={`rounded px-1.5 py-0.5 text-[10px] ${badge(m.status)}`}>{m.status}</span>
            <span className="font-mono">{m.message_id}</span>
            <span className="text-slate-400">{m.type} {m.sender_id}→{m.recipient_id} t{m.created_at_tick}</span>
          </li>
        ))}
        {comms.messages.length === 0 && <li className="text-slate-500">No messages yet.</li>}
      </ul>
      <h3 className="mb-1 text-xs font-semibold text-slate-300">Reconciliation</h3>
      <ul className="max-h-20 space-y-0.5 overflow-y-auto text-xs">
        {comms.reconciliation_log.map((r, i) => (
          <li key={i} className="rounded bg-slate-950 px-2 py-0.5 text-slate-300">
            t{r.tick} <span className="rounded bg-emerald-800 px-1 text-[10px]">{r.status}</span> {r.agent_id} — {r.detail}
          </li>
        ))}
        {comms.reconciliation_log.length === 0 && <li className="text-slate-500">No reconciliations yet — heal a partition to see one here.</li>}
      </ul>
    </div>
  );
}
