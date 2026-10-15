"use client";

import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getMetrics } from "../lib/api";
import type { SimulationMetrics } from "../types";

interface Props {
  metrics: SimulationMetrics | null;
  compareA: SimulationMetrics | null;
  compareB: SimulationMetrics | null;
  onCompareLoaded: (a: SimulationMetrics | null, b: SimulationMetrics | null) => void;
  liveStrategy: string;
}

/**
 * Metrics display (values from API now; computation lands in Phase 8).
 * Compare view runs two sims via API and shows both side-by-side.
 */
export default function MetricsPanel({ metrics, compareA, compareB, onCompareLoaded, liveStrategy }: Props) {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const loadCompare = async (stratA: string, stratB: string, simA: string, simB: string) => {
    setLoading(true);
    setErr(null);
    try {
      const [a, b] = await Promise.all([getMetrics(simA), getMetrics(simB)]);
      onCompareLoaded({ ...a, strategy: stratA }, { ...b, strategy: stratB });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "compare fetch failed");
    } finally {
      setLoading(false);
    }
  };

  const servedData = metrics
    ? [
        { name: "served", value: metrics.served, fill: "#34d399" },
        { name: "unserved", value: metrics.unserved, fill: "#f87171" },
        { name: "committed", value: metrics.committed, fill: "#38bdf8" },
      ]
    : [];

  const rejectedData = metrics
    ? Object.entries(metrics.rejected_by_reason).map(([reason, count]) => ({ reason: reason.slice(0, 34), count }))
    : [];

  const compareRows = (m: SimulationMetrics | null) =>
    m
      ? [
          { k: "served", v: m.served },
          { k: "unserved", v: m.unserved },
          { k: "committed", v: m.committed },
          ...Object.entries(m.extra ?? {}).map(([k, v]) => ({ k, v })),
        ]
      : [];

  return (
    <div className="rounded border border-slate-700 bg-slate-900 p-3">
      <h2 className="mb-1 text-sm font-semibold">
        Metrics <span className="text-xs font-normal text-slate-400">(strategy {metrics?.strategy ?? liveStrategy} · tick {metrics?.ticks ?? "—"} — API values; Phase 8 computes fairness/latency)</span>
      </h2>
      {!metrics && <p className="text-xs text-slate-400">No metrics yet.</p>}
      {metrics && (
        <>
          <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
            <div className="h-44">
              <div className="text-xs text-slate-400">service: served / unmet / committed</div>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={servedData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="name" tick={{ fill: "#cbd5e1", fontSize: 11 }} />
                  <YAxis allowDecimals={false} tick={{ fill: "#cbd5e1", fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
                  <Bar dataKey="value">
                    {servedData.map((d) => (
                      <Cell key={d.name} fill={d.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="h-44">
              <div className="text-xs text-slate-400">rejected by reason (violations proxy)</div>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rejectedData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis type="number" allowDecimals={false} tick={{ fill: "#cbd5e1", fontSize: 11 }} />
                  <YAxis type="category" dataKey="reason" width={150} tick={{ fill: "#cbd5e1", fontSize: 10 }} />
                  <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
                  <Bar dataKey="count" fill="#fbbf24" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          {metrics.extra && Object.keys(metrics.extra).length > 0 && (
            <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-300">
              {Object.entries(metrics.extra).map(([k, v]) => (
                <span key={k} className="rounded bg-slate-800 px-2 py-0.5">{k}: {v}</span>
              ))}
            </div>
          )}
          <div className="mt-1 text-xs text-slate-500">
            idle / violations / fairness gap / recovery / latency render here from API when present.
          </div>
        </>
      )}
      <div className="mt-2 border-t border-slate-800 pt-2">
        <h3 className="text-xs font-semibold">Strategy compare (centralized vs negotiation)</h3>
        <CompareForm onRun={loadCompare} loading={loading} />
        {err && <p className="text-xs text-red-300">{err}</p>}
        {(compareA ?? compareB) && (
          <div className="mt-1 grid grid-cols-2 gap-2 text-xs">
            {[compareA, compareB].map((m, i) => (
              <div key={i} className="rounded bg-slate-950 p-2">
                <div className="font-semibold">{m?.strategy ?? "—"}</div>
                <ul className="mt-1 space-y-0.5 text-slate-300">
                  {compareRows(m).map((r) => (
                    <li key={r.k} className="flex justify-between"><span>{r.k}</span><span>{r.v}</span></li>
                  ))}
                  {m && Object.keys(m.rejected_by_reason).length > 0 && (
                    <li className="text-slate-500">rejected: {Object.entries(m.rejected_by_reason).map(([k, v]) => `${k}=${v}`).join("; ").slice(0, 160)}</li>
                  )}
                </ul>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function CompareForm({ onRun, loading }: { onRun: (a: string, b: string, simA: string, simB: string) => void; loading: boolean }) {
  const [simA, setSimA] = useState("");
  const [simB, setSimB] = useState("");
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
      <input value={simA} onChange={(e) => setSimA(e.target.value)} placeholder="centralized sim id" className="w-40 rounded bg-slate-800 px-2 py-1" aria-label="Centralized sim id" />
      <input value={simB} onChange={(e) => setSimB(e.target.value)} placeholder="negotiation sim id" className="w-40 rounded bg-slate-800 px-2 py-1" aria-label="Negotiation sim id" />
      <button
        disabled={loading || !simA || !simB}
        onClick={() => onRun("centralized", "negotiation", simA, simB)}
        className="rounded bg-sky-700 px-2 py-1 hover:bg-sky-600 disabled:opacity-50"
      >
        {loading ? "Loading…" : "Compare side-by-side"}
      </button>
      <span className="text-slate-500">Create one sim per strategy, paste ids, compare.</span>
    </div>
  );
}
