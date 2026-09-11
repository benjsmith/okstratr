"""DAG of seated work — stub."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    id: str
    title: str
    depends_on: list[str] = field(default_factory=list)
    state: str = "pending"  # pending | ready | running | done | blocked


class Dag:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}

    def add(self, node_id: str, title: str, depends_on: list[str] | None = None) -> Node:
        n = Node(id=node_id, title=title, depends_on=list(depends_on or []))
        self.nodes[node_id] = n
        return n

    def ready(self) -> list[Node]:
        out: list[Node] = []
        for n in self.nodes.values():
            if n.state != "pending":
                continue
            deps_ok = all(
                self.nodes.get(d) and self.nodes[d].state == "done" for d in n.depends_on
            )
            if deps_ok:
                out.append(n)
        return out

    def summary(self) -> dict[str, Any]:
        by_state: dict[str, int] = {}
        for n in self.nodes.values():
            by_state[n.state] = by_state.get(n.state, 0) + 1
        return {"nodes": len(self.nodes), "by_state": by_state, "ready": [n.id for n in self.ready()]}


_DEFAULT = Dag()


def default_dag() -> Dag:
    return _DEFAULT


def seat_root(objective: str) -> Node:
    """Ensure a root node for the seated objective."""
    dag = default_dag()
    root_id = "root"
    if root_id not in dag.nodes:
        dag.add(root_id, objective or "(untitled)")
    else:
        dag.nodes[root_id].title = objective or dag.nodes[root_id].title
        dag.nodes[root_id].state = "ready"
    return dag.nodes[root_id]
