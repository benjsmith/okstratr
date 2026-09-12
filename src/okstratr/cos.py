"""Chief of staff — heuristic breakdown of desk objectives into DAG nodes."""

from __future__ import annotations

from time import time
from typing import Any

from . import blackboard, dag, roles, status

# (id, title, objective_fmt, depends_on, role)
_Step = tuple[str, str, str, list[str], str]

# Default / unspecified kind — keep the historical CoS clarify chain so
# callers that invoke break_down() without a desk stay stable.
_COS_CHAIN: list[_Step] = [
    (
        "cos-clarify",
        "Clarify success criteria",
        "Define done-when / acceptance for: {obj}",
        ["root"],
        roles.ROLE_COS,
    ),
    (
        "cos-gather",
        "Gather context",
        "Collect constraints, priors, and blockers for: {obj}",
        ["cos-clarify"],
        roles.ROLE_COS,
    ),
    (
        "cos-execute",
        "Execute core work",
        "Do the main work toward: {obj}",
        ["cos-gather"],
        roles.ROLE_COS,
    ),
    (
        "cos-verify",
        "Verify outcomes",
        "Check results against success criteria for: {obj}",
        ["cos-execute"],
        roles.ROLE_VERIFIER,
    ),
]

# work / auto — Switchbay investigator / synthesizer / verifier (not only CoS).
_SWITCHBAY: list[_Step] = [
    (
        "investigator",
        "Investigate",
        "Gather evidence and context for: {obj}",
        ["root"],
        roles.ROLE_INVESTIGATOR,
    ),
    (
        "synthesizer",
        "Synthesize",
        "Merge independent opinions into succinct claims for: {obj}",
        ["investigator"],
        roles.ROLE_SYNTHESIZER,
    ),
    (
        "verifier",
        "Verify",
        "Check outcomes against success criteria for: {obj}",
        ["synthesizer"],
        roles.ROLE_VERIFIER,
    ),
]

_CURATE: list[_Step] = [
    (
        "curate-propose",
        "Propose pages",
        "Draft curated pages to land for: {obj}",
        ["root"],
        roles.ROLE_CURATOR_PLANNER,
    ),
    (
        "curate-review",
        "Review drafts",
        "Review proposed pages before commit for: {obj}",
        ["curate-propose"],
        roles.ROLE_CURATOR_JUDGE,
    ),
    (
        "curate-commit",
        "Commit / land",
        "Land reviewed pages (okbay reviews path) for: {obj}",
        ["curate-review"],
        roles.ROLE_CURATOR_JUDGE,
    ),
]

_CODE: list[_Step] = [
    (
        "code-investigate",
        "Investigate",
        "Scope the change and gather context for: {obj}",
        ["root"],
        roles.ROLE_INVESTIGATOR,
    ),
    (
        "code-implement",
        "Implement",
        "Implement the change for: {obj}",
        ["code-investigate"],
        roles.ROLE_PLANNER,
    ),
    (
        "code-verify",
        "Verify",
        "Verify the implementation against criteria for: {obj}",
        ["code-implement"],
        roles.ROLE_VERIFIER,
    ),
]

_DECK: list[_Step] = [
    (
        "deck-outline",
        "Outline",
        "Outline the narrative / brief for: {obj}",
        ["root"],
        roles.ROLE_PLANNER,
    ),
    (
        "deck-synthesize",
        "Synthesize narrative",
        "Merge material into a succinct deck for: {obj}",
        ["deck-outline"],
        roles.ROLE_SYNTHESIZER,
    ),
    (
        "deck-verify",
        "Verify brief",
        "Check the brief against the objective for: {obj}",
        ["deck-synthesize"],
        roles.ROLE_VERIFIER,
    ),
]

KIND_TEMPLATES: dict[str, list[_Step]] = {
    "work": _SWITCHBAY,
    "auto": _SWITCHBAY,
    "curate": _CURATE,
    "code": _CODE,
    "deck": _DECK,
}


def resolve_kind(kind: str | None = None) -> str | None:
    """Explicit kind, else the active desk kind, else None (default CoS chain)."""
    if kind:
        k = kind.strip().lower()
        if k:
            return k
    try:
        from . import desks

        active = desks.default_registry().active()
        if active is not None and active.kind:
            return str(active.kind).strip().lower() or None
    except Exception:  # noqa: BLE001
        return None
    return None


def template_for(kind: str | None) -> list[_Step]:
    """Kind-specific planner template. work/auto → Switchbay roles."""
    k = resolve_kind(kind) if kind is None else (kind or "").strip().lower()
    if k in KIND_TEMPLATES:
        return KIND_TEMPLATES[k]
    return _COS_CHAIN


def advise(objective: str, blackboard_head: list[str] | None = None, *, kind: str | None = None) -> dict[str, Any]:
    """Return a CoS plan summary (no DAG mutation)."""
    obj = (objective or "").strip() or "(no objective)"
    notes = list(blackboard_head or [])
    steps = template_for(kind)
    breakdown = [
        {
            "id": nid,
            "title": title,
            "objective": obj_fmt.format(obj=obj),
            "depends_on": list(deps),
            "role": role,
        }
        for nid, title, obj_fmt, deps, role in steps
    ]
    return {
        "objective": obj,
        "kind": resolve_kind(kind) if kind is not None else resolve_kind(None),
        "priority": "normal",
        "breakdown": [b["title"] + ": " + b["objective"] for b in breakdown],
        "nodes": breakdown,
        "escalate_if": ["blocked > 30m", "needs human judgment"],
        "blackboard_context": notes[:5],
        "stub": False,
        "heuristic": True,
        "switchbay_roles": [b["role"] for b in breakdown],
    }


def next_action(objective: str, *, kind: str | None = None) -> str:
    plan = advise(objective, kind=kind)
    steps = plan.get("breakdown") or []
    return steps[0] if steps else "Start a desk"


def break_down(
    objective: str | None = None,
    *,
    kind: str | None = None,
    mark_root_done: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """
    Heuristic (no LLM) expansion of the seated objective into child DAG nodes.

    work/auto → Switchbay investigator / synthesizer / verifier.
    Other kinds keep their templates. No kind and no active desk → cos-* chain.
    Idempotent: existing template nodes are left in place (title/objective refreshed).
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

    resolved = resolve_kind(kind)
    steps = template_for(resolved)

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

    for nid, title, obj_fmt, deps, role in steps:
        child_obj = obj_fmt.format(obj=obj)
        plan_lines.append(f"{nid}: {title} [{role}]")
        if nid in g.nodes:
            n = g.nodes[nid]
            n.title = title
            n.objective = child_obj
            n.depends_on = list(deps)
            n.kind = n.kind or role
            n.role = role
            n.updated_at = time()
            updated.append(nid)
        else:
            g.add(
                nid,
                title,
                depends_on=list(deps),
                kind=role,
                role=role,
                objective=child_obj,
                state="pending",
                save=False,
            )
            created.append(nid)

    if mark_root_done and "root" in g.nodes and g.nodes["root"].state not in ("done", "failed"):
        g.mark_done("root", notes="CoS / planner breakdown complete", save=False)

    g.refresh_ready(save=False)
    if save:
        g.save()

    summary_text = (
        f"CoS plan for: {obj} (kind={resolved or 'default'})\n"
        + "\n".join(f"- {line}" for line in plan_lines)
        + f"\n(created={len(created)}, updated={len(updated)})"
    )
    note = blackboard.post(
        summary_text,
        author="cos",
        kind="decision",
        tags=["cos", "breakdown", resolved or "default"],
        provenance="okstratr.cos.break_down",
        node_id="root",
    )

    ready_ids = [n.id for n in g.ready()]
    node_ids = [nid for nid, *_ in steps]
    return {
        "ok": True,
        "objective": obj,
        "kind": resolved,
        "created": created,
        "updated": updated,
        "nodes": node_ids,
        "ready": ready_ids,
        "plan": advise(obj, kind=resolved),
        "blackboard_note_id": note.get("id"),
        "idempotent": not created and bool(updated),
    }


def should_auto_break(g: dag.Dag | None = None) -> bool:
    """True when the DAG only has root (or is empty) — start may auto-run CoS."""
    graph = g if g is not None else dag.default_dag()
    ids = set(graph.nodes.keys())
    if not ids:
        return True
    return ids == {"root"}
