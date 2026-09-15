"""Kernel: hiring manager (no real LLM calls).

Uses an explicit desk kind (or the neutral ``auto`` default), always ensures
a CoS, grants roles under an effort-bandit utility + hard cap, and retires
short-lived DAG workers. Live Auto bandit / effort-slider utility is in
okstratr.bandit and documented in docs/DESK-KERNEL.md.
"""

from __future__ import annotations

import re
from time import time
from typing import Any

from . import bandit, blackboard, dag, okbay, roles

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

# Effort thresholds / caps (hard ceiling; bandit selects within).
HIRE_CAP_LOW = 2  # CoS + planner (minimal)
HIRE_CAP_MID = 6
HIRE_CAP_HIGH = 10
EFFORT_LOW = 0.35
EFFORT_HIGH = 0.70


def choose_kind(objective: str, kind: str | None = None) -> str:
    """Use the explicit kind, otherwise the neutral ``auto`` desk.

    Classifying objective text and suggesting/selecting a desk kind is product
    improvement #1 and is deliberately not shipped in this slice.
    Unknown explicit kinds remain allowed (kinds are not a forever-closed enum).
    """
    del objective  # intentionally not classified
    if kind:
        k = kind.strip().lower()
        if k:
            return k
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
    """Max granted roles for this effort (hard ceiling; bandit selects within)."""
    return bandit.hire_cap(effort)


def effort_slider(effort: float | None, *, desk_id: str | None = None) -> dict[str, Any]:
    """Status payload for the effort slider (live bandit)."""
    snap = bandit.snapshot(effort, desk_id=desk_id)
    snap["value"] = None if effort is None else bandit.clamp_effort(effort)
    snap["cap"] = hire_cap(effort)
    snap["stub"] = False
    snap["bandit"] = True
    snap["note"] = (
        "Effort maps to utility weights (quality vs cost/latency). "
        "Bandit selects hire policy arms; marginal utility must beat effort-scaled cost."
    )
    return snap


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
    diversity = bool((plan.get("bandit_decision") or {}).get("diversity"))
    granted = []
    seen_hints: dict[str, set[str]] = {}
    diversify = ["diverse", "strongest_available", "alt_diverse", "alt_strong"]
    for r in hired:
        hint = roles.model_hint_for(r)
        if diversity and r in seen_hints:
            used = seen_hints[r]
            hint = next((m for m in diversify if m not in used), "diverse")
        elif diversity and hint == "strongest_available" and r not in (
            roles.ROLE_COS,
            roles.ROLE_PLANNER,
            roles.ROLE_CURATOR_JUDGE,
        ):
            hint = "diverse"
        granted.append(_granted_entry(r, model_hint=hint, effort=effort))
        seen_hints.setdefault(r, set()).add(hint)
    return {
        "cos": roles.ROLE_COS,
        "effort": effort,
        "cap": hire_cap(effort),
        "granted": granted,
        "model_policy": plan.get("model_policy") or "strongest_available_or_user_choice",
        "stub": False,
        "bandit": True,
        "bandit_arm": (plan.get("bandit_decision") or {}).get("arm_id"),
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


def _desk_id_of(desk: Any | None) -> str | None:
    if desk is None:
        return None
    if isinstance(desk, str):
        return desk
    if isinstance(desk, dict):
        did = desk.get("id")
        return str(did) if did else None
    did = getattr(desk, "id", None)
    return str(did) if did else None


def hire_plan(
    objective: str,
    *,
    kind: str | None = None,
    effort: float | None = None,
    desk: Any | None = None,
) -> dict[str, Any]:
    """
    Bandit hiring plan: kind + roles. No LLM.

    effort ∈ [0, 1] maps to utility weights; bandit selects a hire-policy arm
    under hire_cap; marginal utility filters roles. Always CoS first.
    Curator workers are refused without an okbay reviews commit path.
    """
    chosen = choose_kind(objective, kind)
    desk_id = _desk_id_of(desk)
    decision = bandit.select_arm(effort, desk_id=desk_id)
    base = roles.roles_for_kind(chosen)
    hired = bandit.roles_for_arm(chosen, decision, base_roles=base)
    hired, audits = bandit.filter_by_marginal_utility(
        hired, effort, diversity=bool(decision.get("diversity"))
    )
    hired, worker_refused = _apply_curate_guard(hired, desk=desk)
    hired = ensure_cos(hired)

    # Low effort: force minimal when bandit/cap already tight
    if effort is not None and effort < EFFORT_LOW:
        hired = ensure_cos([roles.ROLE_COS, roles.ROLE_PLANNER])

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
        "stub": False,
        "bandit": True,
        "bandit_decision": decision,
        "marginal_audits": audits,
        "notes": [
            "Workers send succinct summaries only (no full reasoning traces).",
            "Short-lived workers must retire from the DAG.",
            "Curate path requires propose→review→commit land capability.",
            "Hire gated by effort-bandit marginal utility + hard cap.",
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
            "stub": False,
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
        "stub": False,
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


def set_effort(desk: Any, value: float) -> dict[str, Any]:
    """Set desk effort slider ∈ [0,1]; refresh org cap / bandit snapshot."""
    d, reg = _resolve_desk(desk)
    if d is None:
        return {"ok": False, "error": "no desk for effort"}
    try:
        e = max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return {"ok": False, "error": f"effort must be float in [0,1], got {value!r}"}
    d.effort = e
    org = dict(getattr(d, "org", None) or {})
    org["effort"] = e
    org["cap"] = hire_cap(e)
    org["stub"] = False
    org["bandit"] = True
    d.org = org
    if isinstance(getattr(d, "hire", None), dict):
        d.hire = dict(d.hire)
        d.hire["effort"] = e
        d.hire["hire_cap"] = hire_cap(e)
    d.updated_at = time()
    if hasattr(reg, "save"):
        reg.save()
    try:
        from . import status as status_mod

        status_mod.write_status()
    except Exception:  # noqa: BLE001
        pass
    slider = effort_slider(e, desk_id=getattr(d, "id", None))
    return {
        "ok": True,
        "action": "effort",
        "desk_id": getattr(d, "id", None),
        "effort": e,
        "cap": hire_cap(e),
        "effort_slider": slider,
        "org": d.org,
    }


def hire(desk: Any, request: Any) -> dict[str, Any]:
    """
    Grant a role on the desk org if under the effort cap, marginal utility,
    and curate guards pass.

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
    granted_hints = [str(x.get("model_hint") or "") for x in granted]

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

    hint = req["model_hint"]
    if hint is None and already >= 1:
        # Prefer different model when multiples
        used = {h for g, h in zip(granted_ids, granted_hints) if g == role}
        for cand in ("diverse", "alt_diverse", "strongest_available", "alt_strong"):
            if cand not in used:
                hint = cand
                break
        hint = hint or "diverse"
    hint = hint or roles.model_hint_for(role)

    mu = bandit.marginal_utility(
        role, granted_ids, effort, model_hint=hint, granted_hints=granted_hints
    )
    if not mu["accept"] and role != roles.ROLE_COS:
        return {
            "ok": False,
            "error": (
                f"marginal utility ΔU={mu['delta_u']:.4f} ≤ 0 "
                f"(I={mu['I_marginal']:.3f}, c={mu['c_scaled']:.3f}) at effort={effort}"
            ),
            "guard": "marginal_utility",
            "marginal": mu,
            "effort": effort,
            "cap": cap,
            "roles": granted_ids,
            "effort_slider": effort_slider(effort, desk_id=getattr(d, "id", None)),
        }

    granted_ids.append(role)
    granted_ids = ensure_cos(granted_ids)
    granted.append(_granted_entry(role, model_hint=hint, effort=effort))
    org = {
        "cos": roles.ROLE_COS,
        "effort": effort,
        "cap": cap,
        "granted": granted if granted else [_granted_entry(r, effort=effort) for r in granted_ids],
        "model_policy": "strongest_available_or_user_choice",
        "stub": False,
        "bandit": True,
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
        "model_hint": hint,
        "desk_id": getattr(d, "id", None),
        "roles": granted_ids,
        "org": org,
        "cap": cap,
        "effort": effort,
        "marginal": mu,
        "bandit": True,
    }


def notify_outcome(
    outcome: str,
    *,
    desk: Any | None = None,
    node_id: str | None = None,
    had_claim: bool | None = None,
) -> dict[str, Any]:
    """
    Update bandit arms from node/worker outcomes.

    outcome: done | failed | timeout | retired_without_claim | retired
    """
    d, _reg = _resolve_desk(desk)
    desk_id = getattr(d, "id", None) if d is not None else _desk_id_of(desk)
    oc = (outcome or "").strip().lower()
    if oc == "done":
        reward = bandit.REWARD_DONE
    elif oc in ("failed", "fail", "timeout"):
        reward = bandit.REWARD_FAILED if oc != "timeout" else bandit.REWARD_TIMEOUT
    elif oc in ("retired_without_claim", "retired_no_claim"):
        reward = bandit.REWARD_RETIRED_NO_CLAIM
    elif oc == "retired":
        reward = bandit.REWARD_DONE if had_claim else bandit.REWARD_RETIRED_NO_CLAIM
    else:
        return {"ok": False, "error": f"unknown outcome: {outcome!r}"}
    arm_id = None
    if d is not None:
        hire = getattr(d, "hire", None) or {}
        if isinstance(hire, dict):
            arm_id = (hire.get("bandit_decision") or {}).get("arm_id")
        org = getattr(d, "org", None) or {}
        if isinstance(org, dict) and not arm_id:
            arm_id = org.get("bandit_arm")
    return bandit.record_reward(
        reward, desk_id=desk_id, arm_id=arm_id, reason=f"{oc}:{node_id or ''}"
    )


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
    Updates the effort bandit (retired with/without claim).
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
    # Claim heuristic: blackboard evidence/claim mentioning this node, or non-empty notes
    had_claim = bool((node.notes or "").strip()) or bool(
        blackboard.search(nid)
    ) or bool(summary and summary.strip())
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
    prior_state = node.state
    g.remove(nid, save=True)

    d, reg = _resolve_desk(desk)
    if d is not None and hasattr(reg, "_persist_desk_dag"):
        try:
            reg._persist_desk_dag(d)
            d.updated_at = time()
            reg.save()
        except Exception:  # noqa: BLE001
            pass

    # Bandit reward
    if prior_state == "failed":
        bandit_out = notify_outcome("failed", desk=d, node_id=nid)
    elif prior_state == "done" or had_claim:
        bandit_out = notify_outcome(
            "retired" if prior_state != "done" else "done",
            desk=d,
            node_id=nid,
            had_claim=had_claim,
        )
    else:
        bandit_out = notify_outcome("retired_without_claim", desk=d, node_id=nid)

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
        "bandit_reward": bandit_out,
        "had_claim": had_claim,
        "message": "Short-lived worker removed from active DAG; summary on blackboard",
    }
