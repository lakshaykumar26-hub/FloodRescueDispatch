"use client";

/**
 * Pure-SVG synthetic map. No tile/network dependency: renders entirely from
 * scenario node x/y, so blocking map tiles cannot break it (Phase 6 gate).
 */
import { useMemo } from "react";
import type { Edge, WorldState } from "../types";

const W = 760;
const H = 640;
const PAD = 44;

function project(x: number, y: number, maxX: number, maxY: number): [number, number] {
  const sx = (v: number, m: number) => PAD + (v / Math.max(m, 1)) * (W - 2 * PAD);
  // Flip y so larger y is lower on screen (matches scenario layout roughly).
  const sy = (v: number, m: number) => PAD + (v / Math.max(m, 1)) * (H - 2 * PAD);
  return [sx(x, maxX), sy(y, maxY)];
}

interface Props {
  world: WorldState;
  selectedRouteEdgeIds?: string[];
  changedRouteEdgeIds?: string[];
  selectedIncidentId?: string | null;
  selectedResourceId?: string | null;
  disconnectedIds?: string[];
  onSelectIncident?: (id: string) => void;
  onSelectResource?: (id: string) => void;
}

export default function SyntheticMap({
  world,
  selectedRouteEdgeIds = [],
  changedRouteEdgeIds = [],
  selectedIncidentId = null,
  selectedResourceId = null,
  disconnectedIds = [],
  onSelectIncident,
  onSelectResource,
}: Props) {
  const nodePos = useMemo(() => {
    const maxX = Math.max(1, ...world.nodes.map((n) => n.x));
    const maxY = Math.max(1, ...world.nodes.map((n) => n.y));
    const m = new globalThis.Map<string, [number, number]>();
    for (const n of world.nodes) m.set(n.node_id, project(n.x, n.y, maxX, maxY));
    return m;
  }, [world.nodes]);

  const edgeById = useMemo(() => {
    const m = new globalThis.Map<string, Edge>();
    for (const e of world.edges) m.set(e.edge_id, e);
    return m;
  }, [world.edges]);

  const selectedSet = useMemo(() => new Set(selectedRouteEdgeIds), [selectedRouteEdgeIds]);
  const changedSet = useMemo(() => new Set(changedRouteEdgeIds), [changedRouteEdgeIds]);
  const disconnectedSet = useMemo(() => new Set(disconnectedIds), [disconnectedIds]);

  const incidentByNode = useMemo(() => {
    const m = new globalThis.Map<string, typeof world.incidents>();
    for (const i of world.incidents) {
      const arr = m.get(i.node_id) ?? [];
      arr.push(i);
      m.set(i.node_id, arr);
    }
    return m;
  }, [world.incidents]);

  const boatByNode = useMemo(() => {
    const m = new globalThis.Map<string, typeof world.boats>();
    for (const b of world.boats) {
      const arr = m.get(b.node_id) ?? [];
      arr.push(b);
      m.set(b.node_id, arr);
    }
    return m;
  }, [world.boats]);

  const urgencyColor = (u: number) =>
    u >= 5 ? "#ef4444" : u >= 4 ? "#f97316" : u >= 3 ? "#eab308" : "#22c55e";

  return (
    <div className="rounded border border-slate-700 bg-slate-900 p-2">
      <div className="mb-1 flex flex-wrap gap-3 px-1 text-[11px] text-slate-300">
        <span><span className="inline-block h-0 w-6 border-t-2 border-slate-400 align-middle" /> road</span>
        <span><span className="inline-block h-0 w-6 border-t-2 border-sky-400 align-middle" /> waterway</span>
        <span><span className="inline-block h-0 w-6 border-t-2 border-dashed border-red-500 align-middle" /> closed</span>
        <span><span className="inline-block h-0 w-6 border-t-2 border-dotted border-amber-400 align-middle" /> disputed ⚠</span>
        <span><span className="inline-block h-0 w-6 border-t-[3px] border-emerald-400 align-middle" /> planned route</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Synthetic flood graph (offline SVG, no tiles)">
        {/* edges */}
        {world.edges.map((e) => {
          const a = nodePos.get(e.from_node);
          const b = nodePos.get(e.to_node);
          if (!a || !b) return null;
          const isSelected = selectedSet.has(e.edge_id);
          const isChanged = changedSet.has(e.edge_id);
          let stroke = e.mode === "water" ? "#38bdf8" : "#94a3b8";
          let dash: string | undefined;
          let width = e.mode === "water" ? 2.5 : 2;
          if (e.status === "closed") {
            stroke = "#ef4444";
            dash = "7 5";
            width = 3;
          } else if (e.status === "disputed") {
            stroke = "#fbbf24";
            dash = "2 4";
            width = 3;
          }
          if (isSelected) {
            stroke = "#34d399";
            width = 4;
          }
          if (isChanged) {
            stroke = "#c084fc";
            width = 4;
            dash = "10 3";
          }
          return (
            <g key={e.edge_id}>
              <title>{`${e.edge_id} ${e.mode} ${e.status} tt=${e.travel_time}`}</title>
              <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={stroke} strokeWidth={width} strokeDasharray={dash} strokeLinecap="round" />
              {e.status === "disputed" && (
                <text x={(a[0] + b[0]) / 2} y={(a[1] + b[1]) / 2 - 6} fontSize={13} textAnchor="middle">⚠</text>
              )}
              {e.status === "closed" && (
                <text x={(a[0] + b[0]) / 2} y={(a[1] + b[1]) / 2 - 6} fontSize={11} textAnchor="middle" fill="#ef4444">✕</text>
              )}
            </g>
          );
        })}
        {/* nodes */}
        {world.nodes.map((n) => {
          const p = nodePos.get(n.node_id);
          if (!p) return null;
          const fill = n.kind === "shelter" ? "#22c55e" : n.kind === "station" ? "#a78bfa" : n.kind === "transfer" ? "#f472b6" : "#334155";
          return (
            <g key={n.node_id}>
              <title>{`${n.node_id} ${n.kind} (${n.neighborhood})`}</title>
              <rect x={p[0] - 7} y={p[1] - 7} width={14} height={14} rx={n.kind === "shelter" ? 7 : 2} fill={fill} stroke="#0f172a" strokeWidth={1.5} />
              <text x={p[0]} y={p[1] - 11} fontSize={9} fill="#cbd5e1" textAnchor="middle">{n.node_id}</text>
            </g>
          );
        })}
        {/* incidents */}
        {world.incidents.filter((i) => i.status !== "SERVED" && i.status !== "CANCELLED").map((inc, idx) => {
          const p = nodePos.get(inc.node_id);
          if (!p) return null;
          const ox = 14 + (idx % 3) * 4;
          const selected = selectedIncidentId === inc.incident_id;
          return (
            <g
              key={inc.incident_id}
              onClick={() => onSelectIncident?.(inc.incident_id)}
              style={{ cursor: onSelectIncident ? "pointer" : "default" }}
            >
              <title>{`${inc.incident_id} u=${inc.urgency} ppl=${inc.people} ${inc.status}`}</title>
              <circle cx={p[0] + ox} cy={p[1] + 12} r={selected ? 11 : 8} fill={urgencyColor(inc.urgency)} stroke={selected ? "#fff" : "#0f172a"} strokeWidth={selected ? 2.5 : 1.5} />
              <text x={p[0] + ox} y={p[1] + 16} fontSize={9} fontWeight="bold" textAnchor="middle" fill="#0f172a">{inc.urgency}</text>
              {inc.kind === "recovery" && (
                <text x={p[0] + ox + 10} y={p[1] + 8} fontSize={11}>🛟</text>
              )}
            </g>
          );
        })}
        {/* boats */}
        {world.boats.map((b) => {
          const p = nodePos.get(b.node_id);
          if (!p) return null;
          const failed = b.status === "FAILED" || b.status === "STRANDED" || b.needs_recovery;
          const disc = disconnectedSet.has(b.boat_id);
          const selected = selectedResourceId === b.boat_id;
          return (
            <g key={b.boat_id} onClick={() => onSelectResource?.(b.boat_id)} style={{ cursor: onSelectResource ? "pointer" : "default" }}>
              <title>{`${b.boat_id} ${b.status} fuel=${b.fuel}`}</title>
              <rect x={p[0] - 22} y={p[1] - 22} width={17} height={13} rx={2} fill={failed ? "#ef4444" : disc ? "#64748b" : "#0ea5e9"} stroke={selected ? "#fff" : "#0f172a"} strokeWidth={selected ? 2.5 : 1.5} />
              <text x={p[0] - 13.5} y={p[1] - 11.5} fontSize={7.5} textAnchor="middle" fill="#fff">⛵</text>
              {(failed || disc) && (
                <text x={p[0] - 22} y={p[1] - 24} fontSize={10}>{failed ? "🔥" : "📡✕"}</text>
              )}
            </g>
          );
        })}
        {/* teams */}
        {world.teams.map((t) => {
          const p = nodePos.get(t.node_id);
          if (!p) return null;
          const selected = selectedResourceId === t.team_id;
          return (
            <g key={t.team_id} onClick={() => onSelectResource?.(t.team_id)} style={{ cursor: onSelectResource ? "pointer" : "default" }}>
              <title>{`${t.team_id} ${t.status}`}</title>
              <polygon
                points={`${p[0] + 20},${p[1] + 20} ${p[0] + 28},${p[1] + 20} ${p[0] + 24},${p[1] + 12}`}
                fill="#facc15"
                stroke={selected ? "#fff" : "#0f172a"}
                strokeWidth={selected ? 2.5 : 1.5}
              />
            </g>
          );
        })}
      </svg>
      <div className="px-1 text-[11px] text-slate-400">
        {world.nodes.length} nodes · {world.edges.length} edges · {incidentByNode.size} incident sites · {boatByNode.size} boat positions · edge refs: {Array.from(edgeById.keys()).slice(0, 8).join(", ")}{world.edges.length > 8 ? "…" : ""}
      </div>
    </div>
  );
}
