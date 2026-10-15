"use client";

import { useMemo } from "react";
import type { SimEvent, WorldState } from "../types";

const W = 760;
const H = 640;
const PAD = 76;

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

export default function SyntheticMap({ world, events = [], selectedIncidentId = null, tick, motionDurationMs = 1000, onSelectIncident }: Props) {
  const positions = useMemo(() => {
    const maxX = Math.max(1, ...world.nodes.map((node) => node.x));
    const maxY = Math.max(1, ...world.nodes.map((node) => node.y));
    const result = new Map<string, [number, number]>();
    for (const node of world.nodes) {
      result.set(node.node_id, [PAD + (node.x / maxX) * (W - 2 * PAD), PAD + (node.y / maxY) * (H - 2 * PAD)]);
    }
    return result;
  }, [world.nodes]);

  return (
    <div className="map-visual">
      <div className="map-legend" aria-label="Map key">
        <span><i className="legend-square legend-shelter" />S = Shelter</span>
        <span><i className="legend-square legend-boat" />R = Rescuer</span>
        <span><i className="legend-square legend-request" />INC = Incident</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Map showing rescue requests, boats, shelters, and blocked roads">
        {world.edges.map((edge, index) => {
          const a = positions.get(edge.from_node);
          const b = positions.get(edge.to_node);
          if (!a || !b) return null;
          const closed = edge.status === "closed";
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
              <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={closed ? "#d96758" : edge.mode === "water" ? "#91bfcb" : "#9aada6"} strokeWidth={closed ? 4 : edge.mode === "water" ? 2.5 : 2} strokeDasharray={closed ? "8 5" : edge.mode === "water" ? "4 4" : undefined} strokeLinecap="round" />
              <text x={labelX} y={labelY} fontSize={11} fontWeight="bold" textAnchor="middle" dominantBaseline="central" fill={closed ? "#a43d32" : "#314c45"} stroke="#f5f9f7" strokeWidth={4} paintOrder="stroke">{edge.edge_id}</text>
            </g>
          );
        })}

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

        {world.nodes.filter((node) => node.kind === "shelter").map((node) => {
          const point = positions.get(node.node_id);
          if (!point) return null;
          return <g key={node.node_id}><title>Shelter</title><circle cx={point[0]} cy={point[1]} r={14} fill="#48a879" stroke="#fff" strokeWidth={3} /><text x={point[0]} y={point[1] + 5} fontSize={15} fontWeight="bold" fill="#fff" textAnchor="middle">S</text></g>;
        })}

        {world.incidents.filter((incident) => incident.status !== "SERVED" && incident.status !== "CANCELLED").map((incident, index) => {
          const point = positions.get(incident.node_id);
          if (!point) return null;
          const offset = 15 + (index % 3) * 5;
          const fill = incident.urgency >= 5 ? "#c94335" : incident.urgency === 4 ? "#e87935" : incident.urgency === 3 ? "#d9a52f" : incident.urgency === 2 ? "#83a948" : "#378c68";
          return (
            <g key={incident.incident_id} transform={`translate(${point[0]} ${point[1]})`} onClick={() => onSelectIncident?.(incident.incident_id)} style={{ cursor: onSelectIncident ? "pointer" : "default" }}>
              <title>{`${incident.incident_id}, priority ${incident.urgency} of 5, ${incident.people} people, ${incident.status}`}</title>
              {tick !== undefined && incident.created_tick === tick && <circle cx={offset} cy={12} r={15} fill="none" stroke={fill} strokeWidth={2} className="incident-ping" />}
              <circle cx={offset} cy={12} r={selectedIncidentId === incident.incident_id ? 15 : 13} fill={fill} stroke="#fff" strokeWidth={selectedIncidentId === incident.incident_id ? 3 : 2} />
              <text x={offset} y={16} fontSize={9} fontWeight="bold" textAnchor="middle" fill="#fff">INC</text>
            </g>
          );
        })}

        {[...world.boats, ...world.teams.map((team) => ({ boat_id: team.team_id, node_id: team.node_id, status: team.status, needs_recovery: false }))].map((rescuer, index) => {
          const point = positions.get(rescuer.node_id);
          if (!point) return null;
          const dx = (index % 3) * 18 - 18;
          const dy = Math.floor(index / 3) * 18;
          return <g key={rescuer.boat_id} className="marker-glide" style={{ transitionDuration: `${motionDurationMs}ms` }} transform={`translate(${point[0] + dx} ${point[1] - 30 - dy})`}><title>Rescuer</title><circle r={13} fill="#286c87" stroke="#fff" strokeWidth={2} /><text y={5} fontSize={14} fontWeight="bold" textAnchor="middle" fill="#fff">R</text></g>;
        })}
      </svg>
    </div>
  );
}
