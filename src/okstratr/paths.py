"""Shared state directory for okstratr persistence."""

from __future__ import annotations

import os
from pathlib import Path


def state_dir() -> Path:
    """Return ~/.local/state/okstratr or OKSTRATR_STATE_DIR (for tests)."""
    raw = (os.environ.get("OKSTRATR_STATE_DIR") or "").strip()
    if raw:
        p = Path(raw).expanduser()
    else:
        p = Path.home() / ".local" / "state" / "okstratr"
    p.mkdir(parents=True, exist_ok=True)
    return p
