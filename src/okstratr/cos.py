"""Chief of staff — heuristic breakdown of seated objectives into DAG nodes."""

from __future__ import annotations

from time import time
from typing import Any

from . import blackboard, dag, status

# Stable child template: (id_suffix, title, objective_fmt, depends_on)
_BREAKDOWN_STEPS: list[tuple[str, str, str, list[str]]] = [
    (
        "clarify",
        "Clarify success criteria",
        "Define done-when / acceptance for: {obj}",
        ["root"],
    ),
    (
        "gather",
        "Gather context",
        "Collect constraints, priors, and blockers for: {obj}",
        ["cos-clarify"],
    ),
    (
        "execute",
        "Execute core work",
        "Do the main work toward: {obj}",
        ["cos-gather"],
    ),
    (
        "verify",
        "Verify outcomes",
        "Check results against success criteria for: {obj}",
        ["cos-execute"],
    ),
]


def advise(objective: str, blackboard_head: list[str] | None = None) -> dict[str, Any]:
    """Return a CoS plan summary (no DAG mutation)."""
    obj = (objective or "").strip() or "(no objective)"
    notes = list(blackboard_head or [])
    breakdown = [
        {
            "id": f"cos-{sid}",
            "title": title,
            "objective": obj_fmt.format(obj=obj),
            "depends_on": list(deps),
        }
        for sid, title, obj_fmt, deps in _BREAKDOWN_STEPS
    ]
    return {
        "objective": obj,
        "priority": "normal",
        "breakdown": [b["title"] + ": " + b["objective"] for b in breakdown],
        "nodes": breakdown,
        "escalate_if": ["blocked > 30m", "needs human judgment"],
        "blackboard_context": notes[:5],
        "stub": False,
        "heuristic": True,
    }


def next_action(objective: str) -> str:
    plan = advise(objective)
    steps = plan.get("breakdown") or []
    return steps[0] if steps else "Seat an objective"


def break_down(
    objective: str | None = None,
    *,
    mark_root_done: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """
    Heuristic (no LLM) expansion of the seated objective into child DAG nodes.

    Stable ids: cos-clarify, cos-gather, cos-execute, cos-verify.
    Idempotent: existing cos-* nodes are left in place (title/objective refreshed).
    Posts a blackboard note summarizing the plan.
    """
    g = dag.default_dag()
    obj = (objective or "").strip()
    if not obj:
        root = g.nodes.get("root")
        if root is not None:
            obj = (root.objective or root.title or "").strip()
        if not obj:
            obj = status.get_objective()
    if not obj:
        obj = "(no objective)"

    # Ensure root exists
    if "root" not in g.nodes:
        g.seat_root(obj, save=False)
    else:
        root = g.nodes["root"]
        if not (root.objective or "").strip():
            root.objective = obj
        if not (root.title or "").strip() or root.title == "(untitled)":
            root.title = obj

    created: list[str] = []
    updated: list[str] = []
    plan_lines: list[str] = []

    for sid, title, obj_fmt, deps in _BREAKDOWN_STEPS:
        node_id = f"cos-{sid}"
        child_obj = obj_fmt.format(obj=obj)
        plan_lines.append(f"{node_id}: {title}")
        if node_id in g.nodes:
            n = g.nodes[node_id]
            n.title = title
            n.objective = child_obj
            n.depends_on = list(deps)
            n.kind = n.kind or "cos"
            n.updated_at = time()
            updated.append(node_id)
        else:
            g.add(
                node_id,
                title,
                depends_on=list(deps),
                kind="cos",
                objective=child_obj,
                state="pending",
                save=False,
            )
            created.append(node_id)

    if mark_root_done and "root" in g.nodes and g.nodes["root"].state not in ("done", "failed"):
        # Planning complete — unblock first cos-* children
        g.mark_done("root", notes="CoS breakdown complete", save=False)

    g.refresh_ready(save=False)
    if save:
        g.save()

    summary_text = (
        f"CoS plan for: {obj}\n"
        + "\n".join(f"- {line}" for line in plan_lines)
        + f"\n(created={len(created)}, updated={len(updated)})"
    )
    note = blackboard.post(
        summary_text,
        author="cos",
        kind="decision",
        tags=["cos", "breakdown"],
        provenance="okstratr.cos.break_down",
        node_id="root",
    )

    ready_ids = [n.id for n in g.ready()]
    return {
        "ok": True,
        "objective": obj,
        "created": created,
        "updated": updated,
        "nodes": [f"cos-{sid}" for sid, *_ in _BREAKDOWN_STEPS],
        "ready": ready_ids,
        "plan": advise(obj),
        "blackboard_note_id": note.get("id"),
        "idempotent": not created and bool(updated),
    }


def should_auto_break(g: dag.Dag | None = None) -> bool:
    """True when the DAG only has root (or is empty) — seat may auto-run CoS."""
    graph = g if g is not None else dag.default_dag()
    ids = set(graph.nodes.keys())
    if not ids:
        return True
    return ids == {"root"}
