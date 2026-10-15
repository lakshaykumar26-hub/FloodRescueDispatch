-- Phase 6 Step 02: initial schema (CONVENTIONS §6, 13 tables).
-- Every row carries simulation_id + tick. Snapshots reuse the Phase-1 JSON
-- format (version:1). assignment_history is append-only (never UPDATE).
-- SQLite dialect; Postgres-compatible types kept simple on purpose.

CREATE TABLE IF NOT EXISTS simulation_runs (
  simulation_id TEXT PRIMARY KEY,
  scenario_name TEXT NOT NULL,
  strategy TEXT NOT NULL,
  seed INTEGER NOT NULL,
  status TEXT NOT NULL,
  tick INTEGER NOT NULL DEFAULT 0,
  max_ticks INTEGER NOT NULL DEFAULT 120,
  created_at TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS locations (
  simulation_id TEXT NOT NULL,
  tick INTEGER NOT NULL,
  node_id TEXT NOT NULL,
  neighborhood TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT '',
  x REAL NOT NULL DEFAULT 0,
  y REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (simulation_id, node_id)
);

CREATE TABLE IF NOT EXISTS network_edges (
  simulation_id TEXT NOT NULL,
  tick INTEGER NOT NULL,
  edge_id TEXT NOT NULL,
  from_node TEXT NOT NULL,
  to_node TEXT NOT NULL,
  mode TEXT NOT NULL,
  travel_time INTEGER NOT NULL,
  status TEXT NOT NULL,
  risk_level REAL NOT NULL,
  capacity INTEGER NOT NULL,
  last_updated_tick INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (simulation_id, edge_id)
);

CREATE TABLE IF NOT EXISTS incidents (
  simulation_id TEXT NOT NULL,
  tick INTEGER NOT NULL,
  incident_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  urgency INTEGER NOT NULL,
  people INTEGER NOT NULL,
  required_capabilities TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL,
  created_tick INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL DEFAULT 'standard',
  caused_by TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (simulation_id, incident_id)
);

CREATE TABLE IF NOT EXISTS resources (
  simulation_id TEXT NOT NULL,
  tick INTEGER NOT NULL,
  resource_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  node_id TEXT NOT NULL,
  status TEXT NOT NULL,
  capacity INTEGER NOT NULL DEFAULT 0,
  fuel REAL NOT NULL DEFAULT 0,
  fuel_reserve REAL NOT NULL DEFAULT 0,
  passengers INTEGER NOT NULL DEFAULT 0,
  assignment_id TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (simulation_id, resource_id)
);

CREATE TABLE IF NOT EXISTS shelters (
  simulation_id TEXT NOT NULL,
  tick INTEGER NOT NULL,
  shelter_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  capacity INTEGER NOT NULL,
  occupancy INTEGER NOT NULL DEFAULT 0,
  reservations TEXT NOT NULL DEFAULT '{}',
  accepting INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (simulation_id, shelter_id)
);

CREATE TABLE IF NOT EXISTS simulation_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  simulation_id TEXT NOT NULL,
  tick INTEGER NOT NULL,
  seq INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_simulation_events_sim_tick
  ON simulation_events (simulation_id, tick);

CREATE TABLE IF NOT EXISTS assignments (
  simulation_id TEXT NOT NULL,
  assignment_id TEXT NOT NULL,
  tick INTEGER NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  proposal_id TEXT NOT NULL DEFAULT '',
  incident_id TEXT NOT NULL DEFAULT '',
  resource_id TEXT NOT NULL DEFAULT '',
  resource_kind TEXT NOT NULL DEFAULT '',
  shelter_id TEXT NOT NULL DEFAULT '',
  seats INTEGER NOT NULL DEFAULT 0,
  route_edge_ids TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL,
  cost REAL NOT NULL DEFAULT 0,
  created_tick INTEGER NOT NULL DEFAULT 0,
  history TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (simulation_id, assignment_id)
);

CREATE TABLE IF NOT EXISTS assignment_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  simulation_id TEXT NOT NULL,
  tick INTEGER NOT NULL,
  assignment_id TEXT NOT NULL,
  from_status TEXT NOT NULL DEFAULT '',
  to_status TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  actor TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_assignment_history_sim_asn
  ON assignment_history (simulation_id, assignment_id);

CREATE TABLE IF NOT EXISTS communication_messages (
  simulation_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  tick INTEGER NOT NULL,
  type TEXT NOT NULL DEFAULT '',
  sender_id TEXT NOT NULL DEFAULT '',
  recipient_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'QUEUED',
  payload TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (simulation_id, message_id)
);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  simulation_id TEXT NOT NULL,
  tick INTEGER NOT NULL,
  report_id TEXT NOT NULL DEFAULT '',
  subject_id TEXT NOT NULL DEFAULT '',
  claim TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  observed_at_tick INTEGER NOT NULL DEFAULT 0,
  received_at_tick INTEGER NOT NULL DEFAULT 0,
  confidence REAL NOT NULL DEFAULT 0,
  verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED'
);
CREATE INDEX IF NOT EXISTS idx_reports_sim_subject
  ON reports (simulation_id, subject_id);

CREATE TABLE IF NOT EXISTS state_snapshots (
  simulation_id TEXT NOT NULL,
  tick INTEGER NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  snapshot_json TEXT NOT NULL,
  PRIMARY KEY (simulation_id, tick)
);

CREATE TABLE IF NOT EXISTS simulation_metrics (
  simulation_id TEXT NOT NULL,
  tick INTEGER NOT NULL,
  strategy TEXT NOT NULL DEFAULT '',
  served INTEGER NOT NULL DEFAULT 0,
  unserved INTEGER NOT NULL DEFAULT 0,
  committed INTEGER NOT NULL DEFAULT 0,
  rejected_by_reason TEXT NOT NULL DEFAULT '{}',
  snapshots TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (simulation_id, tick)
);
