"""Persistence package: durable runs, history, messages, snapshots, metrics.

SQLite (stdlib) is the default so tests never need a live Supabase/Postgres.
A ``postgresql://`` DATABASE_URL uses psycopg/SQLAlchemy only when such a
driver is importable; otherwise it falls back to a local sqlite file.
"""

from .database import Database, get_shared, reset_shared

__all__ = ["Database", "get_shared", "reset_shared"]
