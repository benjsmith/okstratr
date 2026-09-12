"""Effort-bandit hire policies: persist arm stats, map effort → utility weights.

Info-theory flavored utility (documented in docs/DESK-KERNEL.md):

  effort e ∈ [0, 1]
  w_quality = e
  w_cost    = 1 − e

  Hire one more independent worker iff
    ΔU = w_quality · I_marginal − w_cost · c_scaled  >  0

  where
    I_marginal ∈ (0, 1]  — independence of the candidate vs already-granted
                           (1.0 orthogonal new role; lower for duplicates /
                           overlapping permission tags; diversity bonus when
                           model_hint differs for multiples)
    c_scaled = COST_UNIT · (1 + λ · n_non_cos) / (1 + μ · e)
               (effort scales down effective cost so high effort buys more)

Hard ceiling remains hire_cap(e). Bandit arms are hire policies
(N workers × model-diversity on/off × role-set key); UCB1 selects among
arms feasible under the cap. Rewards: done=+1, failed/timeout=−1,
retired_without_claim=−0.5.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from time import time
from typing import Any

from . import roles
from .paths import state_dir

STATE_NAME = "bandit.json"
COST_UNIT = 0.35
LAMBDA_N = 0.25
MU_EFFORT = 1.5
UCB_C = 1.2

# Policy arms: (arm_id, n_workers, diversity, role_set_key)
# role_set_key: "minimal" | "core" | "kind" (use kind defaults)
DEFAULT_ARMS: tuple[tuple[str, int, bool, str], ...] = (
    ("n2_div0_minimal", 2, False, "minimal"),
    ("n4_div0_core", 4, False, "core"),
    ("n4_div1_core", 4, True, "core"),
    ("n5_div0_kind", 5, False, "kind"),
    ("n5_div1_kind", 5, True, "kind"),
    ("n6_div0_kind", 6, False, "kind"),
    ("n6_div1_kind", 6, True, "kind"),
    ("n8_div1_kind", 8, True, "kind"),
    ("n10_div1_kind", 10, True, "kind"),
)

REWARD_DONE = 1.0
REWARD_FAILED = -1.0
REWARD_TIMEOUT = -1.0
REWARD_RETIRED_NO_CLAIM = -0.5

_CACHE: dict[str, Any] | None = None
_CACHE_PATH: Path | None = None


def _path() -> Path:
    return state_dir() / STATE_NAME


def reset_cache() -> None:
    global _CACHE, _CACHE_PATH
    _CACHE = None
    _CACHE_PATH = None


def clamp_effort(effort: float | None) -> float:
    if effort is None:
        return 0.5
    try:
        return max(0.0, min(1.0, float(effort)))
    except (TypeError, ValueError):
        return 0.5


def utility_weights(effort: float | None) -> dict[str, float]:
    e = clamp_effort(effort)
    return {
        "effort": e,
        "w_quality": e,
        "w_cost": 1.0 - e,
        "cost_unit": COST_UNIT,
        "lambda_n": LAMBDA_N,
        "mu_effort": MU_EFFORT,
    }


def hire_cap(effort: float | None) -> int:
    e = clamp_effort(effort)
    if e < 0.35:
        return 2
    if e < 0.70:
        return 6
    return 10


def _empty_arm(arm_id: str, n: int, diversity: bool, role_set: str) -> dict[str, Any]:
    return {
        "id": arm_id,
        "n_workers": n,
        "diversity": diversity,
        "role_set": role_set,
        "pulls": 0,
        "reward_sum": 0.0,
        "mean": 0.0,
    }


def _default_store() -> dict[str, Any]:
    arms = {
        a[0]: _empty_arm(a[0], a[1], a[2], a[3]) for a in DEFAULT_ARMS
    }
    return {
        "version": 1,
        "global": {"arms": arms, "last_decision": None, "total_pulls": 0},
        "desks": {},
    }


def _load(*, force: bool = False) -> dict[str, Any]:
    global _CACHE, _CACHE_PATH
    path = _path()
    if not force and _CACHE is not None and _CACHE_PATH == path:
        return _CACHE
    store = _default_store()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                store["global"] = _merge_bucket(store["global"], raw.get("global") or {})
                desks = {}
                for did, bucket in (raw.get("desks") or {}).items():
                    if isinstance(bucket, dict):
                        desks[str(did)] = _merge_bucket(
                            {"arms": {a[0]: _empty_arm(a[0], a[1], a[2], a[3]) for a in DEFAULT_ARMS},
                             "last_decision": None, "total_pulls": 0},
                            bucket,
                        )
                store["desks"] = desks
        except (OSError, json.JSONDecodeError):
            pass
    _CACHE = store
    _CACHE_PATH = path
    return store


def _merge_bucket(base: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    arms = dict(base.get("arms") or {})
    for a in DEFAULT_ARMS:
        if a[0] not in arms:
            arms[a[0]] = _empty_arm(a[0], a[1], a[2], a[3])
    for aid, stats in (raw.get("arms") or {}).items():
        if not isinstance(stats, dict):
            continue
        if aid not in arms:
            arms[aid] = _empty_arm(
                aid,
                int(stats.get("n_workers") or 2),
                bool(stats.get("diversity")),
                str(stats.get("role_set") or "kind"),
            )
        cur = arms[aid]
        cur["pulls"] = int(stats.get("pulls") or 0)
        cur["reward_sum"] = float(stats.get("reward_sum") or 0.0)
        pulls = cur["pulls"]
        cur["mean"] = (cur["reward_sum"] / pulls) if pulls else 0.0
        if "n_workers" in stats:
            cur["n_workers"] = int(stats["n_workers"])
        if "diversity" in stats:
            cur["diversity"] = bool(stats["diversity"])
        if "role_set" in stats:
            cur["role_set"] = str(stats["role_set"])
    return {
        "arms": arms,
        "last_decision": raw.get("last_decision"),
        "total_pulls": int(raw.get("total_pulls") or 0),
        "active_arm": raw.get("active_arm"),
    }


def _save(store: dict[str, Any]) -> None:
    global _CACHE, _CACHE_PATH
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(store)
    payload["updated_at"] = time()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    _CACHE = store
    _CACHE_PATH = path


def _bucket(store: dict[str, Any], desk_id: str | None) -> dict[str, Any]:
    if desk_id:
        desks = store.setdefault("desks", {})
        if desk_id not in desks:
            desks[desk_id] = {
                "arms": {a[0]: _empty_arm(a[0], a[1], a[2], a[3]) for a in DEFAULT_ARMS},
                "last_decision": None,
                "total_pulls": 0,
            }
        return desks[desk_id]
    return store["global"]


def independence_score(
    role_id: str,
    granted: list[str],
    *,
    model_hint: str | None = None,
    granted_hints: list[str] | None = None,
) -> float:
    """I_marginal ∈ (0,1]: higher for orthogonal new roles / diverse models."""
    if role_id == roles.ROLE_COS:
        return 1.0
    if role_id not in granted:
        # New role: check permission overlap with granted
        spec = roles.ROLE_CATALOG.get(role_id)
        if spec is None:
            return 0.85
        new_perms = set(spec.permissions)
        overlap = 0
        for gid in granted:
            if gid == roles.ROLE_COS:
                continue
            other = roles.ROLE_CATALOG.get(gid)
            if other and new_perms & set(other.permissions):
                overlap += 1
        base = max(0.35, 1.0 - 0.2 * overlap)
        return base
    # Duplicate role — prefer different model_hint
    count = granted.count(role_id)
    if model_hint and granted_hints:
        same_hint = sum(
            1
            for g, h in zip(granted, granted_hints)
            if g == role_id and h == model_hint
        )
        if same_hint == 0:
            return max(0.25, 0.55 / count)  # diversity bonus
    return max(0.05, 0.2 / count)


def marginal_utility(
    role_id: str,
    granted: list[str],
    effort: float | None,
    *,
    model_hint: str | None = None,
    granted_hints: list[str] | None = None,
) -> dict[str, Any]:
    w = utility_weights(effort)
    n_non_cos = sum(1 for r in granted if r != roles.ROLE_COS)
    i_m = independence_score(
        role_id, granted, model_hint=model_hint, granted_hints=granted_hints
    )
    c_scaled = COST_UNIT * (1.0 + LAMBDA_N * n_non_cos) / (1.0 + MU_EFFORT * w["effort"])
    delta = w["w_quality"] * i_m - w["w_cost"] * c_scaled
    return {
        "role": role_id,
        "I_marginal": i_m,
        "c_scaled": c_scaled,
        "delta_u": delta,
        "accept": delta > 0 or role_id == roles.ROLE_COS,
        "weights": w,
    }


def _ucb_score(arm: dict[str, Any], total_pulls: int) -> float:
    pulls = int(arm.get("pulls") or 0)
    mean = float(arm.get("mean") or 0.0)
    if pulls <= 0:
        return float("inf")
    return mean + UCB_C * math.sqrt(math.log(max(total_pulls, 1) + 1) / pulls)


def select_arm(
    effort: float | None,
    *,
    desk_id: str | None = None,
    prefer_diversity: bool | None = None,
) -> dict[str, Any]:
    """UCB1 over arms with n_workers <= hire_cap(effort)."""
    store = _load()
    bucket = _bucket(store, desk_id)
    cap = hire_cap(effort)
    w = utility_weights(effort)
    # High effort prefers diversity when unspecified
    if prefer_diversity is None:
        prefer_diversity = w["effort"] >= 0.55

    candidates = [
        a
        for a in bucket["arms"].values()
        if int(a.get("n_workers") or 0) <= cap
    ]
    if not candidates:
        # Fallback minimal
        aid = "n2_div0_minimal"
        arm = bucket["arms"].get(aid) or _empty_arm(aid, 2, False, "minimal")
        candidates = [arm]

    # Soft preference: among untied UCB, lean diversity at high effort
    total = int(bucket.get("total_pulls") or 0)
    scored = []
    for a in candidates:
        s = _ucb_score(a, total)
        bias = 0.05 if (prefer_diversity and a.get("diversity")) else 0.0
        if not prefer_diversity and a.get("diversity"):
            bias = -0.02
        scored.append((s + bias, a))
    scored.sort(key=lambda x: (-(float("inf") if math.isinf(x[0]) else x[0]), -int(x[1].get("n_workers") or 0)))
    chosen = scored[0][1]
    decision = {
        "arm_id": chosen["id"],
        "n_workers": chosen["n_workers"],
        "diversity": bool(chosen.get("diversity")),
        "role_set": chosen.get("role_set") or "kind",
        "cap": cap,
        "weights": w,
        "ucb": None if math.isinf(scored[0][0]) else scored[0][0],
        "ts": time(),
        "desk_id": desk_id,
    }
    bucket["last_decision"] = decision
    bucket["active_arm"] = chosen["id"]
    # Count as a pull when selected for a hire plan
    chosen["pulls"] = int(chosen.get("pulls") or 0) + 1
    bucket["total_pulls"] = int(bucket.get("total_pulls") or 0) + 1
    pulls = chosen["pulls"]
    chosen["mean"] = (float(chosen.get("reward_sum") or 0.0) / pulls) if pulls else 0.0
    _save(store)
    return decision


def record_reward(
    reward: float,
    *,
    desk_id: str | None = None,
    arm_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    store = _load(force=True)
    bucket = _bucket(store, desk_id)
    # Also update global
    global_bucket = store["global"]
    aid = arm_id or bucket.get("active_arm") or (bucket.get("last_decision") or {}).get("arm_id")
    if not aid:
        aid = (global_bucket.get("active_arm") or (global_bucket.get("last_decision") or {}).get("arm_id"))
    updated = []
    for b in (bucket, global_bucket):
        if not aid or aid not in b.get("arms", {}):
            continue
        arm = b["arms"][aid]
        # Pull already counted on select; only accumulate reward here
        arm["reward_sum"] = float(arm.get("reward_sum") or 0.0) + float(reward)
        pulls = max(1, int(arm.get("pulls") or 0))
        arm["mean"] = arm["reward_sum"] / pulls
        updated.append({"scope": "desk" if b is bucket and desk_id else "global", "arm_id": aid, "mean": arm["mean"], "pulls": pulls})
    _save(store)
    return {
        "ok": True,
        "reward": reward,
        "reason": reason,
        "arm_id": aid,
        "updated": updated,
        "desk_id": desk_id,
    }


def roles_for_arm(
    kind: str,
    decision: dict[str, Any],
    *,
    base_roles: list[str] | None = None,
) -> list[str]:
    """Build role list for an arm decision (CoS always first; capped by n)."""
    n = int(decision.get("n_workers") or 2)
    role_set = decision.get("role_set") or "kind"
    if role_set == "minimal":
        hired = [roles.ROLE_COS, roles.ROLE_PLANNER]
    elif role_set == "core":
        hired = list(roles.CORE_ROLES)
    else:
        hired = list(base_roles or roles.roles_for_kind(kind))
    # Ensure CoS first
    if roles.ROLE_COS not in hired:
        hired.insert(0, roles.ROLE_COS)
    elif hired[0] != roles.ROLE_COS:
        hired = [roles.ROLE_COS] + [r for r in hired if r != roles.ROLE_COS]
    if len(hired) > n:
        hired = hired[:n]
        if roles.ROLE_COS not in hired:
            hired = [roles.ROLE_COS] + hired[: max(0, n - 1)]
    return hired


def filter_by_marginal_utility(
    hired: list[str],
    effort: float | None,
    *,
    diversity: bool = False,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Keep CoS; add others only while ΔU > 0 and under cap."""
    cap = hire_cap(effort)
    kept: list[str] = []
    hints: list[str] = []
    audits: list[dict[str, Any]] = []
    diversify_models = [
        "diverse",
        "strongest_available",
        "alt_diverse",
        "alt_strong",
    ]
    for role in hired:
        if role == roles.ROLE_COS:
            hint = roles.model_hint_for(role)
            kept.append(role)
            hints.append(hint)
            audits.append({"role": role, "accept": True, "reason": "cos_first"})
            continue
        if len(kept) >= cap:
            audits.append({"role": role, "accept": False, "reason": "hire_cap"})
            continue
        # Prefer different model_hint when diversity on and role already present
        if diversity and role in kept:
            used = {h for g, h in zip(kept, hints) if g == role}
            hint = next((m for m in diversify_models if m not in used), "diverse")
        else:
            hint = "diverse" if diversity and roles.model_hint_for(role) == "diverse" else roles.model_hint_for(role)
            if diversity and hint == "strongest_available" and role != roles.ROLE_PLANNER:
                hint = "diverse"
        mu = marginal_utility(role, kept, effort, model_hint=hint, granted_hints=hints)
        audits.append(mu)
        if mu["accept"]:
            kept.append(role)
            hints.append(hint)
    return kept, audits


def snapshot(effort: float | None = None, *, desk_id: str | None = None) -> dict[str, Any]:
    store = _load()
    bucket = _bucket(store, desk_id) if desk_id else store["global"]
    # Prefer desk bucket when desk_id; else merge view of global
    if desk_id and desk_id in store.get("desks", {}):
        bucket = store["desks"][desk_id]
    else:
        bucket = store["global"]
    w = utility_weights(effort)
    arms = sorted(
        bucket.get("arms", {}).values(),
        key=lambda a: (-float(a.get("mean") or 0), a.get("id")),
    )
    return {
        "stub": False,
        "bandit": True,
        "value": None if effort is None else clamp_effort(effort),
        "cap": hire_cap(effort),
        "weights": w,
        "arms": [
            {
                "id": a["id"],
                "n_workers": a["n_workers"],
                "diversity": a["diversity"],
                "role_set": a["role_set"],
                "pulls": a["pulls"],
                "mean": a["mean"],
                "reward_sum": a["reward_sum"],
            }
            for a in arms
        ],
        "last_decision": bucket.get("last_decision"),
        "active_arm": bucket.get("active_arm"),
        "total_pulls": bucket.get("total_pulls") or 0,
        "desk_id": desk_id,
        "formula": (
            "ΔU = w_quality·I_marginal − w_cost·c_scaled > 0; "
            "w_quality=e, w_cost=1−e; c_scaled=COST_UNIT·(1+λn)/(1+μe)"
        ),
    }
