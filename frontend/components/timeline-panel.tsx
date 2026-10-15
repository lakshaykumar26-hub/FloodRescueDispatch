"use client";

import type { SimEvent } from "../types";
import Pager, { PAGE_SIZE, usePager } from "./pager";

interface Props {
  events: SimEvent[];
  tick: number;
  maxTick: number;
  scrubTick: number | null;
  onScrub: (t: number | null) => void;
  onPickEvent: (e: SimEvent) => void;
}

export default function TimelinePanel({ events, tick, maxTick, scrubTick, onScrub, onPickEvent }: Props) {
  const hi = Math.max(maxTick, tick, 1);
  const shown = scrubTick ?? tick;
  const kinds = [...new Set(events.map((e) => e.kind))].sort();
  const rows = events.filter((e) => e.tick <= shown).slice(-80);
  const { totalPages, cur, setPage } = usePager(rows.length);
  const visible = rows.slice(cur * PAGE_SIZE, cur * PAGE_SIZE + PAGE_SIZE);
  return (
    <section className="list-card">
      <div className="section-heading compact-heading">
        <div><h2>Timeline</h2><p>Review events up to any tick</p></div>
        <span className="count-pill">tick {tick}</span>
      </div>
      <div className="connection-note">
        {scrubTick !== null ? <><span>scrubbing t{scrubTick}</span> · live t{tick} <button className="detail-close" onClick={() => onScrub(null)}>back to live</button></> : <>tick {tick}</>}
      </div>
      <input
        type="range"
        min={0}
        max={hi}
        value={shown}
        onChange={(e) => onScrub(Number(e.target.value) === tick ? null : Number(e.target.value))}
        className="scrub-range"
        aria-label="Scrub ticks"
      />
      <p className="connection-note">Scrub to tick T to review events up to T; click an event to sync map + explanation. State restore at T is verified against GET state at replay tick.</p>
      <ul className="request-list timeline-list">
        {visible.map((e, i) => (
          <li key={`${cur}-${i}`}>
            <button onClick={() => onPickEvent(e)} className="request-row">
              <span className="timeline-tick">t{e.tick}</span>
              <span className="row-main"><strong>{e.kind}</strong><small>{JSON.stringify(e.detail).slice(0, 120)}</small></span>
            </button>
          </li>
        ))}
      </ul>
      <Pager page={cur} totalPages={totalPages} onPage={setPage} />
      {kinds.length > 0 && <p className="connection-note">kinds: {kinds.join(", ")}</p>}
    </section>
  );
}
