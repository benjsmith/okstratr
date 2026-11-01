"""Hard limits for one orchestration run.

The effort slider and the learner may ask for less than these, never more.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

MAX_NODES = 24
MAX_DEPTH = 8
MAX_CONCURRENCY = 8
MAX_EXPANSIONS = 3
WORKER_TIMEOUT_SEC = 900.0
WALL_CLOCK_SEC = 3600.0


def _int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass
class Bounds:
    max_nodes: int = MAX_NODES
    max_depth: int = MAX_DEPTH
    max_concurrency: int = MAX_CONCURRENCY
    max_expansions: int = MAX_EXPANSIONS
    worker_timeout_sec: float = WORKER_TIMEOUT_SEC
    wall_clock_sec: float = WALL_CLOCK_SEC

    def clamp(self) -> Bounds:
        """Return a copy that never exceeds the hard limits."""
        return Bounds(
            max_nodes=max(1, min(_int(self.max_nodes, MAX_NODES), MAX_NODES)),
            max_depth=max(1, min(_int(self.max_depth, MAX_DEPTH), MAX_DEPTH)),
            max_concurrency=max(
                1, min(_int(self.max_concurrency, MAX_CONCURRENCY), MAX_CONCURRENCY)
            ),
            max_expansions=max(
                0, min(_int(self.max_expansions, MAX_EXPANSIONS), MAX_EXPANSIONS)
            ),
            worker_timeout_sec=max(
                1.0,
                min(_float(self.worker_timeout_sec, WORKER_TIMEOUT_SEC), WORKER_TIMEOUT_SEC),
            ),
            wall_clock_sec=max(
                1.0, min(_float(self.wall_clock_sec, WALL_CLOCK_SEC), WALL_CLOCK_SEC)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> Bounds:
        if not isinstance(raw, dict):
            return cls().clamp()
        kw = {k: raw[k] for k in cls.__dataclass_fields__ if k in raw}
        return cls(**kw).clamp()
