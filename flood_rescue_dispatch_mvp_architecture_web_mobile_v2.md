# Flood Rescue Dispatch --- Complete MVP Architecture (Web + Mobile)

> **Project:** Flood Rescue Dispatch Where Boats, Shelters and Roads
> Negotiate in Real Time\
> **Purpose:** Build a time-stepped, explainable flood-rescue simulation
> with a web command dashboard and an offline-first mobile app for field
> responders. It coordinates boats, ground teams, incidents, shelters,
> and communication channels under changing conditions, including periods
> without internet connectivity.

## 1. MVP goals

The MVP should demonstrate that the system can:

-   Model a changing flood environment using road and waterway graphs.
-   Track incidents, boats, ground teams, shelters, capacities, and
    resource states.
-   Compare centralized dispatch with decentralized agent negotiation.
-   Replan when routes close, boats fail, shelters fill, or new
    incidents appear.
-   Represent uncertain and contradictory reports without treating
    confidence as truth.
-   Simulate communication delays, dropped and duplicated messages,
    network partitions, and reconnection.
-   Preserve an auditable event log and explain why assignments were
    made, cancelled, or changed.
-   Provide a field-responder mobile app that can display a cached mission,
    record updates offline, and synchronize them when a communication path returns.
-   Evaluate response time, unmet demand, route violations, fairness,
    resource utilization, and recovery time.

**Scope boundary:** This is a simulation and prototype, not a validated
emergency-response system. Use synthetic locations and scenarios; do not
depend on live operational feeds for the MVP.

## 2. High-level architecture

```text
┌──────────────────────────────┐      ┌──────────────────────────────┐
│ WEB COMMAND DASHBOARD        │      │ MOBILE FIELD APP             │
│ Next.js + TypeScript         │      │ Expo + React Native + TS      │
│ Map · Incidents · Metrics    │      │ Mission · Route · Status      │
│ Dispatch Controls · Replay   │      │ Hazard Reports · Sync Queue  │
└──────────────┬───────────────┘      └──────────────┬───────────────┘
               │ REST / WebSocket / Sync API        │
               └─────────────────┬──────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│                         PYTHON BACKEND                            │
│                            FastAPI                                │
│                                                                  │
│  API + Validation          Simulation Controller                 │
│           │                         │                            │
│           ▼                         ▼                            │
│  ┌──────────────────────┐  ┌──────────────────────────────────┐  │
│  │ COMMUNICATION GATEWAY │  │ SIMULATION ENGINE                │  │
│  │ Queue · ACK · Retry   │  │ World · Clock · Events           │  │
│  │ Dedup · Expiry        │  │ Hazards · State · Snapshots      │  │
│  └──────────┬───────────┘  └────────────────┬─────────────────┘  │
│             │                               ▼                    │
│             │                ┌────────────────────────────────┐  │
│             │                │ AGENTS + DISPATCH ENGINE       │  │
│             │                │ Boat · Team · Incident         │  │
│             │                │ Shelter · Negotiation          │  │
│             │                │ Replanning · Safety Validation │  │
│             │                └────────────────────────────────┘  │
└─────────────┼────────────────────────────────────────────────────┘
              │
      ┌───────▼───────────────────────────────────────────────┐
      │ COMMUNICATION PATHS                                    │
      │ Simulated Network · Local Wi-Fi/LAN · Optional Radio   │
      └────────────────────────────────────────────────────────┘

┌──────────────────────────────┐      ┌──────────────────────────────┐
│ MOBILE DEVICE LOCAL STORAGE  │      │ SERVER PERSISTENCE            │
│ SQLite · Cached Mission      │      │ PostgreSQL / Supabase         │
│ Local Beliefs · Outbox        │      │ Runs · Events · Assignments  │
│ Pending Reports · Last Sync  │      │ Messages · Snapshots · Metrics│
└──────────────────────────────┘      └──────────────────────────────┘
```

The local agent runtimes can initially execute inside the same Python
process. Simulated communication delays and partitions make their
behavior resemble agents on separate devices. Separate deployments are
not required for the first MVP.

## 3. Recommended technology stack

  -----------------------------------------------------------------------
  Component               Technology              Responsibility
  ----------------------- ----------------------- -----------------------
  Frontend                Next.js + TypeScript    Dashboard and
                                                  simulation controls

  Styling                 Tailwind CSS            Responsive interface

  Map                     React Leaflet           Locations, routes,
                                                  hazards, boats,
                                                  incidents, shelters

  Charts                  Recharts                Performance and
                                                  fairness metrics

  Backend API             Python + FastAPI        API and orchestration

  Validation              Pydantic                Validate API payloads
                                                  and messages

  Simulation engine       Python                  Discrete-time world and
                                                  event processing

  Graph algorithms        NetworkX                Road/waterway graphs
                                                  and routing

  Agent coordination      Python modules          Bids, negotiation,
                                                  assignments, replanning

  Async messaging         Python `asyncio`        Simulated asynchronous
                                                  message handling

  Persistence             PostgreSQL via Supabase Durable records and run
                                                  history

  Live updates            WebSockets              Stream events and state
                                                  changes

  Testing                 pytest                  Routing, dispatch,
                                                  safety, partition,
                                                  replay tests

  Offline extension       Local Wi-Fi/LAN,        Controlled off-grid
                          optionally compatible   communication
                          radio-mesh hardware     experiments
  -----------------------------------------------------------------------

**Keep the MVP simple:** one modular Python backend, a web dashboard, a
mobile app, one database, and replaceable communication adapters. Do not start with
Kafka, Redis, Kubernetes, microservices, or an LLM; none is necessary to
prove the core idea.

Keep the simulation engine independent of FastAPI, the database, and the
frontend so it can be tested directly.

## 4. Suggested repository structure

``` text
flood-rescue-dispatch/
├── frontend/
│   ├── app/
│   ├── components/
│   │   ├── map/
│   │   ├── incidents/
│   │   ├── resources/
│   │   ├── communications/
│   │   ├── timeline/
│   │   └── metrics/
│   ├── hooks/
│   ├── lib/
│   └── types/
│
├── mobile/
│   ├── app/                       # Expo Router screens/routes
│   ├── components/
│   ├── features/
│   │   ├── missions/
│   │   ├── reports/
│   │   ├── communications/
│   │   └── sync/
│   ├── db/
│   │   ├── sqlite.ts
│   │   └── migrations/
│   ├── services/
│   │   ├── api.ts
│   │   ├── sync-engine.ts
│   │   ├── connectivity.ts
│   │   └── location.ts
│   ├── state/
│   ├── types/
│   ├── app.json
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── simulations.py
│   │   │   ├── state.py
│   │   │   ├── incidents.py
│   │   │   ├── assignments.py
│   │   │   ├── events.py
│   │   │   ├── communications.py
│   │   │   └── metrics.py
│   │   ├── simulation/
│   │   │   ├── engine.py
│   │   │   ├── world.py
│   │   │   ├── clock.py
│   │   │   ├── event_scheduler.py
│   │   │   ├── state_manager.py
│   │   │   └── snapshots.py
│   │   ├── agents/
│   │   │   ├── base_agent.py
│   │   │   ├── incident_agent.py
│   │   │   ├── boat_agent.py
│   │   │   ├── ground_team_agent.py
│   │   │   ├── shelter_agent.py
│   │   │   └── report_agent.py
│   │   ├── dispatch/
│   │   │   ├── scheduler_interface.py
│   │   │   ├── centralized_scheduler.py
│   │   │   ├── negotiation_scheduler.py
│   │   │   ├── bid_evaluator.py
│   │   │   ├── conflict_resolver.py
│   │   │   ├── commitment_manager.py
│   │   │   └── safety_validator.py
│   │   ├── routing/
│   │   │   ├── graph.py
│   │   │   ├── pathfinder.py
│   │   │   ├── route_validator.py
│   │   │   └── route_replanner.py
│   │   ├── communications/
│   │   │   ├── models.py
│   │   │   ├── gateway.py
│   │   │   ├── message_queue.py
│   │   │   ├── delivery_tracker.py
│   │   │   ├── deduplicator.py
│   │   │   ├── simulated_network.py
│   │   │   ├── wifi_adapter.py
│   │   │   └── radio_adapter.py
│   │   ├── evaluation/
│   │   │   ├── metrics.py
│   │   │   ├── fairness.py
│   │   │   └── experiment_runner.py
│   │   ├── persistence/
│   │   │   ├── repositories.py
│   │   │   └── database.py
│   │   └── schemas/
│   │       ├── incidents.py
│   │       ├── resources.py
│   │       ├── assignments.py
│   │       └── messages.py
│   ├── tests/
│   │   ├── test_routing.py
│   │   ├── test_boat_lifecycle.py
│   │   ├── test_dispatch.py
│   │   ├── test_safety_invariants.py
│   │   ├── test_network_partition.py
│   │   └── test_replay.py
│   ├── pyproject.toml
│   └── .env.example
│
├── scenarios/
│   ├── baseline.json
│   ├── bridge_closure.json
│   ├── boat_failure.json
│   ├── shelter_overflow.json
│   └── combined_disaster.json
│
└── README.md
```

Treat this as the target logical structure. Create modules as needed
while implementing each phase rather than generating empty files for
everything upfront.

## 5. Simulation world and graph model

Represent the environment as a time-varying graph:

\[ G_t=(V,E_t) \]

-   (V): intersections, rescue locations, shelters, boat stations, and
    transfer points.
-   (E_t): road and waterway edges currently represented in the
    simulation.
-   (G_t) changes as flood levels change, bridges close, waterways
    become unsafe, and routes reopen.

Example edge:

``` json
{
  "edge_id": "W-12",
  "from_node": "N-04",
  "to_node": "N-09",
  "mode": "water",
  "travel_time": 8,
  "status": "open",
  "risk_level": 0.2,
  "capacity": 1,
  "last_updated_tick": 14
}
```

These are illustrative values. Use synthetic time units initially and
define them consistently.

### Transport modes

**Boats** - Navigate waterway edges. - Have capacity, speed, fuel, and
operational status. - Require a feasible route and compatible landing or
transfer points. - Need a feasible destination and sufficient fuel under
the configured reserve policy.

**Ground rescue teams** - Navigate the road graph. - Cannot use closed
roads. - Have defined capabilities and availability. - May need a boat
or transfer point to reach isolated locations.

**Shelters** - Have location, capacity, occupancy, and incoming
reservations. - May become full, inaccessible, or unavailable. - Must
not be over-reserved.

**Incidents** - Have location, urgency, estimated people needing
assistance, required capabilities, creation tick, and report
confidence. - Can require boats, ground teams, or multiple transport
stages. - Have an explicit lifecycle such as `OPEN`, `ASSIGNED`,
`IN_PROGRESS`, `SERVED`, `CANCELLED`, or `UNRESOLVED`.

Use synthetic JSON scenarios first; do not depend on live map or flood
feeds.

## 6. Agent design

Agents are ordinary Python classes with explicit state and decision
rules. They do not need to be independent AI models.

  -----------------------------------------------------------------------
  Agent                   Owns or knows           Responsibility
  ----------------------- ----------------------- -----------------------
  Incident agent          Reported location,      Maintain incident state
                          urgency, estimated      and request resources
                          demand                  

  Boat agent              Position, capacity,     Evaluate and execute
                          fuel, mission, local    feasible missions
                          belief                  

  Ground-team agent       Position, capabilities, Respond to accessible
                          mission, local belief   incidents

  Shelter agent           Location, occupancy,    Accept or reject
                          reservations, capacity  incoming arrivals

  Report agent            Source, observation     Submit and track
                          time, confidence, claim potentially conflicting
                                                  reports
  -----------------------------------------------------------------------

Example:

``` python
class BoatAgent:
    def __init__(self, boat_id, capacity, fuel, location):
        self.id = boat_id
        self.capacity = capacity
        self.fuel = fuel
        self.location = location
        self.status = "AVAILABLE"
        self.assignment_id = None
        self.passengers = 0
        self.local_belief = {}
```

The global simulation state and each agent's local belief must be
separate. Otherwise, an offline boat would automatically know every
update, defeating the purpose of communication simulation.

### Boat lifecycle

``` text
AVAILABLE
   -> ASSIGNED
   -> EN_ROUTE_TO_INCIDENT
   -> RESCUING
   -> TRANSPORTING_TO_SHELTER
   -> RECOVERY
   -> AVAILABLE
```

Exception states include `UNAVAILABLE`, `FAILED`, `STRANDED`,
`RETURNING`, and `MAINTENANCE`.

If a boat fails while carrying passengers, create an explicit recovery
workflow. Do not simply delete the assignment or mark the passengers as
rescued.

## 7. Dispatch engine

Expose two scheduling strategies behind one interface so they can be
compared under the same scenarios.

### 7.1 Centralized baseline

1.  Rank incidents using urgency and waiting time.
2.  Generate compatible resource candidates.
3.  Calculate feasible routes and estimated travel times.
4.  Check capacity, fuel, transport compatibility, and shelter
    availability.
5.  Score candidate assignments.
6.  Resolve competing claims on resources and shelter capacity.
7.  Run safety validation.
8.  Commit the assignment and record the decision.

Start with a simple greedy scheduler. More advanced optimization can be
added after the baseline is tested.

### 7.2 Decentralized negotiation

``` text
Incident detected
      |
      v
Incident publishes a rescue request
      |
      v
Eligible resource agents receive the request
      |
      v
Agents evaluate feasibility and submit bids
      |
      v
Conflict resolver evaluates competing bids
      |
      v
Safety validator checks the proposal
      |
      v
Assignment is committed
      |
      v
Resource acknowledges the assignment
```

Example bid:

``` json
{
  "agent_id": "BOAT-03",
  "incident_id": "INC-08",
  "estimated_arrival": 12,
  "estimated_completion": 31,
  "risk_score": 0.15,
  "people_capacity": 6,
  "fuel_feasible": true,
  "shelter_feasible": true,
  "belief_version": 17
}
```

### 7.3 Bid scoring

A simple initial cost function is:

\[ C(r,i)=w_tT(r,i)+w_rR(r,i)+w_fF(r,i)+w_oO(r,i) \]

Where:

-   (T): estimated travel time.
-   (R): route risk.
-   (F): fairness adjustment.
-   (O): opportunity cost of assigning the resource to this incident
    instead of another.
-   (w_t,w_r,w_f,w_o): configurable weights.

Lower-cost feasible bids are preferable. Urgency, waiting time, and
service requirements must also influence scheduling.

**Hard safety constraints must not be reduced to score penalties.** A
prohibited route, failed resource, incompatible transport mode, or
unavailable destination must cause the proposal to be rejected.

### 7.4 Assignment states and duplicate prevention

Use explicit states such as:

`PROPOSED -> COMMITTED -> ACKNOWLEDGED -> IN_PROGRESS -> COMPLETED`

Other transitions include `REJECTED`, `EXPIRED`, `CANCELLED`, and
`REQUIRES_RECONCILIATION`.

Every assignment should have a unique ID, version, resource owner,
incident, destination, and history.

Disconnected agents can hold conflicting beliefs about ownership. Use an
authoritative coordinator when reachable, idempotent messages, version
checks, and explicit reconciliation after reconnection. Do not claim
that leases or a central database guarantee unique assignments during a
complete network partition if disconnected parties can independently
commit work.

## 8. Communication architecture and offline operation

The system should work as an offline-first **simulation** and be
designed so local communications can later be connected through
adapters.

``` text
Flood Dispatch App
       |
       v
Communication Gateway
  - Message validation
  - Priority queue
  - Delivery tracking
  - Retry and deduplication
  - Expiry and version checks
  - Offline persistence
       |
       +------------------+-------------------+
       |                  |                   |
 Simulated Network     Local Wi-Fi        Radio-Mesh Adapter
       |                  |                   |
       +------------------+-------------------+
                          |
                    Local Agents
```

### Communication modes

  -----------------------------------------------------------------------
  Mode                    Internet required?      Use
  ----------------------- ----------------------- -----------------------
  Simulated network       No                      Test delay, loss,
                                                  duplication,
                                                  partitions, and
                                                  recovery

  Local Wi-Fi/LAN         Not necessarily; local  Run the application on
                          equipment must remain   a local network
                          powered and operational 

  Radio-mesh adapter      A compatible mesh can   Optional physical
                          operate without         messaging experiment
                          internet, subject to    
                          hardware and            
                          configuration           

  Internet                Yes                     Optional remote
                                                  monitoring or
                                                  synchronization
  -----------------------------------------------------------------------

Implement the simulated network first, local LAN second, and physical
radio integration only after the protocol and safety checks work.

### Message envelope

``` json
{
  "message_id": "MSG-00142",
  "type": "ASSIGNMENT_OFFER",
  "sender_id": "DISPATCH-01",
  "recipient_id": "BOAT-03",
  "simulation_id": "SIM-001",
  "created_at_tick": 42,
  "expires_at_tick": 52,
  "version": 3,
  "payload": {
    "assignment_id": "ASN-00031",
    "incident_id": "INC-08",
    "destination_id": "SHELTER-02"
  }
}
```

Use simulation ticks for deterministic experiments. A physical
deployment would also need appropriate real-time timestamps.

### Message types

-   `INCIDENT_CREATED`
-   `ASSIGNMENT_OFFER`
-   `ASSIGNMENT_ACCEPTED`
-   `ASSIGNMENT_CANCELLED`
-   `BOAT_POSITION`
-   `BOAT_STATUS_CHANGED`
-   `HAZARD_REPORTED`
-   `SHELTER_CAPACITY_CHANGED`
-   `MESSAGE_ACK`

### Gateway requirements

1.  **Store-and-forward:** Persist messages that cannot currently be
    delivered.
2.  **Acknowledgements:** Track receipt separately from acceptance or
    completion.
3.  **Retries:** Retry eligible messages after connectivity returns.
4.  **Deduplication:** Avoid processing the same message twice.
5.  **Expiry:** Reject obsolete commands and stale offers.
6.  **Versioning:** Detect outdated state and conflicting updates.
7.  **Reconciliation:** Compare local and authoritative state after
    reconnection.
8.  **Validation:** Validate sender, message type, schema, and permitted
    transition.
9.  **Priority:** Prioritize configured safety-critical messages over
    routine telemetry.
10. **Audit:** Keep a record of message lifecycle and retries.

Do not assume `sent = delivered = acknowledged = accepted = completed`.

When disconnected, a boat cannot know about a new incident or an unseen
hazard unless the information reaches it over an available channel. If
every channel is unavailable, the agent must follow explicit local
operating rules and treat stale route information conservatively. A
communication adapter alone does not guarantee connectivity.

## 9. Dynamic replanning and event processing

Use a deterministic, discrete-time simulation loop:

``` text
1. Advance simulation clock
2. Apply scheduled flood and infrastructure events
3. Update the global world state
4. Deliver messages whose delivery conditions are met
5. Update each agent's local belief from received messages
6. Advance resources along valid routes
7. Update incidents, passenger counts, and shelter occupancy
8. Detect failed or invalid commitments
9. Cancel, suspend, or mark commitments for reconciliation
10. Generate replacement proposals and bids
11. Resolve conflicts and validate safety invariants
12. Commit feasible assignments
13. Queue outbound messages
14. Record events, metrics, and periodic snapshots
15. Publish dashboard updates
```

The precise ordering should be documented and kept deterministic. For
example, define whether a bridge closure scheduled for tick 40 is
applied before resources move during tick 40.

### Combined failure scenario

At tick 40:

-   A bridge closes.
-   Boat 2 fails.
-   Shelter 1 reaches capacity.
-   A new high-urgency incident appears.
-   Boat 3 loses connectivity.

Expected behavior:

1.  Update the edge and resource states.
2.  Revalidate routes and assignments affected by the bridge closure.
3.  Start a recovery workflow if Boat 2 has passengers aboard.
4.  Recalculate destination feasibility after Shelter 1 fills.
5.  Reassign affected work through the dispatch engine.
6.  Queue messages for Boat 3 rather than pretending they were received.
7.  Record each cancellation, proposal, rejection, and reassignment with
    a reason.
8.  On reconnection, reconcile Boat 3's stale mission and route before
    it resumes normal work.

### Contradictory reports

Store reports independently instead of overwriting one with another.

``` json
{
  "report_id": "RPT-018",
  "subject_id": "W-12",
  "claim": "CLOSED",
  "source": "BOAT-03",
  "observed_at_tick": 38,
  "received_at_tick": 42,
  "confidence": 0.9,
  "verification_status": "UNVERIFIED"
}
```

When reports conflict:

-   Preserve source and observation time.
-   Record the disagreement.
-   Update the system's belief about the affected edge.
-   Apply a conservative route policy to safety-critical disputed edges.
-   Allow later evidence to change the belief.
-   Explain why a route was restricted or reopened.

Confidence is evidence about a report, not proof of its correctness.

## 10. Safety invariants

Create a dedicated safety validator. Every proposed assignment must pass
its checks before being committed.

  -----------------------------------------------------------------------
  Invariant                           Requirement
  ----------------------------------- -----------------------------------
  Route safety                        No committed route uses a
                                      prohibited edge

  Resource availability               Failed or unavailable resources
                                      cannot accept new missions

  Exclusive assignment                A resource cannot hold conflicting
                                      active assignments

  Boat capacity                       Passenger load must fit within
                                      operational capacity

  Shelter capacity                    Occupancy plus reservations must
                                      remain within available capacity

  Transport compatibility             The resource must be able to reach
                                      and serve the incident

  Fuel feasibility                    Boat fuel must satisfy the
                                      configured reserve policy

  Assignment validity                 Expired or cancelled assignments
                                      cannot remain active

  Passenger recovery                  A failed resource carrying
                                      passengers triggers a recovery
                                      workflow

  State consistency                   Assignment commits validate against
                                      the latest authoritative state
                                      available to the coordinator

  Message idempotency                 Duplicate delivery must not
                                      duplicate an assignment or state
                                      transition
  -----------------------------------------------------------------------

Track shelter occupancy separately from reservations for expected
arrivals. Multiple boats must not reserve the same remaining capacity.

Validate and commit competing assignments atomically in the
authoritative coordinator. During a partition, represent unresolved
ownership or capacity claims explicitly rather than pretending the
global state is fully known.

These invariants improve simulation rigor but do not, by themselves,
make the system suitable for real emergency operations.

## 11. Database architecture

Use PostgreSQL through Supabase for durable records. Keep active state
in memory initially, persisting important events, assignments, and
snapshots.

  -----------------------------------------------------------------------
  Table                               Purpose
  ----------------------------------- -----------------------------------
  `simulation_runs`                   Scenario, strategy, configuration,
                                      status, random seed

  `locations`                         Synthetic nodes, shelters,
                                      stations, incident locations

  `network_edges`                     Road/waterway connectivity and
                                      status

  `incidents`                         Incident details, urgency,
                                      lifecycle

  `resources`                         Boats and ground teams

  `shelters`                          Capacity, occupancy, reservations

  `simulation_events`                 Closures, failures, flood changes,
                                      injected reports

  `assignments`                       Current assignment state and linked
                                      entities

  `assignment_history`                Proposals, commits, cancellations,
                                      reassignment decisions

  `communication_messages`            IDs, status, delivery attempts,
                                      expiry

  `reports`                           Claims, sources, confidence,
                                      contradictions

  `state_snapshots`                   State at selected ticks

  `simulation_metrics`                Metrics used for comparison
  -----------------------------------------------------------------------

### Persistence guidelines

-   Give each run a unique ID.
-   Associate events with their run and simulation tick.
-   Preserve assignment history instead of overwriting important
    transitions.
-   Distinguish queued, delivered, acknowledged, rejected, and expired
    messages.
-   Save enough state in snapshots to restore or replay a run.
-   Use deterministic random seeds.
-   Avoid writing every tiny state mutation to the database if periodic
    snapshots and a complete meaningful event log suffice.

## 12. API design

Use REST for control and queries and WebSockets for live updates.

  ----------------------------------------------------------------------------------------
  Method                  Endpoint                                 Purpose
  ----------------------- ---------------------------------------- -----------------------
  `POST`                  `/api/simulations`                       Create a run from a
                                                                   scenario

  `POST`                  `/api/simulations/{id}/start`            Start the run

  `POST`                  `/api/simulations/{id}/pause`            Pause the run

  `POST`                  `/api/simulations/{id}/step`             Advance one tick

  `GET`                   `/api/simulations/{id}/state`            Current world state

  `GET`                   `/api/simulations/{id}/events`           Event history

  `GET`                   `/api/simulations/{id}/assignments`      Assignment history

  `POST`                  `/api/simulations/{id}/events`           Inject a test event

  `GET`                   `/api/simulations/{id}/metrics`          Evaluation results

  `POST`                  `/api/simulations/{id}/replay`           Replay a completed run

  `GET`                   `/api/simulations/{id}/communications`   Network and message
                                                                   status

  `WS`                    `/ws/simulations/{id}`                   Stream state and event
                                                                   updates
  ----------------------------------------------------------------------------------------

API handlers should call the simulation engine rather than independently
implementing scheduling or state transitions.

## 13. Frontend dashboard

The dashboard should explain both the current situation and the reasons
behind the system's decisions.

### Main map

-   Distinguish roads from waterways.
-   Show open, closed, and disputed edges.
-   Display boats, teams, incidents, shelters, and current assignments.
-   Draw planned routes and highlight route changes.
-   Mark failed and disconnected resources.

### Incident and resource panels

-   Incident urgency, waiting time, estimated demand, and status.
-   Resource status, current mission, estimated arrival, capacity, and
    fuel.
-   Shelter occupancy, reservations, and remaining capacity.

### Decision explanation panel

For every assignment or reassignment, display: - Selected resource and
incident. - Alternative candidates. - Estimated arrival and completion
times. - Reasons alternative bids were rejected. - Safety constraints
applied. - Information that was stale or unavailable.

### Communication monitor

-   Connected and disconnected agents.
-   Queued messages and delivery status.
-   Delays, retries, expiry, and network partitions.
-   Reconciliation status after reconnection.

### Controls and metrics

-   Play, pause, step, speed control.
-   Inject predefined events.
-   Select centralized or negotiation strategy.
-   Replay completed runs.
-   Compare metrics across strategies.

## 14. Evaluation plan

Compare the centralized baseline with decentralized negotiation using
identical scenarios and, where applicable, identical random seeds.
Repeat experiments across multiple seeds to avoid relying on one
outcome.

  -----------------------------------------------------------------------
  Metric                              Definition
  ----------------------------------- -----------------------------------
  Time to service                     Time from incident creation to a
                                      clearly defined service milestone

  Unmet requests                      Incidents or people not served by
                                      the simulation deadline

  Resource idle time                  Time a resource is available but
                                      not doing productive work

  Route violations                    Committed or executed route steps
                                      that violate configured constraints

  Fairness                            Differences in service outcomes
                                      across neighborhoods

  Recovery time                       Time from disruption to a valid
                                      replacement plan

  Assignment latency                  Time from eligible request to
                                      committed assignment

  Message delivery latency            Time between message creation and
                                      delivery

  Queue length                        Number of messages waiting for
                                      delivery

  Reconciliation time                 Time needed to resolve state
                                      differences after reconnection
  -----------------------------------------------------------------------

Define service milestones precisely. Reaching an incident is not the
same as delivering people to a shelter.

A simple neighborhood service-time disparity metric is:

\[
F\_{`\text{gap}`{=tex}}=`\max`{=tex}\_n(`\bar `{=tex}T_n)-`\min`{=tex}\_n(`\bar `{=tex}T_n)
\]

where (`\bar `{=tex}T_n) is average service time for neighborhood (n).
Interpret this alongside urgency and unmet demand; a scheduler must not
improve averages by leaving difficult incidents unserved.

### Required scenarios

  Scenario                 What it tests
  ------------------------ ---------------------------------------------
  Baseline flood           Normal dispatch
  Simultaneous incidents   Resource contention
  Bridge closure           Dynamic routing
  Boat failure             Resource replacement and passenger recovery
  Shelter overflow         Destination reassignment
  Network partition        Offline operation and delayed messages
  Contradictory reports    Uncertainty handling
  Duplicate messages       Idempotent processing
  Reconnection             State reconciliation
  Combined disaster        Multiple simultaneous failures

## 15. Initial synthetic scenario

Start with a manageable world.

  Entity                  Initial quantity
  --------------------- ------------------
  Locations                             25
  Road edges                            25
  Waterway edges                        20
  Incidents                             12
  Boats                                  5
  Ground rescue teams                    5
  Shelters                               4
  Neighborhoods                          4

These are configurable starting values, not hard limits. Ensure some
incidents are road-accessible, some water-accessible, and some require
multi-stage transport. Include a few isolated areas and alternate routes
so disruptions matter.

Give each scenario a fixed random seed. Make flood progression, incident
arrivals, speeds, communication reliability, and shelter capacity
configurable.

## 16. Implementation roadmap

### Phase 1 --- Simulation foundation

-   Synthetic graph and world model.
-   Incident, resource, and shelter models.
-   Simulation clock and event scheduler.
-   Graph routing.
-   Boat and ground-team state machines.
-   Shelter occupancy and reservation tracking.

**Done when:** A simulation can run from start to finish without a
frontend.

### Phase 2 --- Centralized dispatch

-   Candidate assignment generation.
-   Feasibility checks and bid scoring.
-   Assignment commitments.
-   Route and capacity validation.
-   Event logging.

**Done when:** Feasible incidents receive assignments and invalid
assignments are rejected.

### Phase 3 --- Agent negotiation

-   Agent-local state and beliefs.
-   Proposal and bid messages.
-   Conflict resolution.
-   Assignment acceptance and cancellation.
-   Shared scheduler interface.

**Done when:** The same scenario can run under either scheduling
strategy.

### Phase 4 --- Dynamic events

-   Bridge closures and flood progression.
-   Boat failure.
-   Shelter overflow.
-   Conflicting reports.
-   Commitment invalidation and reassignment.

**Done when:** Disruptions cause explicit, auditable replanning without
silently violating configured invariants.

### Phase 5 --- Communication simulation

-   Message router with delay, loss, duplication, and reordering.
-   Network partitions and reconnection.
-   Persistent queues, acknowledgements, retries, and expiry.
-   Deduplication and reconciliation.

**Done when:** Disconnected agents retain stale beliefs and reconnect
without silently erasing conflicts.

### Phase 6 --- Dashboard and replay

-   Interactive map.
-   Incident and resource panels.
-   Event timeline.
-   Decision explanations.
-   Communication monitor.
-   Metric charts and replay.

**Done when:** A reviewer can follow a disruption and understand why the
system changed its assignments.

### Phase 7 --- Optional physical communications

1.  Run the backend on a suitable local machine.
2.  Connect another device over local Wi-Fi and test with internet
    disconnected.
3.  Add a compatible radio adapter if desired.
4.  Test delayed delivery, disconnection, duplicates, and recovery in a
    controlled setting.
5.  Document limitations and keep the system clearly labeled as a
    prototype.

Actual emergency use would require qualified operational,
communications, security, and safety review.

## 17. Testing checklist

### Routing and resources

-   A closed edge is never selected for a new route.
-   A boat without sufficient fuel is rejected.
-   A boat cannot exceed capacity.
-   A failed resource cannot receive a new mission.
-   A full shelter cannot accept additional reservations.
-   A failed boat with passengers triggers recovery logic.

### Dispatch and commitments

-   One resource cannot receive conflicting active assignments.
-   Competing bids are resolved deterministically under a fixed seed.
-   Every rejected proposal has a reason.
-   A cancellation invalidates the previous commitment.
-   Replanning preserves assignment history.

### Communications

-   Duplicate messages do not cause duplicate transitions.
-   Expired assignment offers are rejected.
-   Delayed and out-of-order messages are handled.
-   Disconnected agents do not receive global updates magically.
-   Reconnection detects stale or conflicting state.
-   An unacknowledged message is not treated as accepted.

### Replay and evaluation

-   A fixed seed produces reproducible simulation behavior.
-   Snapshots can restore the relevant state.
-   Replay preserves event order.
-   Metrics are calculated from recorded data and documented
    definitions.

## 18. Mobile field app architecture

The mobile app complements the web dashboard; it does not replace the central dispatch engine.

- **Web dashboard:** used by command staff to inspect the whole simulation, compare bids, inject events, and oversee dispatch.
- **Mobile app:** used by a boat or ground-team responder to view its accepted mission, follow the last known route, send status updates, and report hazards.
- **Backend:** remains the source of authoritative assignments when reachable. The mobile app must never assume that a locally queued event has already reached dispatch.

### 18.1 Recommended mobile stack

| Component | Recommendation | Purpose |
|---|---|---|
| App framework | Expo + React Native + TypeScript | Shared Android/iOS application code |
| Navigation | Expo Router | Screen and route organization |
| Local persistence | `expo-sqlite` | Store cached missions, local event history, and an outbox across app restarts |
| Connectivity | `@react-native-community/netinfo` | Detect network state changes; distinguish network connectivity from successful backend reachability |
| Secure credentials | `expo-secure-store` | Store device credentials or refresh tokens securely |
| Optional notifications | `expo-notifications` | Best-effort notifications when a notification service is available |
| Synthetic map | `react-native-svg` | Draw the MVP's synthetic road/water graph without requiring online map tiles |
| Physical map (later) | A mobile map library with a deliberate offline-map strategy | Real-world geography, subject to map-data licensing and tile-storage constraints |
| API client | Typed REST client | Communicate with the same FastAPI backend |
| Live updates | WebSocket when reachable | Receive state changes while a working network path exists |

Use a development build when native modules and production-like notification behavior are needed. Expo's official documentation explains development builds and the native functionality they provide: <https://docs.expo.dev/develop/development-builds/introduction/>.

SQLite persistence is useful because records can survive app restarts: <https://docs.expo.dev/versions/latest/sdk/sqlite/>. NetInfo can observe network-state changes, but a connected Wi-Fi icon alone does not prove that the backend or radio gateway is reachable: <https://docs.expo.dev/versions/latest/sdk/netinfo/>.

### 18.2 Mobile app screens

**1. Sign-in and device setup**
- Authenticate the responder.
- Associate the device with a responder/resource ID and role.
- Download initial configuration and the responder's permitted data.
- Show the configured dispatch server or local gateway connection state.

**2. My mission**
- Show the currently committed assignment, assignment ID/version, incident, destination, and last synchronization time.
- Clearly distinguish `COMMITTED`, `ACKNOWLEDGED`, `IN_PROGRESS`, `PENDING_SYNC`, `CANCELLED`, and `COMPLETED`.
- Display stale-data warnings when the app is offline or mission data has exceeded its configured freshness limit.

**3. Route and situation**
- Display the route and hazard information last received by the device.
- Highlight its age and source.
- For the synthetic MVP graph, draw nodes and edges locally so the screen works without online tiles.
- If location permission is granted, optionally display current device position. If permission is unavailable, allow explicit manual position/status updates.
- Never imply that an old cached route reflects current flood conditions.

**4. Mission status**
- Record departure, arrival, rescue started, passenger count, destination arrival, and recovery status as appropriate to the simulation.
- Require confirmation for important transitions.
- Store the event locally first when offline and visibly label it as awaiting synchronization.

**5. Hazard/report form**
- Select a map node/edge or location.
- Record the observation, type, optional confidence, and observation time.
- Optionally attach a photo as a later enhancement; do not make photo upload a requirement for the MVP.
- Keep the report in the local outbox when no communication path is available.

**6. Connection and sync status**
- Show backend/LAN/gateway reachability separately from general device connectivity.
- Show pending messages, last successful synchronization, retry count, and rejected/expired updates.
- Allow the user to inspect why an update could not be synchronized.

### 18.3 Offline-first data model

Use SQLite tables along these lines:

- `cached_missions`: latest known committed assignment and version.
- `cached_routes`: route snapshot, source/version, and last-update time.
- `cached_hazards`: hazards known to this device and their freshness metadata.
- `local_events`: locally recorded status changes and observations.
- `outbox`: events waiting to be transmitted.
- `inbox`: processed message IDs to help prevent duplicate handling.
- `sync_state`: last successful synchronization and server cursor/version.
- `device_settings`: non-secret configuration.

Each locally created event should have a stable unique event ID, device ID, mission/assignment ID when applicable, creation time, local sequence, event type, payload, and base version. Re-sending an event must reuse the same ID so the server can process it idempotently.

Example outbox event:

```json
{
  "event_id": "EVT-DEVICE-0031",
  "device_id": "DEVICE-07",
  "assignment_id": "ASN-00031",
  "type": "ARRIVED_AT_INCIDENT",
  "local_sequence": 31,
  "created_at": "2026-10-15T12:30:00Z",
  "base_assignment_version": 3,
  "sync_status": "PENDING"
}
```

The timestamp above is illustrative. Store actual timestamps in a defined format, and maintain simulation ticks separately when operating in simulation mode.

### 18.4 Mobile synchronization flow

```text
Responder records an event
          |
          v
Persist event to SQLite
          |
          v
Display event as PENDING SYNC
          |
          v
Is an approved communication path reachable?
       /                    \
     No                      Yes
     |                        |
Keep in outbox         Send event batch
     |                        |
Wait for connectivity   Server validates ID,
or local gateway        version, permissions,
to return               expiry, and transition
                              |
                      ┌───────┴────────┐
                      │                │
                   Accepted          Rejected
                      │                │
               Mark acknowledged   Store reason and
               Update cursor       show conflict
```

The backend should return a per-event result such as `ACCEPTED`, `DUPLICATE`, `REJECTED_STALE`, `REJECTED_INVALID`, or `REQUIRES_RECONCILIATION`. The client should remove or mark events as synchronized only after receiving the corresponding result.

Recommended sync triggers:
- App launch or foregrounding.
- A network/gateway reachability transition.
- User-initiated retry.
- A successful acknowledgement that indicates more queued events can be sent.

Background sync may be opportunistic only. Mobile operating systems can defer background work, and its execution is not a guarantee of immediate delivery. Expo's background-task documentation describes this platform-managed behavior: <https://docs.expo.dev/versions/latest/sdk/background-task/>. Critical updates must not depend solely on scheduled background execution or push notifications.

### 18.5 What offline does and does not mean

**Offline storage is not itself a communication network.** If there is no internet, local LAN, radio link, or other usable path, the app can save information but cannot send it to dispatch or receive new assignments.

During an outage, the app can:
- Display the last committed mission and cached route.
- Record progress and hazard observations locally.
- Queue events with stable IDs.
- Warn that its information may be stale.
- Apply carefully defined local restrictions.

It cannot:
- Learn about a new incident that has not reached the device.
- Know about a hazard that it has not received or observed.
- Claim an offline update has reached dispatch.
- Safely assume an old route is still valid.
- Independently create globally authoritative assignment ownership.

For the MVP, allow local recording of progress on a previously committed mission. Do not let a disconnected phone silently commit new global assignments. If physical radio is later added, the app must communicate through a compatible radio or gateway integration; a normal phone internet connection cannot be assumed to provide off-grid messaging.

### 18.6 Security and data integrity

- Authenticate devices and enforce role-based authorization on the server.
- Validate each event and allowed state transition.
- Use TLS when transport supports it; do not treat a local network as inherently trusted.
- Store credentials in platform secure storage, not in plain-text app settings.
- Minimize sensitive information in local caches and clear it when a device is decommissioned.
- Use unique IDs, idempotent event handling, versions, and audit logs.
- Treat device location and user-submitted reports as untrusted inputs until validated.
- Avoid exposing all incidents or resource details to every mobile user; return only data appropriate to the user's role and assignment.

### 18.7 Mobile-specific test checklist

- The app retains a queued event after being force-closed and reopened.
- A repeated upload does not duplicate a status transition.
- The UI clearly distinguishes locally stored events from server-acknowledged events.
- A disconnected app shows the age of cached mission and hazard data.
- A stale or cancelled assignment is rejected or flagged during synchronization.
- Reconnection handles duplicate and out-of-order events.
- Permission denial for location does not make core mission workflows unusable.
- The app can use the synthetic graph without external map tiles.
- Backend unavailability is detected even when Wi-Fi itself is connected.
- Background execution is treated as best-effort, not as a dependable emergency message channel.

### 18.8 Mobile implementation sequence

1. Create the Expo + React Native + TypeScript app and basic navigation.
2. Connect sign-in and read-only mission APIs.
3. Build mission, route, resource status, and hazard-report screens.
4. Add SQLite caching and a persistent outbox.
5. Add batch sync with server acknowledgements, version checks, and idempotency.
6. Simulate offline/online transitions and test stale data.
7. Add WebSocket updates while connected.
8. Add optional local-network gateway support.
9. Explore radio hardware only after the adapter protocol and end-to-end tests pass.
10. Add optional push notifications for non-guaranteed alerts when a supported push service is available. Do not rely on push to operate through a complete connectivity outage.

Official Expo notification documentation: <https://docs.expo.dev/versions/latest/sdk/notifications/>.

## 19. Final architecture decisions

1. **One modular backend:** one FastAPI application with clearly separated simulation, agent, dispatch, routing, communications, evaluation, and persistence modules.
2. **Two purpose-built clients:** a Next.js web dashboard for command staff and an Expo React Native mobile app for field responders, sharing the same backend and API contracts.
3. **Simulation-first:** prove the world model and centralized scheduler before adding negotiation.
4. **Shared scheduler interface:** compare centralized and decentralized strategies fairly.
5. **Separate local beliefs:** offline agents must not automatically know the global state.
6. **Communication adapters:** simulated network first, local LAN next, physical radio optional.
7. **Offline-first mobile behavior:** cache missions and queue local events, while distinguishing stored, sent, acknowledged, and accepted states.
8. **Hard safety invariants:** unsafe or infeasible assignments are rejected rather than merely penalized.
9. **Auditable decisions:** every proposal, commitment, cancellation, message, and reassignment should be explainable.
10. **Synthetic data and reproducible evaluation:** use synthetic scenarios, fixed seeds, explicit metrics, and repeated experiments.
11. **No premature infrastructure:** avoid distributed services until the prototype demonstrates a concrete need.

The core contribution is the combination of **multi-agent negotiation, dynamic replanning, explicit safety constraints, and offline communication under uncertain information**. The mobile app extends this architecture to field responders, but offline storage alone does not provide connectivity. The map and mobile interface make the system's decisions understandable; they are not the core algorithm.
