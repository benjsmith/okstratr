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
    role: str | None = None
    """Hired role that owns this node (investigator, verifier, …)."""

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
            role=str(data["role"]) if data.get("role") else None,
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
        role: str | None = None,
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
            role=role,
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
        self._bandit_outcome("done", node_id)
        return n

    def mark_failed(self, node_id: str, *, notes: str | None = None, save: bool = True) -> Node:
        n = self.set_state(node_id, "failed", save=False)
        if notes is not None:
            n.notes = notes
            n.updated_at = time()
        if save:
            self.save()
        reason = "timeout" if notes and "timeout" in str(notes).lower() else "failed"
        self._bandit_outcome(reason, node_id)
        return n

    def _bandit_outcome(self, outcome: str, node_id: str) -> None:
        """Best-effort bandit reward on node done/fail (no raise)."""
        if node_id in ("root",):
            return
        try:
            from . import kernel

            kernel.notify_outcome(outcome, node_id=node_id)
        except Exception:  # noqa: BLE001
            pass

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

    def graph_view(self) -> dict[str, Any]:
        """Layout-friendly DAG for the Agent Space canvas.

        Always includes virtual Chief of Staff + Blackboard nodes so the panel
        shows a Switchbay-like frame even when the desk is idle / empty.
        """
        # Role → row tier (0=CoS, 1=workers, 2=blackboard, 3=verify/synth)
        tier_for_role = {
            "cos": 0,
            "root": 0,
            "planner": 1,
            "investigator": 1,
            "researcher": 1,
            "curator_planner": 1,
            "curator_worker": 1,
            "curator_judge": 1,
            "blackboard": 2,
            "verifier": 3,
            "synthesizer": 3,
        }

        real_items = [
            n for n in self.nodes.values()
            if n.id != "root" and (n.kind or "") != "root"
        ]
        idle = len(real_items) == 0

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        seen: set[str] = set()

        def add_node(
            nid: str,
            *,
            label: str,
            role: str,
            kind: str | None = None,
            state: str = "ready",
            virtual: bool = False,
            title: str = "",
        ) -> None:
            if nid in seen:
                return
            seen.add(nid)
            r = role or "worker"
            nodes.append(
                {
                    "id": nid,
                    "label": label,
                    "title": title or label,
                    "role": r,
                    "kind": kind or r,
                    "state": state,
                    "tier": tier_for_role.get(r, 1),
                    "virtual": virtual,
                }
            )

        # Always: Chief of Staff (top) + Blackboard
        cos_state = "ready"
        root = self.nodes.get("root")
        if root is not None:
            cos_state = root.state
        # Prefer an explicit cos-role node if present
        for n in self.nodes.values():
            if (n.role or n.kind) == "cos" and n.id != "root":
                cos_state = n.state
                break
        add_node(
            "cos",
            label="chief of staff",
            role="cos",
            kind="cos",
            state=cos_state,
            virtual=True,
            title="Chief of Staff",
        )
        add_node(
            "blackboard",
            label="blackboard",
            role="blackboard",
            kind="blackboard",
            state="ready",
            virtual=True,
            title="Blackboard",
        )

        # Real worker / verify / synth nodes
        id_map: dict[str, str] = {"root": "cos"}  # root edges attach to CoS
        for n in real_items:
            role = (n.role or n.kind or "worker").lower()
            if role == "root":
                continue
            # Collapse dedicated CoS-role nodes into the virtual CoS
            # (keep cos-verify etc. when role is verifier/synthesizer)
            if role == "cos":
                id_map[n.id] = "cos"
                continue
            gid = n.id
            id_map[n.id] = gid
            short = n.id
            if len(short) > 18:
                short = short[:16] + "…"
            add_node(
                gid,
                label=short,
                role=role,
                kind=n.kind,
                state=n.state,
                virtual=False,
                title=n.title or n.id,
            )

        # Edges from depends_on, remapped through id_map; plus CoS→workers→BB
        worker_ids = [
            nd["id"] for nd in nodes
            if nd["id"] not in ("cos", "blackboard") and nd.get("tier") == 1
        ]
        terminal_ids = [
            nd["id"] for nd in nodes
            if nd["id"] not in ("cos", "blackboard") and nd.get("tier") == 3
        ]
        edge_seen: set[tuple[str, str]] = set()

        def add_edge(a: str, b: str) -> None:
            if a == b or a not in seen or b not in seen:
                return
            key = (a, b)
            if key in edge_seen:
                return
            edge_seen.add(key)
            edges.append({"from": a, "to": b})

        if idle:
            add_edge("cos", "blackboard")
        else:
            for n in real_items:
                src = id_map.get(n.id)
                if not src or src == "cos" and (n.role or n.kind) == "cos":
                    # still process deps for cos-chain nodes collapsed into cos
                    pass
                deps = n.depends_on or []
                if not deps and src and src != "cos":
                    add_edge("cos", src)
                for d in deps:
                    a = id_map.get(d, d if d in seen else None)
                    if a is None and d == "root":
                        a = "cos"
                    b = id_map.get(n.id)
                    if a and b:
                        add_edge(a, b)

            # Fan workers into blackboard; blackboard into terminals when present
            for wid in worker_ids:
                add_edge(wid, "blackboard")
            if terminal_ids:
                add_edge("cos", "blackboard")  # soft spine
                for tid in terminal_ids:
                    add_edge("blackboard", tid)
            elif worker_ids:
                pass  # workers already → blackboard
            else:
                # Only cos-chain / unusual nodes — still show CoS → BB
                add_edge("cos", "blackboard")

            # Ensure every non-cos/bb node has at least one edge from CoS if orphan
            pointed = {e["to"] for e in edges}
            for nd in nodes:
                if nd["id"] in ("cos", "blackboard"):
                    continue
                if nd["id"] not in pointed:
                    add_edge("cos", nd["id"])

        # Stable order: by tier then id
        nodes.sort(key=lambda nd: (nd.get("tier", 1), nd["id"]))
        return {
            "nodes": nodes,
            "edges": edges,
            "idle": idle,
            "label": "AGENT SPACE",
        }

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
            "graph": self.graph_view(),
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
