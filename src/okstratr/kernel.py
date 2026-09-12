"""Kernel: hiring manager (no real LLM calls).

Chooses a default desk kind from a light objective heuristic, always ensures
a CoS, grants roles under an effort-based cap, and retires short-lived DAG
workers. Full Auto bandit / effort-slider utility is documented in
docs/DESK-KERNEL.md and not implemented here.
"""

from __future__ import annotations

import re
from time import time
from typing import Any

from . import blackboard, dag, okbay, roles

# Default kind set — not a closed enum forever; kernel may invent later.
KNOWN_KINDS = roles.DEFAULT_DESK_KINDS

_CURATE_RE = re.compile(
    r"\b(curat\w*|wiki|atlas|page|docs?\b|knowledge|catalog)\b", re.I
)
_CODE_RE = re.compile(
    r"\b(code|implement|fix|bug|pr\b|refactor|tests?|compile|git)\b", re.I
)
_DECK_RE = re.compile(
    r"\b(deck|brief|slides?|pitch|narrative|present|summar\w*)\b", re.I
)
_WORK_RE = re.compile(
    r"\b(ship|execute|do\b|work|task|ops|run)\b", re.I
)

# Standing DAG nodes that must not be retired (desk spine).
STANDING_NODE_IDS = frozenset({"root"})

# Effort slider stub: how many granted roles the desk may hold.
HIRE_CAP_LOW = 2  # CoS + planner (minimal)
HIRE_CAP_MID = 6
HIRE_CAP_HIGH = 10
EFFORT_LOW = 0.35
EFFORT_HIGH = 0.70


def choose_kind(objective: str, kind: str | None = None) -> str:
    """
    Pick a desk kind. Explicit kind wins if recognized; else heuristic on objective.
    Unknown explicit kinds are allowed (kernel may invent) but logged as custom.
    """
    if kind:
        k = kind.strip().lower()
        if k:
            return k
    obj = (objective or "").strip()
    if not obj:
        return "auto"
    if _CURATE_RE.search(obj):
        return "curate"
    if _DECK_RE.search(obj):
        return "deck"
    if _CODE_RE.search(obj):
        return "code"
    if _WORK_RE.search(obj):
        return "work"
    return "auto"


def ensure_cos(role_ids: list[str] | None) -> list[str]:
    """Always put CoS first; the only user interface for the desk."""
    ids = list(role_ids or [])
    if roles.ROLE_COS not in ids:
        ids.insert(0, roles.ROLE_COS)
    elif ids[0] != roles.ROLE_COS:
        ids = [roles.ROLE_COS] + [r for r in ids if r != roles.ROLE_COS]
    return ids


def hire_cap(effort: float | None) -> int:
    """Max granted roles for this effort. Slider stub — not a live bandit."""
    if effort is None:
        e = 0.5
    else:
        try:
            e = max(0.0, min(1.0, float(effort)))
        except (TypeError, ValueError):
            e = 0.5
    if e < EFFORT_LOW:
        return HIRE_CAP_LOW
    if e < EFFORT_HIGH:
        return HIRE_CAP_MID
    return HIRE_CAP_HIGH


def effort_slider(effort: float | None) -> dict[str, Any]:
    """Status payload for the effort slider (stub)."""
    cap = hire_cap(effort)
    return {
        "value": effort,
        "cap": cap,
        "stub": True,
        "bandit": False,
        "note": (
            "Effort trims hire cap and optional roles only. "
            "Live utility / Auto bandit is future work."
        ),
    }


def curate_commit_path_ok(desk: Any | None = None) -> bool:
    """True when a curate land/commit path is configured (okbay reviews hook)."""
    if desk is not None:
        cp = getattr(desk, "commit_path", None)
        if isinstance(desk, dict):
            cp = desk.get("commit_path")
        if isinstance(cp, dict) and cp.get("configured"):
            return True
        if isinstance(cp, str) and cp.strip():
            return True
    return bool(okbay.reviews_commit_path().get("configured"))


def _granted_entry(
    role_id: str,
    *,
    model_hint: str | None = None,
    effort: float | None = None,
) -> dict[str, Any]:
    return {
        "id": role_id,
        "model_hint": model_hint or roles.model_hint_for(role_id),
        "effort": effort,
        "granted_at": time(),
    }


def org_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Persistable desk org: CoS + granted roles with model hints and effort."""
    effort = plan.get("effort")
    hired = ensure_cos(list(plan.get("roles") or []))
    return {
        "cos": roles.ROLE_COS,
        "effort": effort,
        "cap": hire_cap(effort),
        "granted": [_granted_entry(r, effort=effort) for r in hired],
        "model_policy": plan.get("model_policy") or "strongest_available_or_user_choice",
        "stub": True,
    }


def _apply_curate_guard(hired: list[str], *, desk: Any | None = None) -> tuple[list[str], bool]:
    """Drop curator_worker unless a commit/review path is configured."""
    if roles.ROLE_CURATOR_WORKER not in hired:
        return hired, False
    if curate_commit_path_ok(desk):
        # Still require a judge so propose→review can land.
        if roles.ROLE_CURATOR_JUDGE not in hired:
            hired = list(hired) + [roles.ROLE_CURATOR_JUDGE]
        return hired, False
    filtered = [r for r in hired if r != roles.ROLE_CURATOR_WORKER]
    return filtered, True


def hire_plan(
    objective: str,
    *,
    kind: str | None = None,
    effort: float | None = None,
    desk: Any | None = None,
) -> dict[str, Any]:
    """
    Stub hiring plan: kind + roles. No LLM.

    effort ∈ [0, 1] (optional) trims to the hire cap and, when low, CoS+planner
    only. Curator workers are refused without an okbay reviews commit path.
    """
    chosen = choose_kind(objective, kind)
    hired = roles.roles_for_kind(chosen)
    hired, worker_refused = _apply_curate_guard(hired, desk=desk)

    if effort is not None and effort < EFFORT_LOW:
        hired = ensure_cos([roles.ROLE_COS, roles.ROLE_PLANNER])
    else:
        hired = ensure_cos(hired)

    cap = hire_cap(effort)
    if len(hired) > cap:
        hired = ensure_cos(hired)[:cap]

    plan = {
        "kind": chosen,
        "kind_was_default": chosen in KNOWN_KINDS,
        "objective": (objective or "").strip(),
        "roles": hired,
        "cos": roles.ROLE_COS,
        "effort": effort,
        "hire_cap": cap,
        "model_policy": "strongest_available_or_user_choice",
        "org": None,  # filled below
        "curate_worker_refused": worker_refused,
        "commit_path": okbay.reviews_commit_path(),
        "okbay_workspace": okbay.active_workspace(),
        "stub": True,
        "notes": [
            "Workers send succinct summaries only (no full reasoning traces).",
            "Short-lived workers must retire from the DAG.",
            "Curate path requires propose→review→commit land capability.",
        ],
    }
    plan["org"] = org_from_plan(plan)
    return plan


def spin_up_desk_spec(
    objective: str,
    *,
    kind: str | None = None,
    effort: float | None = None,
    desk: Any | None = None,
) -> dict[str, Any]:
    """Kernel entry: decide desk type + hires for a new or resumed objective."""
    plan = hire_plan(objective, kind=kind, effort=effort, desk=desk)
    obj = plan["objective"]
    if plan["kind"] == "auto" and obj and len(obj.split()) <= 6 and effort is None:
        if not _CODE_RE.search(obj) and not _CURATE_RE.search(obj):
            plan = dict(plan)
            plan["roles"] = ensure_cos([roles.ROLE_COS, roles.ROLE_PLANNER])
            plan["minimal"] = True
            plan["hire_cap"] = hire_cap(effort)
            plan["org"] = org_from_plan(plan)
    return plan


def route_herdr_input(
    text: str,
    *,
    desk_id: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """
    Herdr text passthrough → kernel.

    1. Targeted at an existing desk CoS pane (desk_id / thread_id) → that desk.
    2. New chat / no desk → spin up an appropriate desk (minimal for simple Qs).
    """
    from . import desks as desks_mod

    blob = (text or "").strip()
    reg = desks_mod.default_registry()
    target = None
    if desk_id:
        target = reg.desks.get(desk_id)
    if target is None and thread_id:
        for d in reg.standing():
            if d.thread_id == thread_id:
                target = d
                break
    if target is not None and target.state != "dismissed":
        return {
            "ok": True,
            "route": "existing_cos",
            "desk_id": target.id,
            "thread_id": target.thread_id,
            "kind": target.kind,
            "text": blob,
            "stub": True,
            "message": "Route to standing desk CoS (no new hire)",
        }

    # New / unmatched → kernel spins a desk. Short questions get a minimal org.
    words = len(blob.split()) if blob else 0
    effort = 0.2 if words and words <= 6 else None
    plan = spin_up_desk_spec(blob, kind="auto", effort=effort)
    return {
        "ok": True,
        "route": "new_minimal" if plan.get("minimal") or (effort is not None) else "new_desk",
        "hire": plan,
        "text": blob,
        "stub": True,
        "message": "No standing desk matched; kernel would spin up a desk",
    }


def _resolve_desk(desk: Any | None) -> tuple[Any | None, Any]:
    from . import desks as desks_mod

    reg = desks_mod.default_registry()
    if desk is None:
        return reg.active(), reg
    if isinstance(desk, str):
        return reg.desks.get(desk), reg
    if isinstance(desk, dict):
        did = desk.get("id")
        return (reg.desks.get(did) if did else None), reg
    did = getattr(desk, "id", None)
    if did and did in reg.desks:
        return reg.desks[did], reg
    return desk, reg


def _parse_hire_request(request: Any) -> dict[str, Any]:
    if isinstance(request, str):
        return {"role": request.strip(), "model_hint": None, "copies": 1}
    if not isinstance(request, dict):
        return {"role": "", "model_hint": None, "copies": 1}
    role = str(request.get("role") or request.get("id") or "").strip()
    hint = request.get("model_hint") or request.get("model")
    copies = request.get("copies") or 1
    try:
        copies = max(1, int(copies))
    except (TypeError, ValueError):
        copies = 1
    return {"role": role, "model_hint": str(hint).strip() if hint else None, "copies": copies}


def hire(desk: Any, request: Any) -> dict[str, Any]:
    """
    Grant a role on the desk org if under the effort cap and curate guards pass.

    request: role id str, or {role|id, model_hint?, copies?}
    desk: Desk, desk_id, or None (active).
    """
    d, reg = _resolve_desk(desk)
    if d is None:
        return {"ok": False, "error": "no desk to hire into"}
    req = _parse_hire_request(request)
    role = req["role"]
    if not role:
        return {"ok": False, "error": "hire request missing role"}

    org = dict(getattr(d, "org", None) or {})
    granted = [dict(x) for x in (org.get("granted") or [])]
    granted_ids = [str(x.get("id")) for x in granted]
    if not granted_ids:
        granted_ids = list(getattr(d, "roles", None) or [])
        granted = [_granted_entry(r, effort=getattr(d, "effort", None)) for r in granted_ids]
    granted_ids = ensure_cos(granted_ids)

    if role == roles.ROLE_CURATOR_WORKER and not curate_commit_path_ok(d):
        return {
            "ok": False,
            "error": "curate commit/review path not configured; refused curator_worker",
            "guard": "curate_commit_path",
            "commit_path": okbay.reviews_commit_path(),
            "hint": "Set OKSTRATR_OKBAY_REVIEWS=1 or desk.commit_path (okbay reviews hook)",
        }

    already = granted_ids.count(role)
    if already >= req["copies"] and role in granted_ids:
        return {
            "ok": True,
            "action": "already_granted",
            "role": role,
            "desk_id": d.id,
            "roles": granted_ids,
            "org": org or org_from_plan({"roles": granted_ids, "effort": getattr(d, "effort", None)}),
        }

    effort = getattr(d, "effort", None)
    if isinstance(getattr(d, "hire", None), dict) and effort is None:
        effort = d.hire.get("effort")
    cap = hire_cap(effort)
    if len(granted_ids) >= cap:
        return {
            "ok": False,
            "error": f"hire cap reached ({cap} roles at effort={effort})",
            "cap": cap,
            "effort": effort,
            "roles": granted_ids,
            "guard": "hire_cap",
        }

    granted_ids.append(role)
    granted_ids = ensure_cos(granted_ids)
    granted.append(
        _granted_entry(role, model_hint=req["model_hint"], effort=effort)
    )
    org = {
        "cos": roles.ROLE_COS,
        "effort": effort,
        "cap": cap,
        "granted": granted if granted else [_granted_entry(r, effort=effort) for r in granted_ids],
        "model_policy": "strongest_available_or_user_choice",
        "stub": True,
    }
    # Keep granted list aligned with ids
    seen = {str(x.get("id")) for x in org["granted"]}
    for rid in granted_ids:
        if rid not in seen:
            org["granted"].append(_granted_entry(rid, effort=effort))
            seen.add(rid)

    d.roles = granted_ids
    d.org = org
    d.updated_at = time()
    if hasattr(reg, "save"):
        reg.save()
    try:
        from . import status as status_mod

        status_mod.write_status()
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "action": "hire",
        "role": role,
        "model_hint": req["model_hint"] or roles.model_hint_for(role),
        "desk_id": getattr(d, "id", None),
        "roles": granted_ids,
        "org": org,
        "cap": cap,
        "effort": effort,
    }


def retire_worker(
    node_id: str,
    *,
    desk: Any | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    """
    Remove a short-lived worker node from the active DAG.

    Archives a succinct summary to the blackboard so the DAG does not grow
    without bound (Switchbay bug). Standing root is refused.
    """
    nid = (node_id or "").strip()
    if not nid:
        return {"ok": False, "error": "node_id required"}
    if nid in STANDING_NODE_IDS:
        return {"ok": False, "error": "cannot retire standing root"}

    g = dag.default_dag(force_reload=True)
    node = g.nodes.get(nid)
    if node is None:
        return {"ok": False, "error": f"unknown node: {nid}", "node_id": nid}

    text = (summary or node.notes or node.title or nid).strip()
    text = text[:500]
    note = blackboard.post(
        f"retired {nid}: {text}",
        author="kernel",
        kind="decision",
        tags=["retire", "worker", str(node.kind or node.role or "")],
        provenance="okstratr.kernel.retire_worker",
        node_id=nid,
    )
    archived = {
        "id": node.id,
        "title": node.title,
        "role": getattr(node, "role", None) or node.kind,
        "state": node.state,
        "notes": (node.notes or "")[:500],
        "summary": text,
    }
    g.remove(nid, save=True)

    d, reg = _resolve_desk(desk)
    if d is not None and hasattr(reg, "_persist_desk_dag"):
        try:
            reg._persist_desk_dag(d)
            d.updated_at = time()
            reg.save()
        except Exception:  # noqa: BLE001
            pass
    try:
        from . import status as status_mod

        status_mod.write_status()
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": True,
        "action": "retire",
        "retired": nid,
        "archived": archived,
        "blackboard_note_id": note.get("id"),
        "dag_nodes": len(g.nodes),
        "desk_id": getattr(d, "id", None) if d is not None else None,
        "message": "Short-lived worker removed from active DAG; summary on blackboard",
    }
