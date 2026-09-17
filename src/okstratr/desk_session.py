"""DeskSession — single logical view of standing desks + DAG + objective + seats.

Phase 4 (ADR-001): DeskSession is the SSOT for Panel, TUI, CLI, and bar widgets
via GET /api/status and GET /api/desk_session. status.json is an optional
daemon write-through compat mirror only (not authoritative when HTTP is up).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA = "okstratr.desk_session.v1"


@dataclass
class SeatRef:
    """Pointer to a live seat (Herdr pane or direct CLI process)."""

    adapter: str  # herdr | direct
    desk_id: str | None = None
    thread_id: str | None = None
    harness_id: str | None = None
    node_id: str | None = None
    pid: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"adapter": self.adapter}
        if self.desk_id:
            d["desk_id"] = self.desk_id
        if self.thread_id:
            d["thread_id"] = self.thread_id
        if self.harness_id:
            d["harness_id"] = self.harness_id
        if self.node_id:
            d["node_id"] = self.node_id
        if self.pid is not None:
            d["pid"] = self.pid
        if self.detail:
            d["detail"] = dict(self.detail)
        return d


@dataclass
class DeskRow:
    """One standing desk row in the session view."""

    id: str
    kind: str
    state: str
    objective: str = ""
    placeholder: bool = False
    schedule: dict[str, Any] | None = None
    thread_id: str = ""
    dag_nodes: int | None = None
    seats: list[SeatRef] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "objective": self.objective,
            "placeholder": self.placeholder,
            "schedule": self.schedule,
            "thread_id": self.thread_id,
            "dag_nodes": self.dag_nodes,
            "seats": [s.to_dict() for s in self.seats],
            # Compat aliases used by older Panel/TUI bindings
            "desk_id": self.id,
        }


@dataclass
class DeskSession:
    """Canonical standing-desks + DAG + objective + seat refs view."""

    desks: list[DeskRow] = field(default_factory=list)
    focus_desk_id: str | None = None
    active_desk_id: str | None = None
    objective: str = ""
    dag: dict[str, Any] = field(default_factory=dict)
    herdr_labels: dict[str, Any] = field(default_factory=dict)
    schema: str = SCHEMA
    notes: str = (
        "P4: DeskSession is SSOT via HTTP; status.json is daemon compat mirror "
        "only (clients must not treat FileView as authoritative when HTTP is up)."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "focus_desk_id": self.focus_desk_id,
            "active_desk_id": self.active_desk_id,
            "objective": self.objective,
            "desks": [d.to_dict() for d in self.desks],
            "standing": [d.to_dict() for d in self.desks],  # TUI alias
            "dag": dict(self.dag),
            "herdr_labels": dict(self.herdr_labels),
            "notes": self.notes,
        }


def _direct_seats_by_desk() -> dict[str, list[SeatRef]]:
    out: dict[str, list[SeatRef]] = {}
    try:
        from .harness import procs

        regs = procs.load_registry()
    except Exception:  # noqa: BLE001
        return out
    for rec in regs.values():
        desk_id = getattr(rec, "desk_id", None) or None
        if not desk_id:
            continue
        key = str(desk_id)
        out.setdefault(key, []).append(
            SeatRef(
                adapter="direct",
                desk_id=key,
                thread_id=getattr(rec, "thread_id", None),
                harness_id=getattr(rec, "harness_id", None) or None,
                node_id=getattr(rec, "node_id", None) or None,
                pid=int(getattr(rec, "pid", 0) or 0) or None,
                detail={"argv": list(getattr(rec, "argv", None) or [])},
            )
        )
    return out


def build(
    *,
    registry: Any | None = None,
    dag_summary: dict[str, Any] | None = None,
    objective: str | None = None,
) -> DeskSession:
    """Assemble DeskSession from desk registry + DAG + direct proc registry."""
    from . import dag as dag_mod
    from . import desks as desks_mod
    from . import herdr
    from . import status as status_mod

    reg = registry or desks_mod.default_registry()
    standing_rows = desks_mod.default_standing_rows(reg)
    direct_map = _direct_seats_by_desk()
    focus_id = getattr(reg, "focus_id", None) or getattr(reg, "active_id", None)
    active = reg.active() if hasattr(reg, "active") else None
    active_id = getattr(reg, "active_id", None)
    obj = (objective if objective is not None else "") or ""
    if not obj:
        try:
            obj = status_mod.get_objective() or ""
        except Exception:  # noqa: BLE001
            obj = ""
    if not obj and active is not None:
        obj = str(getattr(active, "objective", "") or "")

    if dag_summary is None:
        try:
            # Prefer focused/active desk file when global is empty (same as /api/dag)
            api_dag = desks_mod.load_dag_for_api(None)
            items = list(api_dag.get("items") or api_dag.get("nodes") or [])
            if isinstance(api_dag.get("nodes"), list):
                items = list(api_dag["nodes"])
            # DeskRow.dag_nodes expects an int count
            dag_summary = {
                k: v for k, v in api_dag.items() if k not in ("nodes",)
            }
            dag_summary["nodes"] = int(api_dag.get("node_count") or len(items))
            dag_summary["items"] = items
        except Exception:  # noqa: BLE001
            try:
                g = dag_mod.default_dag()
                if hasattr(g, "refresh_ready"):
                    g.refresh_ready()
                dag_summary = g.summary() if hasattr(g, "summary") else {}
            except Exception:  # noqa: BLE001
                dag_summary = {}

    labels: dict[str, Any] = {
        "desk_id": None,
        "thread_id": None,
        "focus_desk_id": focus_id,
        "format": getattr(herdr, "AGENT_ID_FORMAT", None)
        or getattr(herdr, "LABEL_FORMAT", "desk={desk_id};thread={thread_id}"),
    }
    if active is not None:
        try:
            labels = herdr.labels_for_desk(active)
            labels["focus_desk_id"] = focus_id
        except Exception:  # noqa: BLE001
            labels["desk_id"] = getattr(active, "id", None)
            labels["thread_id"] = getattr(active, "thread_id", None)

    desks_out: list[DeskRow] = []
    for row in standing_rows:
        if not isinstance(row, dict):
            continue
        desk_id = str(row.get("id") or "")
        thread_id = str(row.get("thread_id") or "")
        # Live desk may carry thread_id even when standing row is slim
        live = None
        try:
            if desk_id and hasattr(reg, "desks"):
                live = reg.desks.get(desk_id)
        except Exception:  # noqa: BLE001
            live = None
        if live is not None and not thread_id:
            thread_id = str(getattr(live, "thread_id", "") or "")

        seats: list[SeatRef] = []
        if desk_id and not row.get("placeholder"):
            seats.append(
                SeatRef(
                    adapter="herdr",
                    desk_id=desk_id,
                    thread_id=thread_id or None,
                    detail={"labels": {"desk_id": desk_id, "thread_id": thread_id}},
                )
            )
            seats.extend(direct_map.get(desk_id, []))

        desks_out.append(
            DeskRow(
                id=desk_id,
                kind=str(row.get("kind") or ""),
                state=str(row.get("state") or ""),
                objective=str(row.get("objective") or ""),
                placeholder=bool(row.get("placeholder")),
                schedule=row.get("schedule") if isinstance(row.get("schedule"), dict) else None,
                thread_id=thread_id,
                dag_nodes=(dag_summary or {}).get("nodes") if desk_id == active_id else None,
                seats=seats,
            )
        )

    return DeskSession(
        desks=desks_out,
        focus_desk_id=focus_id,
        active_desk_id=active_id,
        objective=obj,
        dag=dict(dag_summary or {}),
        herdr_labels=labels,
    )


def snapshot(**kwargs: Any) -> dict[str, Any]:
    """Dict form for embedding in /api/status and status.json."""
    return build(**kwargs).to_dict()
