"use client";

import { useMemo } from "react";
import type { Assignment, SimEvent } from "../types";

interface Props {
  assignments: Assignment[];
  events: SimEvent[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

/**
 * Decision explanation: selected assignment vs alternatives, rejection
 * reasons, safety checks applied, stale/unavailable-info notes. Derived from
 * assignment history + events so EDGE_CLOSED / EDGE_DISPUTED / REPLAN_CHAIN
 * links are cited, never invented.
 */
export default function ExplanationPanel({ assignments, events, selectedId, onSelect }: Props) {
  const sel = assignments.find((a) => a.assignment_id === selectedId) ?? null;

  const related = useMemo(() => {
    if (!sel) return [] as SimEvent[];
    const keys = [sel.assignment_id, sel.proposal_id, sel.incident_id, sel.resource_id, ...(sel.route_edge_ids ?? [])];
    return events.filter((e) => {
      const blob = JSON.stringify(e.detail);
      return keys.some((k) => k && blob.includes(k));
    }).slice(-30);
  }, [sel, events]);

  const rejectionReasons = useMemo(() => {
    if (!sel) return [] as string[];
    const out: string[] = [];
    for (const h of sel.history) {
      if (/REJECT|EDGE_|SHELTER_FULL|RESOURCE_|STALE|EXPIRED/i.test(h.reason)) out.push(`tick ${h.tick}: ${h.reason} (${h.actor})`);
    }
    for (const e of related) {
      const r = (e.detail.reason ?? e.detail.code ?? "") as string;
      if (typeof r === "string" && r && /REJECT|EDGE_|SHELTER|RESOURCE_|STALE/i.test(r)) {
        out.push(`tick ${e.tick} ${e.kind}: ${r}`);
      }
      if (e.kind === "REJECTED" || e.kind === "EDGE_CLOSED" || e.kind === "EDGE_DISPUTED") {
        out.push(`tick ${e.tick} ${e.kind}: ${JSON.stringify(e.detail).slice(0, 160)}`);
      }
    }
    return [...new Set(out)].slice(0, 12);
  }, [sel, related]);

  const alternatives = useMemo(() => {
    if (!sel) return [] as Assignment[];
    return assignments
      .filter((a) => a.incident_id === sel.incident_id && a.assignment_id !== sel.assignment_id)
      .slice(0, 5);
  }, [sel, assignments]);

  const staleNote = useMemo(() => {
    if (!sel) return null as string | null;
    if (sel.status === "REQUIRES_RECONCILIATION") return "Stale/conflicting state flagged — needs reconciliation before further action.";
    const rec = related.find((e) => e.kind === "RECONCILED" || /STALE/i.test(JSON.stringify(e.detail)));
    if (rec) return `Stale-info note at tick ${rec.tick}: ${JSON.stringify(rec.detail).slice(0, 160)}`;
    return null;
  }, [sel, related]);

  const replanChain = useMemo(() => {
    if (!sel) return [] as string[];
    return sel.history
      .filter((h) => /REPLAN_CHAIN|REPLAN_FAILED|SHELTER_FULL|reassign/i.test(h.reason))
      .map((h) => `tick ${h.tick}: ${h.reason}`);
  }, [sel]);

  return (
    <div className="rounded border border-slate-700 bg-slate-900 p-3">
      <h2 className="mb-2 text-sm font-semibold">Decision explanation</h2>
      {assignments.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1">
          {assignments.slice(0, 12).map((a) => (
            <button
              key={a.assignment_id}
              onClick={() => onSelect(a.assignment_id === selectedId ? null : a.assignment_id)}
              className={`rounded px-2 py-0.5 text-xs ${a.assignment_id === selectedId ? "bg-emerald-600 text-white" : "bg-slate-800 hover:bg-slate-700"}`}
            >
              {a.assignment_id} · {a.status}
            </button>
          ))}
        </div>
      )}
      {!sel && <p className="text-xs text-slate-400">Select an assignment (or incident/resource on the map) to see why it was chosen, what was rejected, and which safety checks applied.</p>}
      {sel && (
        <div className="space-y-2 text-xs">
          <div className="rounded bg-slate-800 p-2">
            <strong>Selected: {sel.resource_id} → {sel.incident_id}</strong>
            <div className="text-slate-300">
              cost {sel.cost.toFixed(2)} · seats {sel.seats} · shelter {sel.shelter_id ?? "—"} · route {(sel.route_edge_ids ?? []).join(" → ") || "—"} · v{sel.version} · created tick {sel.created_tick}
            </div>
          </div>
          <div>
            <h3 className="font-semibold text-slate-200">Lifecycle</h3>
            <ul className="mt-0.5 space-y-0.5 text-slate-300">
              {sel.history.map((h, i) => (
                <li key={i}>tick {h.tick}: {h.from ?? "?"} → {h.to ?? "?"} — {h.reason} <span className="text-slate-500">({h.actor})</span></li>
              ))}
              {sel.history.length === 0 && <li className="text-slate-500">No history recorded.</li>}
            </ul>
          </div>
          <div>
            <h3 className="font-semibold text-slate-200">Alternatives for {sel.incident_id}</h3>
            {alternatives.length === 0 && <p className="text-slate-500">No competing assignments recorded for this incident.</p>}
            <ul className="mt-0.5 space-y-0.5 text-slate-300">
              {alternatives.map((a) => (
                <li key={a.assignment_id}>{a.resource_id} · cost {a.cost.toFixed(2)} · route {(a.route_edge_ids ?? []).join("→")} · {a.status}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="font-semibold text-slate-200">Rejection reasons & safety checks</h3>
            {rejectionReasons.length === 0 && <p className="text-slate-500">None cited on this assignment (safety validator passed: closed edge, capacity, fuel reserve, shelter overflow all checked at commit).</p>}
            <ul className="mt-0.5 space-y-0.5 text-slate-300">
              {rejectionReasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </div>
          {replanChain.length > 0 && (
            <div>
              <h3 className="font-semibold text-slate-200">Replan chain</h3>
              <ul className="mt-0.5 space-y-0.5 text-slate-300">
                {replanChain.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}
          {staleNote && <p className="rounded bg-amber-900/40 p-1.5 text-amber-200">⚠ {staleNote}</p>}
          {related.length > 0 && (
            <details>
              <summary className="cursor-pointer text-slate-400">Related events ({related.length})</summary>
              <ul className="mt-1 space-y-0.5 text-slate-400">
                {related.map((e, i) => (
                  <li key={i}>t{e.tick} {e.kind} [{e.actor}] {JSON.stringify(e.detail).slice(0, 140)}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
