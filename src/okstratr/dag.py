"""Persistent DAG of seated work under ~/.local/state/okstratr/dag.json."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import time
from typing import Any

from .paths import state_dir

VALID_STATES = frozenset({"pending", "ready", "running", "done", "blocked", "failed"})


@dataclass
class Node:
    id: str
    title: str
    depends_on: list[str] = field(default_factory=list)
    state: str = "pending"  # pending|ready|running|done|blocked|failed
    kind: str | None = None
    objective: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Node:
        now = time()
        state = str(data.get("state") or "pending")
        if state not in VALID_STATES:
            state = "pending"
        kind = data.get("kind")
        return cls(
            id=str(data["id"]),
            title=str(data.get("title") or data["id"]),
            depends_on=[str(x) for x in (data.get("depends_on") or [])],
            state=state,
            kind=str(kind) if kind is not None else None,
            objective=str(data.get("objective") or ""),
            created_at=float(data.get("created_at") or now),
            updated_at=float(data.get("updated_at") or now),
            notes=str(data.get("notes") or ""),
        )


class CycleError(ValueError):
    """Raised when the DAG contains a cycle."""


class Dag:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else state_dir() / "dag.json"
        self.nodes: dict[str, Node] = {}

    # --- persistence ---

    def load(self) -> Dag:
        self.nodes = {}
        if not self.path.is_file():
            return self
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self
        if isinstance(raw, dict) and "nodes" in raw:
            items = raw.get("nodes") or []
        elif isinstance(raw, list):
            items = raw
        else:
            items = []
        for item in items:
            if not isinstance(item, dict) or "id" not in item:
                continue
            n = Node.from_dict(item)
            self.nodes[n.id] = n
        self.refresh_ready(save=False)
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": time(),
            "nodes": [n.to_dict() for n in self.nodes.values()],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    @classmethod
    def open(cls, path: Path | None = None) -> Dag:
        return cls(path=path).load()

    # --- mutations ---

    def add(
        self,
        node_id: str,
        title: str,
        depends_on: list[str] | None = None,
        *,
        kind: str | None = None,
        objective: str = "",
        state: str | None = None,
        notes: str = "",
        save: bool = True,
    ) -> Node:
        now = time()
        deps = list(depends_on or [])
        initial = state if state in VALID_STATES else "pending"
        n = Node(
            id=node_id,
            title=title,
            depends_on=deps,
            state=initial,
            kind=kind,
            objective=objective or "",
            created_at=now,
            updated_at=now,
            notes=notes or "",
        )
        self.nodes[node_id] = n
        self.refresh_ready(save=False)
        if save:
            self.save()
        return self.nodes[node_id]

    def remove(self, node_id: str, *, save: bool = True) -> bool:
        if node_id not in self.nodes:
            return False
        del self.nodes[node_id]
        # Drop dangling deps references from other nodes
        for n in self.nodes.values():
            if node_id in n.depends_on:
                n.depends_on = [d for d in n.depends_on if d != node_id]
                n.updated_at = time()
        self.refresh_ready(save=False)
        if save:
            self.save()
        return True

    def set_state(self, node_id: str, state: str, *, save: bool = True) -> Node:
        if state not in VALID_STATES:
            raise ValueError(f"invalid state: {state!r}; expected one of {sorted(VALID_STATES)}")
        n = self.nodes.get(node_id)
        if n is None:
            raise KeyError(f"unknown node: {node_id}")
        n.state = state
        n.updated_at = time()
        self.refresh_ready(save=False)
        if save:
            self.save()
        return n

    def mark_done(self, node_id: str, *, notes: str | None = None, save: bool = True) -> Node:
        n = self.set_state(node_id, "done", save=False)
        if notes is not None:
            n.notes = notes
            n.updated_at = time()
        self.refresh_ready(save=False)
        if save:
            self.save()
        return n

    def mark_failed(self, node_id: str, *, notes: str | None = None, save: bool = True) -> Node:
        n = self.set_state(node_id, "failed", save=False)
        if notes is not None:
            n.notes = notes
            n.updated_at = time()
        if save:
            self.save()
        return n

    def reset(self, *, save: bool = True) -> None:
        """Clear all nodes."""
        self.nodes.clear()
        if save:
            self.save()

    # --- ready / blocked / topo ---

    def _deps_done(self, n: Node) -> bool:
        return all(
            (d in self.nodes and self.nodes[d].state == "done") for d in n.depends_on
        )

    def refresh_ready(self, *, save: bool = True) -> list[Node]:
        """Promote pending → ready when all deps are done; demote ready → pending if not."""
        changed = False
        for n in self.nodes.values():
            if n.state in ("done", "failed", "running", "blocked"):
                continue
            deps_ok = self._deps_done(n)
            if deps_ok and n.state == "pending":
                n.state = "ready"
                n.updated_at = time()
                changed = True
            elif (not deps_ok) and n.state == "ready":
                n.state = "pending"
                n.updated_at = time()
                changed = True
        if changed and save:
            self.save()
        return self.ready()

    def ready(self) -> list[Node]:
        out = [n for n in self.nodes.values() if n.state == "ready"]
        # Also treat pending-with-deps-done as ready for callers that skip refresh
        for n in self.nodes.values():
            if n.state == "pending" and self._deps_done(n):
                out.append(n)
        # de-dupe by id preserving order
        seen: set[str] = set()
        uniq: list[Node] = []
        for n in out:
            if n.id not in seen:
                seen.add(n.id)
                uniq.append(n)
        return uniq

    def blocked_reasons(self, node_id: str | None = None) -> dict[str, list[str]]:
        """Map node_id → list of unmet dependency ids (or missing deps)."""
        targets = (
            [self.nodes[node_id]]
            if node_id is not None
            else list(self.nodes.values())
        )
        out: dict[str, list[str]] = {}
        for n in targets:
            if n.state in ("done", "ready") and self._deps_done(n):
                continue
            reasons: list[str] = []
            for d in n.depends_on:
                dep = self.nodes.get(d)
                if dep is None:
                    reasons.append(f"missing:{d}")
                elif dep.state == "failed":
                    reasons.append(f"failed:{d}")
                elif dep.state == "blocked":
                    reasons.append(f"blocked:{d}")
                elif dep.state != "done":
                    reasons.append(f"{dep.state}:{d}")
            if n.state == "blocked" and not reasons:
                reasons.append("marked_blocked")
            if reasons or n.state in ("blocked", "pending", "failed"):
                out[n.id] = reasons
        return out

    def topo_order(self) -> list[str]:
        """Return node ids in topological order; raise CycleError on cycles."""
        indeg: dict[str, int] = {nid: 0 for nid in self.nodes}
        children: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for n in self.nodes.values():
            for d in n.depends_on:
                if d not in self.nodes:
                    continue
                children[d].append(n.id)
                indeg[n.id] = indeg.get(n.id, 0) + 1
        queue = sorted([nid for nid, deg in indeg.items() if deg == 0])
        order: list[str] = []
        while queue:
            # stable: pop smallest id for determinism
            nid = queue.pop(0)
            order.append(nid)
            for c in sorted(children.get(nid, [])):
                indeg[c] -= 1
                if indeg[c] == 0:
                    queue.append(c)
                    queue.sort()
        if len(order) != len(self.nodes):
            leftover = sorted(set(self.nodes) - set(order))
            raise CycleError(f"cycle detected involving: {', '.join(leftover)}")
        return order

    def summary(self) -> dict[str, Any]:
        by_state: dict[str, int] = {}
        for n in self.nodes.values():
            by_state[n.state] = by_state.get(n.state, 0) + 1
        try:
            order = self.topo_order()
            cycle = None
        except CycleError as e:
            order = []
            cycle = str(e)
        return {
            "nodes": len(self.nodes),
            "by_state": by_state,
            "ready": [n.id for n in self.ready()],
            "topo_order": order,
            "cycle": cycle,
            "blocked_reasons": self.blocked_reasons(),
            "items": [n.to_dict() for n in self.nodes.values()],
        }

    def seat_root(self, objective: str, *, reset: bool = False, save: bool = True) -> Node:
        """
        Create/update the root node for a seated objective.

        Without reset: update root title/objective; do not wipe the DAG.
        With reset: clear all nodes, then create a fresh root.
        """
        obj = (objective or "").strip()
        if reset:
            self.nodes.clear()
        root_id = "root"
        now = time()
        if root_id not in self.nodes:
            self.add(
                root_id,
                obj or "(untitled)",
                depends_on=[],
                kind="root",
                objective=obj,
                state="ready",
                save=False,
            )
        else:
            root = self.nodes[root_id]
            if obj:
                root.title = obj
                root.objective = obj
            root.kind = root.kind or "root"
            if root.state in ("pending", "done", "failed"):
                root.state = "ready"
            root.updated_at = now
        self.refresh_ready(save=False)
        if save:
            self.save()
        return self.nodes[root_id]


_DEFAULT: Dag | None = None
_DEFAULT_PATH: Path | None = None


def default_dag(*, force_reload: bool = False) -> Dag:
    global _DEFAULT, _DEFAULT_PATH
    path = state_dir() / "dag.json"
    if _DEFAULT is None or force_reload or _DEFAULT_PATH != path:
        _DEFAULT = Dag.open(path)
        _DEFAULT_PATH = path
    return _DEFAULT


def seat_root(objective: str, *, reset: bool = False) -> Node:
    """Ensure a root node for the seated objective (persisted)."""
    return default_dag().seat_root(objective, reset=reset)
