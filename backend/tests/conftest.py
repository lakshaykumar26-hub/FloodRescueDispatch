"""Ensure repo root is on sys.path so tests can `from backend.app... import ...`.

Allows `pytest backend/tests -q` from the repo root without an install,
and keeps a single module identity with `python -m backend.app...` runs.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
