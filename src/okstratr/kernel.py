"""Kernel stub: hiring manager (no real LLM calls).

Chooses a default desk kind from a light objective heuristic, always ensures
a CoS, and returns a hire plan. Full Auto bandit / effort-slider utility is
documented in docs/DESK-KERNEL.md and not implemented here.
"""

from __future__ import annotations

import re
from typing import Any

from . import roles

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


def hire_plan(
    objective: str,
    *,
    kind: str | None = None,
    effort: float | None = None,
) -> dict[str, Any]:
    """
    Stub hiring plan: kind + roles. No LLM.

    effort ∈ [0, 1] (optional) lightly trims optional roles when low; full
    utility / bandit is future work.
    """
    chosen = choose_kind(objective, kind)
    hired = roles.roles_for_kind(chosen)

    # Curate guard: never hire curator_worker without judge (commit path).
    if roles.ROLE_CURATOR_WORKER in hired and roles.ROLE_CURATOR_JUDGE not in hired:
        hired.append(roles.ROLE_CURATOR_JUDGE)

    # Low effort → CoS + planner only (minimal desk for simple questions).
    if effort is not None and effort < 0.35:
        hired = ensure_cos([roles.ROLE_COS, roles.ROLE_PLANNER])
    else:
        hired = ensure_cos(hired)

    return {
        "kind": chosen,
        "kind_was_default": chosen in KNOWN_KINDS,
        "objective": (objective or "").strip(),
        "roles": hired,
        "cos": roles.ROLE_COS,
        "effort": effort,
        "model_policy": "strongest_available_or_user_choice",
        "stub": True,
        "notes": [
            "Workers send succinct summaries only (no full reasoning traces).",
            "Short-lived workers must retire from the DAG.",
            "Curate path requires propose→review→commit land capability.",
        ],
    }


def spin_up_desk_spec(
    objective: str,
    *,
    kind: str | None = None,
    effort: float | None = None,
) -> dict[str, Any]:
    """Kernel entry: decide desk type + hires for a new or resumed objective."""
    plan = hire_plan(objective, kind=kind, effort=effort)
    # Minimal desk for very short questions when kind is auto and obj is short.
    obj = plan["objective"]
    if plan["kind"] == "auto" and obj and len(obj.split()) <= 6 and effort is None:
        # Still keep CoS; allow planner only for tiny questions
        if not _CODE_RE.search(obj) and not _CURATE_RE.search(obj):
            plan = dict(plan)
            plan["roles"] = ensure_cos([roles.ROLE_COS, roles.ROLE_PLANNER])
            plan["minimal"] = True
    return plan
