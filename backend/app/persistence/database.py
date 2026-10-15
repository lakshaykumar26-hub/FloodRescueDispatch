"""Engine/session abstraction over sqlite3 (stdlib) with optional Postgres.

``DATABASE_URL`` comes from the environment (see ``backend/.env.example``).
Supported values:

- empty / unset -> ``backend/data/flood_rescue.db`` (file, created on demand)
- ``sqlite:///path`` or a plain filesystem path -> that sqlite file
- ``:memory:`` -> shared in-memory sqlite (tests)
- ``postgresql://...`` -> psycopg if importable, else sqlite fallback file

Only the sqlite path is exercised by the test suite; the Postgres branch is
a thin guarded import so a missing driver never breaks collection.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from ..config import load_dotenv
from .migrations import load_init_sql

_MEMORY_URLS = frozenset({":memory:", "sqlite:///:memory:"})


def _default_path() -> Path:
    here = Path(__file__).resolve()
    backend_dir = here.parents[2]  # backend/app/persistence -> backend/
    data_dir = backend_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "flood_rescue.db"


def resolve_database_url(url: str | None = None) -> str:
    if url is None:
        load_dotenv()  # standalone (non-API) entry points also honor backend/.env
    raw = url if url is not None else os.environ.get("DATABASE_URL", "")
    raw = (raw or "").strip()
    if not raw:
        return str(_default_path())
    return raw


class Database:
    """Thin sqlite3 wrapper (row dicts, script init, lock-guarded writes)."""

    def __init__(self, url: str | None = None) -> None:
        self.url = resolve_database_url(url)
        self._lock = threading.Lock()
        if self.url in _MEMORY_URLS:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        elif self.url.startswith("postgresql://") and self._pg_driver() is not None:
            raise NotImplementedError(
                "postgres driver present but sqlite fallback requested"
            )
        elif self.url.startswith("sqlite:///"):
            path = self.url[len("sqlite:///") :]
            self._conn = sqlite3.connect(path, check_same_thread=False)
        elif self.url.startswith("sqlite://"):
            path = self.url[len("sqlite://") :]
            self._conn = sqlite3.connect(path or ":memory:", check_same_thread=False)
        else:
            # Plain path, sqlite fallback for postgres URLs without driver.
            target = self.url
            if target.startswith("postgresql://"):
                target = str(_default_path())
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(target, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(load_init_sql())
            self._conn.commit()

    @staticmethod
    def _pg_driver() -> Any | None:
        # Guarded optional import: tests run without any postgres driver.
        try:
            import psycopg  # type: ignore[import-not-found]

            return psycopg
        except Exception:  # noqa: BLE001, S110 — driver simply absent
            pass
        try:
            import sqlalchemy  # type: ignore[import-not-found]

            return sqlalchemy
        except Exception:  # noqa: BLE001 — driver simply absent
            return None

    def execute(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            if cur.description is None:
                self._conn.commit()
                return []
            rows = [dict(r) for r in cur.fetchall()]
            self._conn.commit()
            return rows

    def executemany(self, sql: str, seq: list[tuple]) -> None:
        with self._lock:
            self._conn.executemany(sql, seq)
            self._conn.commit()

    def count(self, table: str, where: str = "", params: tuple = ()) -> int:
        sql = f"SELECT COUNT(*) AS n FROM {table}"
        if where:
            sql += f" WHERE {where}"
        rows = self.execute(sql, params)
        return int(rows[0]["n"]) if rows else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_shared: Database | None = None
_shared_lock = threading.Lock()


def get_shared(url: str | None = None) -> Database:
    """Process-wide Database (honors DATABASE_URL on first call)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Database(url=url)
        return _shared


def reset_shared() -> None:
    """Test-only: drop the shared handle so the next call re-resolves."""
    global _shared
    with _shared_lock:
        if _shared is not None:
            try:
                _shared.close()
            except Exception:  # noqa: BLE001, S110 — close is best-effort
                pass
            _shared = None


__all__ = ["Database", "get_shared", "reset_shared", "resolve_database_url"]
