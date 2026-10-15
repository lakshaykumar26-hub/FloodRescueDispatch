"use client";

import type { SimEvent } from "../types";

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
  return (
    <div className="rounded border border-slate-700 bg-slate-900 p-3">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Timeline</h2>
        <span className="text-xs text-slate-400">
          {scrubTick !== null ? <><span className="text-amber-300">scrubbing t{scrubTick}</span> · live t{tick} <button className="ml-1 underline" onClick={() => onScrub(null)}>back to live</button></> : <>tick {tick}</>}
        </span>
      </div>
      <input
        type="range"
        min={0}
        max={hi}
        value={shown}
        onChange={(e) => onScrub(Number(e.target.value) === tick ? null : Number(e.target.value))}
        className="w-full"
        aria-label="Scrub ticks"
      />
      <div className="mb-2 text-[11px] text-slate-500">Scrub to tick T to review events up to T; click an event to sync map + explanation. State restore at T is verified against GET state at replay tick.</div>
      <div className="max-h-44 overflow-y-auto text-xs">
        <ul className="space-y-0.5">
          {events.filter((e) => e.tick <= shown).slice(-80).map((e, i) => (
            <li key={i}>
              <button onClick={() => onPickEvent(e)} className="flex w-full gap-2 rounded bg-slate-950 px-2 py-0.5 text-left hover:bg-slate-800">
                <span className="w-10 shrink-0 text-slate-500">t{e.tick}</span>
                <span className="shrink-0 font-mono text-sky-300">{e.kind}</span>
                <span className="truncate text-slate-400">{JSON.stringify(e.detail).slice(0, 120)}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      {kinds.length > 0 && <div className="mt-1 text-[11px] text-slate-500">kinds: {kinds.join(", ")}</div>}
    </div>
  );
}
