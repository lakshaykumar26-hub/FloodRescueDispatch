"use client";

import { useState } from "react";

export const PAGE_SIZE = 10;

interface PagerState {
  totalPages: number;
  /** Resolved 0-based page (latest when untouched). */
  cur: number;
  setPage: (page: number) => void;
}

/** Pagination that opens on the latest page and stays there until the user navigates. */
export function usePager(itemCount: number): PagerState {
  const totalPages = Math.max(1, Math.ceil(itemCount / PAGE_SIZE));
  const [page, setPage] = useState(-1); // -1 = latest page
  const cur = page < 0 ? totalPages - 1 : Math.min(page, totalPages - 1);
  return { totalPages, cur, setPage };
}

export default function Pager({ page, totalPages, onPage }: { page: number; totalPages: number; onPage: (page: number) => void }) {
  if (totalPages <= 1) return null;
  return (
    <div className="pager" aria-label="List pages">
      <button disabled={page <= 0} onClick={() => onPage(page - 1)} aria-label="Previous page">‹ Prev</button>
      <span>Page {page + 1} of {totalPages}</span>
      <button disabled={page >= totalPages - 1} onClick={() => onPage(page + 1)} aria-label="Next page">Next ›</button>
      {page < totalPages - 1 && <button onClick={() => onPage(-1)}>Latest</button>}
    </div>
  );
}
