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
    <section className="list-card">
      <div className="section-heading compact-heading">
        <div><h2>Metrics <small>(strategy {metrics?.strategy ?? liveStrategy} · tick {metrics?.ticks ?? "—"} — API values; Phase 8 computes fairness/latency)</small></h2><p>Service, rejections and strategy compare</p></div>
      </div>
      {!metrics && <p className="empty-state">No metrics yet.</p>}
      {metrics && (
        <>
          <div className="metrics-charts">
            <div className="metrics-chart">
              <div className="connection-note">service: served / unmet / committed</div>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={servedData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#dbe7e3" />
                  <XAxis dataKey="name" tick={{ fill: "#5b7a70", fontSize: 11 }} />
                  <YAxis allowDecimals={false} tick={{ fill: "#5b7a70", fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: "#ffffff", border: "1px solid #dbe7e3" }} />
                  <Bar dataKey="value">
                    {servedData.map((d) => (
                      <Cell key={d.name} fill={d.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="metrics-chart">
              <div className="connection-note">rejected by reason (violations proxy)</div>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rejectedData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#dbe7e3" />
                  <XAxis type="number" allowDecimals={false} tick={{ fill: "#5b7a70", fontSize: 11 }} />
                  <YAxis type="category" dataKey="reason" width={150} tick={{ fill: "#5b7a70", fontSize: 10 }} />
                  <Tooltip contentStyle={{ background: "#ffffff", border: "1px solid #dbe7e3" }} />
                  <Bar dataKey="count" fill="#e5ae4c" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          {metrics.extra && Object.keys(metrics.extra).length > 0 && (
            <div className="chip-row">
              {Object.entries(metrics.extra).map(([k, v]) => (
                <span key={k} className="chip">{k}: {v}</span>
              ))}
            </div>
          )}
          <div className="connection-note">
            idle / violations / fairness gap / recovery / latency render here from API when present.
          </div>
        </>
      )}
      <div className="compare-block">
        <h3 className="detail-h3">Strategy compare (centralized vs negotiation)</h3>
        <CompareForm onRun={loadCompare} loading={loading} />
        {err && <p className="demo-error">{err}</p>}
        {(compareA ?? compareB) && (
          <div className="comms-grid">
            {[compareA, compareB].map((m, i) => (
              <div key={i} className="detail-card">
                <div><strong>{m?.strategy ?? "—"}</strong></div>
                <ul className="detail-list">
                  {compareRows(m).map((r) => (
                    <li key={r.k} className="compare-row"><span>{r.k}</span><span>{r.v}</span></li>
                  ))}
                  {m && Object.keys(m.rejected_by_reason).length > 0 && (
                    <li className="connection-note">rejected: {Object.entries(m.rejected_by_reason).map(([k, v]) => `${k}=${v}`).join("; ").slice(0, 160)}</li>
                  )}
                </ul>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function CompareForm({ onRun, loading }: { onRun: (a: string, b: string, simA: string, simB: string) => void; loading: boolean }) {
  const [simA, setSimA] = useState("");
  const [simB, setSimB] = useState("");
  return (
    <div className="compare-form">
      <input value={simA} onChange={(e) => setSimA(e.target.value)} placeholder="centralized sim id" className="compare-input" aria-label="Centralized sim id" />
      <input value={simB} onChange={(e) => setSimB(e.target.value)} placeholder="negotiation sim id" className="compare-input" aria-label="Negotiation sim id" />
      <button
        disabled={loading || !simA || !simB}
        onClick={() => onRun("centralized", "negotiation", simA, simB)}
        className="button button-secondary"
      >
        {loading ? "Loading…" : "Compare side-by-side"}
      </button>
      <span className="connection-note">Create one sim per strategy, paste ids, compare.</span>
    </div>
  );
}
