"use client";

import { useEffect, useMemo, useState } from "react";
import type { SimEvent, WorldState } from "../types";

const W = 760;
const H = 640;
const PAD = 76;

/** Lift markers just above their node so co-located shelter/incident glyphs stay readable. */
const MARKER_LIFT = 26;
/** Horizontal fan step for rescuers sharing one node; lone rescuers sit on-node. */
const FAN_STEP = 14;

interface Props {
  world: WorldState;
  events?: SimEvent[];
  selectedRouteEdgeIds?: string[];
  changedRouteEdgeIds?: string[];
  selectedIncidentId?: string | null;
  selectedResourceId?: string | null;
  disconnectedIds?: string[];
  tick?: number;
  motionDurationMs?: number;
  onSelectIncident?: (id: string) => void;
  onSelectResource?: (id: string) => void;
}

interface Rescuer {
  id: string;
  node_id: string;
  status: string;
  fuel: number | null;
  failed: boolean;
}

export default function SyntheticMap({
  world,
  events = [],
  selectedRouteEdgeIds = [],
  changedRouteEdgeIds = [],
  selectedIncidentId = null,
  selectedResourceId = null,
  disconnectedIds = [],
  tick,
  motionDurationMs = 1000,
  onSelectIncident,
  onSelectResource,
}: Props) {
  const positions = useMemo(() => {
    const maxX = Math.max(1, ...world.nodes.map((node) => node.x));
    const maxY = Math.max(1, ...world.nodes.map((node) => node.y));
    const result = new Map<string, [number, number]>();
    for (const node of world.nodes) {
      result.set(node.node_id, [PAD + (node.x / maxX) * (W - 2 * PAD), PAD + (node.y / maxY) * (H - 2 * PAD)]);
    }
    return result;
  }, [world.nodes]);

  const edgeById = useMemo(() => {
    const result = new Map<string, (typeof world.edges)[number]>();
    for (const edge of world.edges) result.set(edge.edge_id, edge);
    return result;
  }, [world.edges]);

  // Rescuers are anchored to their node: slots are assigned per node so a
  // lone rescuer sits exactly on its stop and co-located ones fan out in a
  // tight cluster instead of drifting across the map on a global grid.
  const rescuers = useMemo<(Rescuer & { dx: number; dy: number })[]>(() => {
    const all: Rescuer[] = [
      ...world.boats.map((boat) => ({
        id: boat.boat_id,
        node_id: boat.node_id,
        status: boat.status,
        fuel: boat.fuel,
        failed: boat.status === "FAILED" || boat.status === "STRANDED",
      })),
      ...world.teams.map((team) => ({
        id: team.team_id,
        node_id: team.node_id,
        status: team.status,
        fuel: null,
        failed: false,
      })),
    ];
    const slots = new Map<string, number>();
    return all.map((rescuer) => {
      const slot = slots.get(rescuer.node_id) ?? 0;
      slots.set(rescuer.node_id, slot + 1);
      return { ...rescuer, dx: ((slot % 3) - 1) * FAN_STEP, dy: Math.floor(slot / 3) * 16 };
    });
  }, [world.boats, world.teams]);

  // Markers glide between nodes only after first paint: rendering them
  // immediately (without the glide class) avoids a fly-in from the origin
  // while still letting the browser interpolate later moves.
  const [glide, setGlide] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setGlide(true), 50);
    return () => clearTimeout(timer);
  }, []);

  const disconnected = useMemo(() => new Set(disconnectedIds), [disconnectedIds]);

  const routeLine = (edgeId: string, className: string, stroke: string) => {
    const edge = edgeById.get(edgeId);
    if (!edge) return null;
    const a = positions.get(edge.from_node);
    const b = positions.get(edge.to_node);
    if (!a || !b) return null;
    return (
      <line
        key={`${className}-${edgeId}`}
        className={className}
        x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
        stroke={stroke} strokeWidth={5} strokeLinecap="round" opacity={0.85}
        pointerEvents="none"
      />
    );
  };

  return (
    <div className="map-visual">
      <div className="map-legend" aria-label="Map key">
        <span><i className="legend-square legend-shelter" />S = Shelter</span>
        <span><i className="legend-square legend-boat" />R = Rescuer</span>
        <span><i className="legend-square legend-request" />INC = Incident</span>
        <span>{world.nodes.length} nodes · {world.edges.length} edges</span>
        <span>closed ✕ blocked</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Offline synthetic response map, no tiles: ${world.nodes.length} nodes, ${world.edges.length} edges`}>
        {world.edges.map((edge, index) => {
          const a = positions.get(edge.from_node);
          const b = positions.get(edge.to_node);
          if (!a || !b) return null;
          const closed = edge.status === "closed";
          const disputed = edge.status === "disputed";
          const midX = (a[0] + b[0]) / 2;
          const midY = (a[1] + b[1]) / 2;
          const dx = b[0] - a[0];
          const dy = b[1] - a[1];
          const length = Math.max(1, Math.hypot(dx, dy));
          const labelOffset = ((index % 3) - 1) * 10;
          const labelX = midX - (dy / length) * labelOffset;
          const labelY = midY + (dx / length) * labelOffset;
          return (
            <g key={edge.edge_id}>
              <title>{`${edge.edge_id} ${edge.mode} ${edge.status}`}</title>
              <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={closed ? "#d96758" : edge.mode === "water" ? "#91bfcb" : "#9aada6"} strokeWidth={closed ? 4 : edge.mode === "water" ? 2.5 : 2} strokeDasharray={closed ? "8 5" : edge.mode === "water" ? "4 4" : undefined} strokeLinecap="round" />
              <text x={labelX} y={labelY} fontSize={11} fontWeight="bold" textAnchor="middle" dominantBaseline="central" fill={closed ? "#a43d32" : "#314c45"} stroke="#f5f9f7" strokeWidth={4} paintOrder="stroke">{edge.edge_id}</text>
              {closed && <text x={midX + 14} y={midY - 12} fontSize={13} fontWeight="bold" textAnchor="middle" fill="#a43d32" stroke="#f5f9f7" strokeWidth={3} paintOrder="stroke">✕</text>}
              {disputed && <text x={midX + 14} y={midY - 12} fontSize={13} fontWeight="bold" textAnchor="middle" fill="#8a6d1c" stroke="#f5f9f7" strokeWidth={3} paintOrder="stroke">⚠</text>}
            </g>
          );
        })}

        {changedRouteEdgeIds.map((edgeId) => routeLine(edgeId, "route-march-changed", "#2b7d8c"))}
        {selectedRouteEdgeIds.map((edgeId) => routeLine(edgeId, "route-march", "#c98f1f"))}

        {tick !== undefined && events.filter((event) => event.tick <= tick && event.tick >= tick - 2 && ["EDGE_CLOSED", "EDGE_DISPUTED", "BOAT_FAILED", "SHELTER_FULL", "INCIDENT_ARRIVAL"].includes(event.kind)).slice(-6).map((event, index) => {
          const detail = event.detail;
          const edgeId = typeof detail.edge_id === "string" ? detail.edge_id : undefined;
          const edge = edgeId ? world.edges.find((item) => item.edge_id === edgeId) : undefined;
          const incidentId = typeof detail.incident_id === "string" ? detail.incident_id : undefined;
          const boatId = typeof detail.boat_id === "string" ? detail.boat_id : undefined;
          const shelterId = typeof detail.shelter_id === "string" ? detail.shelter_id : undefined;
          const nodeId = edge
            ? undefined
            : world.incidents.find((item) => item.incident_id === incidentId)?.node_id
              ?? world.boats.find((item) => item.boat_id === boatId)?.node_id
              ?? world.shelters.find((item) => item.shelter_id === shelterId)?.node_id;
          const a = edge ? positions.get(edge.from_node) : undefined;
          const b = edge ? positions.get(edge.to_node) : undefined;
          const point = nodeId ? positions.get(nodeId) : undefined;
          const x = a && b ? (a[0] + b[0]) / 2 : point?.[0];
          const y = a && b ? (a[1] + b[1]) / 2 : point?.[1];
          if (x === undefined || y === undefined) return null;
          const color = event.kind === "INCIDENT_ARRIVAL" ? "#2788a6" : event.kind === "SHELTER_FULL" ? "#9066b0" : "#d45b49";
          return <circle key={`${event.tick}-${event.kind}-${index}`} cx={x} cy={y} r={16} fill="none" stroke={color} strokeWidth={3} className="event-flash" aria-label={`${event.kind} at step ${event.tick}`} />;
        })}

        {world.incidents.filter((incident) => incident.status !== "SERVED" && incident.status !== "CANCELLED").map((incident, index) => {
          const point = positions.get(incident.node_id);
          if (!point) return null;
          const offset = 15 + (index % 3) * 5;
          const fill = incident.urgency >= 5 ? "#c94335" : incident.urgency === 4 ? "#e87935" : incident.urgency === 3 ? "#d9a52f" : incident.urgency === 2 ? "#83a948" : "#378c68";
          const recovery = incident.kind === "recovery";
          return (
            <g key={incident.incident_id} transform={`translate(${point[0]} ${point[1]})`} onClick={() => onSelectIncident?.(incident.incident_id)} style={{ cursor: onSelectIncident ? "pointer" : "default" }}>
              <title>{`${incident.incident_id}, priority ${incident.urgency} of 5, ${incident.people} people, ${incident.status}`}</title>
              {tick !== undefined && incident.created_tick === tick && <circle cx={offset} cy={12} r={15} fill="none" stroke={fill} strokeWidth={2} className="incident-ping" />}
              <circle cx={offset} cy={12} r={selectedIncidentId === incident.incident_id ? 15 : 13} fill={fill} stroke="#fff" strokeWidth={selectedIncidentId === incident.incident_id ? 3 : 2} />
              {recovery
                ? <text x={offset} y={16} fontSize={12} fontWeight="bold" textAnchor="middle">🛟</text>
                : <text x={offset} y={16} fontSize={9} fontWeight="bold" textAnchor="middle" fill="#fff">INC</text>}
            </g>
          );
        })}

        {world.nodes.filter((node) => node.kind === "shelter").map((node) => {
          const point = positions.get(node.node_id);
          if (!point) return null;
          return <g key={node.node_id}><title>Shelter</title><circle cx={point[0]} cy={point[1]} r={14} fill="#48a879" stroke="#fff" strokeWidth={3} /><text x={point[0]} y={point[1] + 5} fontSize={15} fontWeight="bold" textAnchor="middle" fill="#fff">S</text></g>;
        })}

        {rescuers.map((rescuer) => {
          const point = positions.get(rescuer.node_id);
          if (!point) return null;
          const selected = selectedResourceId === rescuer.id;
          const x = point[0] + rescuer.dx;
          const y = point[1] - MARKER_LIFT - rescuer.dy;
          return (
            <g
              key={rescuer.id}
              className={glide ? "marker-glide" : undefined}
              transform={`translate(${x} ${y})`}
              onClick={() => onSelectResource?.(rescuer.id)}
              style={{ transitionDuration: `${motionDurationMs}ms`, cursor: onSelectResource ? "pointer" : "default" }}
            >
              <title>{rescuer.fuel === null ? `${rescuer.id} ${rescuer.status}` : `${rescuer.id} ${rescuer.status} fuel=${rescuer.fuel.toFixed(0)}`}</title>
              <circle r={13} fill={rescuer.failed ? "#a34335" : "#286c87"} stroke="#fff" strokeWidth={selected ? 3 : 2} />
              <text y={5} fontSize={14} fontWeight="bold" textAnchor="middle" fill="#fff">R</text>
              {rescuer.failed && <text x={14} y={-8} fontSize={13} textAnchor="middle">🔥</text>}
              {disconnected.has(rescuer.id) && <text x={-15} y={-8} fontSize={11} fontWeight="bold" textAnchor="middle">📡✕</text>}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
