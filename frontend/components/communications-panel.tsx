"use client";

import type { CommsState } from "../types";
import Pager, { PAGE_SIZE, usePager } from "./pager";

function tag(status: string): string {
  switch (status) {
    case "ACKED": return "tag tag-green";
    case "DELIVERED": return "tag tag-blue";
    case "QUEUED": return "tag tag-amber";
    case "RETRY": return "tag tag-orange";
    case "EXPIRED": return "tag tag-red";
    case "DROPPED": return "tag tag-grey";
    default: return "tag tag-grey";
  }
}

/** Truthful comms monitor: only renders what /communications + events report. Never conflates sent=delivered=acked. */
export default function CommunicationsPanel({ comms }: { comms: CommsState | null }) {
  const allMessages = comms?.messages.slice(-60) ?? [];
  const { totalPages, cur, setPage } = usePager(allMessages.length);
  const visibleMessages = allMessages.slice(cur * PAGE_SIZE, cur * PAGE_SIZE + PAGE_SIZE);
  if (!comms) return <section className="list-card"><p className="empty-state">No comms data yet.</p></section>;
  return (
    <section className="list-card">
      <div className="section-heading compact-heading">
        <div><h2>Comms monitor <small>(tick {comms.tick})</small></h2><p>Queue, delivery and reconciliation</p></div>
      </div>
      <div className="comms-grid">
        <div className="detail-card">
          <div><strong>Connected ({comms.connected.length})</strong></div>
          <div className="connection-note">{comms.connected.join(", ") || "—"}</div>
        </div>
        <div className="detail-card">
          <div><strong>Disconnected ({comms.disconnected.length})</strong></div>
          <div className="connection-note">{comms.disconnected.join(", ") || "—"}</div>
        </div>
      </div>
      <div className="connection-note">Queue length: <strong>{comms.queue.length}</strong>
        {comms.partitions.length > 0 && (
          <span className="tag tag-red">⛔ partition: {comms.partitions.map((p) => `${p.agent_id} t${p.from_tick}→${p.to_tick ?? "…"}`).join("; ")}</span>
        )}
      </div>
      <h3 className="detail-h3">Queued</h3>
      <ul className="request-list">
        {comms.queue.map((m) => (
          <li key={m.message_id} className="request-row">
            <span className={tag(m.status)}>{m.status}</span>
            <span className="row-main"><strong>{m.message_id}</strong><small>{m.type} {m.sender_id}→{m.recipient_id} t{m.created_at_tick} exp t{m.expires_at_tick}{typeof m.retries === "number" ? ` retry×${m.retries}` : ""}</small></span>
          </li>
        ))}
        {comms.queue.length === 0 && <li className="empty-state">Queue empty.</li>}
      </ul>
      <h3 className="detail-h3">Recent messages ({comms.messages.length})</h3>
      <ul className="request-list">
        {visibleMessages.map((m) => (
          <li key={m.message_id} className="request-row">
            <span className={tag(m.status)}>{m.status}</span>
            <span className="row-main"><strong>{m.message_id}</strong><small>{m.type} {m.sender_id}→{m.recipient_id} t{m.created_at_tick}</small></span>
          </li>
        ))}
        {comms.messages.length === 0 && <li className="empty-state">No messages yet.</li>}
      </ul>
      <Pager page={cur} totalPages={totalPages} onPage={setPage} />
      <h3 className="detail-h3">Reconciliation</h3>
      <ul className="request-list">
        {comms.reconciliation_log.map((r, i) => (
          <li key={i} className="request-row">
            <span className="row-main"><strong>t{r.tick} {r.agent_id}</strong><small><span className="tag tag-green">{r.status}</span> {r.detail}</small></span>
          </li>
        ))}
        {comms.reconciliation_log.length === 0 && <li className="empty-state">No reconciliations yet — heal a partition to see one here.</li>}
      </ul>
    </section>
  );
}
