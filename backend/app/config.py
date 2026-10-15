"""Environment configuration for the backend (Phase 6 env setup).

Stdlib-only ``.env`` loading plus typed settings. Imports ``os`` /
``pathlib`` / ``dataclasses`` only, so ``simulation/``-adjacent code can use
it without breaking the no-FastAPI/no-DB import rule. Real environment
variables always win: ``.env`` values never override an already-set var.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]  # backend/app/config.py -> backend/
DEFAULT_DOTENV = BACKEND_DIR / ".env"

_loaded_paths: set[str] = set()


def parse_dotenv_text(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines (quotes stripped, ``#`` comments skipped)."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key.startswith("#"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        # Inline comments only when introduced by whitespace ("value # note").
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def load_dotenv(path: str | Path | None = None) -> str | None:
    """Load ``backend/.env`` (or ``path``) into ``os.environ`` via setdefault.

    Idempotent per path; missing files are a silent no-op so tests and
    containers without a ``.env`` keep working. Returns the loaded path or
    ``None``.
    """
    candidate = Path(path) if path is not None else DEFAULT_DOTENV
    key = str(candidate)
    if key in _loaded_paths:
        return key if candidate.is_file() else None
    _loaded_paths.add(key)
    if not candidate.is_file():
        return None
    try:
        values = parse_dotenv_text(candidate.read_text(encoding="utf-8"))
    except OSError:
        return None
    for env_key, env_value in values.items():
        os.environ.setdefault(env_key, env_value)
    return key


def reset_dotenv_cache() -> None:
    """Test-only: allow a ``.env`` path to be re-loaded."""
    _loaded_paths.clear()


def _as_int(raw: str | None, default: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError, AttributeError):
        return default


@dataclass(frozen=True)
class Settings:
    """Typed view over the backend environment (see ``backend/.env.example``)."""

    database_url: str = ""
    sim_seed: int = 42
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "*",
        ]
    )
    snapshot_every: int = 10


def from_env() -> Settings:
    """Build :class:`Settings` from the current environment (``.env``-aware)."""
    load_dotenv()
    raw_origins = os.environ.get("CORS_ORIGINS", "")
    origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "").strip(),
        sim_seed=_as_int(os.environ.get("SIM_SEED"), 42),
        host=os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_as_int(os.environ.get("PORT"), 8000),
        cors_origins=origins
        or [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "*",
        ],
        snapshot_every=_as_int(os.environ.get("SNAPSHOT_EVERY"), 10),
    )


__all__ = [
    "Settings",
    "from_env",
    "load_dotenv",
    "parse_dotenv_text",
    "reset_dotenv_cache",
]
