"""Role catalog for desk orgs (pi-agent-plugin style stubs).

Roles maximize **independent opinions**: orthogonal permissions / precedents,
and different models when multiples of a role are allowed. Workers must send
succinct summaries only — never full reasoning traces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- Core roles (always considered) ---
ROLE_COS = "cos"
ROLE_PLANNER = "planner"
ROLE_INVESTIGATOR = "investigator"
ROLE_VERIFIER = "verifier"
ROLE_SYNTHESIZER = "synthesizer"

# --- Optional / kind-specific ---
ROLE_CURATOR_WORKER = "curator_worker"
ROLE_CURATOR_PLANNER = "curator_planner"
ROLE_CURATOR_JUDGE = "curator_judge"
ROLE_RESEARCHER = "researcher"

CORE_ROLES: tuple[str, ...] = (
    ROLE_COS,
    ROLE_PLANNER,
    ROLE_INVESTIGATOR,
    ROLE_VERIFIER,
    ROLE_SYNTHESIZER,
)

OPTIONAL_ROLES: tuple[str, ...] = (
    ROLE_CURATOR_WORKER,
    ROLE_CURATOR_PLANNER,
    ROLE_CURATOR_JUDGE,
    ROLE_RESEARCHER,
)

ALL_ROLES: tuple[str, ...] = CORE_ROLES + OPTIONAL_ROLES

# Desk kind → default hired set (CoS always first). Kinds are defaults, not a closed enum.
DEFAULT_KIND_ROLES: dict[str, tuple[str, ...]] = {
    "auto": CORE_ROLES,
    "work": CORE_ROLES,
    "code": (ROLE_COS, ROLE_PLANNER, ROLE_INVESTIGATOR, ROLE_VERIFIER, ROLE_SYNTHESIZER),
    "deck": (ROLE_COS, ROLE_PLANNER, ROLE_SYNTHESIZER, ROLE_VERIFIER),
    "curate": (
        ROLE_COS,
        ROLE_CURATOR_PLANNER,
        ROLE_CURATOR_WORKER,
        ROLE_CURATOR_JUDGE,
        ROLE_SYNTHESIZER,
        ROLE_VERIFIER,
    ),
}

DEFAULT_DESK_KINDS: tuple[str, ...] = ("curate", "work", "code", "deck", "auto")


@dataclass(frozen=True)
class RoleSpec:
    id: str
    title: str
    summary: str
    permissions: tuple[str, ...]
    """Orthogonal permission tags — prefer non-overlapping precedents across roles."""
    may_web_search: bool = False
    """researcher only; must sit behind human/CoS approval."""
    can_commit: bool = False
    """Curate writers must only be hired when a commit/land path exists."""
    independence_note: str = ""


ROLE_CATALOG: dict[str, RoleSpec] = {
    ROLE_COS: RoleSpec(
        id=ROLE_COS,
        title="Chief of staff",
        summary="Only user interface; requests firepower from the kernel; prioritizes.",
        permissions=("user_iface", "hire_request", "prioritize"),
        independence_note="Single CoS per desk; never duplicate as a second UI.",
    ),
    ROLE_PLANNER: RoleSpec(
        id=ROLE_PLANNER,
        title="Planner",
        summary="Breaks objectives into DAG nodes; does not execute.",
        permissions=("dag_plan", "decompose"),
        independence_note="Orthogonal to investigator (no evidence gathering).",
    ),
    ROLE_INVESTIGATOR: RoleSpec(
        id=ROLE_INVESTIGATOR,
        title="Investigator",
        summary="Gathers evidence and context; posts succinct claims.",
        permissions=("gather", "claim"),
        independence_note="Orthogonal to planner and verifier.",
    ),
    ROLE_VERIFIER: RoleSpec(
        id=ROLE_VERIFIER,
        title="Verifier",
        summary="Checks outcomes against success criteria.",
        permissions=("verify", "reject_accept"),
        independence_note="Must not share write permissions with the executor it checks.",
    ),
    ROLE_SYNTHESIZER: RoleSpec(
        id=ROLE_SYNTHESIZER,
        title="Synthesizer",
        summary="Merges independent opinions into succinct blackboard claims.",
        permissions=("synthesize", "blackboard_write"),
        independence_note="Consumes summaries only; never re-asks full traces.",
    ),
    ROLE_CURATOR_WORKER: RoleSpec(
        id=ROLE_CURATOR_WORKER,
        title="Curator worker",
        summary="Drafts curated pages — only when a commit/land path exists.",
        permissions=("curate_draft",),
        can_commit=False,  # drafts only; judge + commit path required
        independence_note=(
            "Do not hire without curator_judge and a real commit path "
            "(Switchbay bug: token burn without land)."
        ),
    ),
    ROLE_CURATOR_PLANNER: RoleSpec(
        id=ROLE_CURATOR_PLANNER,
        title="Curator planner",
        summary="Plans propose → review → commit for curation.",
        permissions=("curate_plan", "dag_plan"),
        independence_note="Ensures propose→review can land pages before workers spawn.",
    ),
    ROLE_CURATOR_JUDGE: RoleSpec(
        id=ROLE_CURATOR_JUDGE,
        title="Curator judge",
        summary="Reviews drafts before commit.",
        permissions=("curate_review", "reject_accept"),
        can_commit=True,
        independence_note="Orthogonal to curator_worker; owns the land/commit gate.",
    ),
    ROLE_RESEARCHER: RoleSpec(
        id=ROLE_RESEARCHER,
        title="Researcher",
        summary="Optional web search behind CoS/human approval.",
        permissions=("research",),
        may_web_search=True,
        independence_note="Web search disabled until explicitly approved.",
    ),
}


# Model hints: kernel prefers strongest for CoS/planner/judge; diversity for multiples.
DEFAULT_MODEL_HINTS: dict[str, str] = {
    ROLE_COS: "strongest_available",
    ROLE_PLANNER: "strongest_available",
    ROLE_INVESTIGATOR: "diverse",
    ROLE_VERIFIER: "diverse",
    ROLE_SYNTHESIZER: "strongest_available",
    ROLE_CURATOR_WORKER: "diverse",
    ROLE_CURATOR_PLANNER: "strongest_available",
    ROLE_CURATOR_JUDGE: "strongest_available",
    ROLE_RESEARCHER: "diverse",
}

# Switchbay planner breakdown roles (work/auto desks).
SWITCHBAY_PLAN_ROLES: tuple[str, ...] = (
    ROLE_INVESTIGATOR,
    ROLE_SYNTHESIZER,
    ROLE_VERIFIER,
)


def model_hint_for(role_id: str) -> str:
    return DEFAULT_MODEL_HINTS.get(role_id, "strongest_available")


def roles_for_kind(kind: str) -> list[str]:
    """Default role ids for a desk kind (CoS always first)."""
    k = (kind or "auto").strip().lower() or "auto"
    roles = list(DEFAULT_KIND_ROLES.get(k, CORE_ROLES))
    if ROLE_COS not in roles:
        roles.insert(0, ROLE_COS)
    elif roles[0] != ROLE_COS:
        roles = [ROLE_COS] + [r for r in roles if r != ROLE_COS]
    return roles


def catalog_summary() -> dict[str, Any]:
    return {
        "core": list(CORE_ROLES),
        "optional": list(OPTIONAL_ROLES),
        "kinds": {k: list(v) for k, v in DEFAULT_KIND_ROLES.items()},
        "independence": "orthogonal permissions/precedents; different models when multiples allowed",
        "channel_rule": "workers send succinct summaries only — never full reasoning traces",
        "model_hints": dict(DEFAULT_MODEL_HINTS),
        "switchbay_plan": list(SWITCHBAY_PLAN_ROLES),
        "roles": {rid: ROLE_CATALOG[rid].summary for rid in ALL_ROLES if rid in ROLE_CATALOG},
    }
