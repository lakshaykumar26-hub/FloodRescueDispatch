"""SQL migration loader (stdlib only)."""

from __future__ import annotations

from pathlib import Path


def load_init_sql() -> str:
    return (Path(__file__).resolve().parent / "001_init.sql").read_text(
        encoding="utf-8"
    )


__all__ = ["load_init_sql"]
