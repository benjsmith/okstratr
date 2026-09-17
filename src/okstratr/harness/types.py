"""Harness registry types — model/seat request contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


HarnessId = str  # e.g. "grok", "claude", "codex"


@dataclass(frozen=True)
class ModelSpec:
    """A model allowed for a harness (pool or per-role)."""

    id: str
    label: str = ""
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass(frozen=True)
class HarnessDef:
    """Built-in harness descriptor (id ↔ Herdr --kind ↔ binaries)."""

    id: HarnessId
    herdr_kind: str
    bin_names: tuple[str, ...]
    label: str = ""
    default_models: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "herdr_kind": self.herdr_kind,
            "bin_names": list(self.bin_names),
            "label": self.label or self.id,
            "default_models": list(self.default_models),
            "notes": self.notes,
        }


@dataclass
class SeatRequest:
    """Request to seat one DAG node / worker."""

    node_id: str
    role: str = "worker"
    desk_id: str | None = None
    thread_id: str | None = None
    prefer_harness: HarnessId | None = None
    prefer_model: str | None = None
    objective: str = ""
    # Phase 2: difficulty / effort for rung selection
    effort: float | None = None
    rung: str | None = None  # trivial|normal|hard

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SeatResult:
    """Outcome of harness selection (before / after seating)."""

    ok: bool
    harness_id: HarnessId | None = None
    herdr_kind: str | None = None
    model: str | None = None
    adapter: str = "herdr"  # herdr | direct
    error: str | None = None
    dry_run: bool = False
    detail: dict[str, Any] = field(default_factory=dict)
    # Observability labels (same keys for Herdr + direct)
    labels: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
