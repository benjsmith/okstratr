"""Which models a desk may use, and which one each node gets.

Each workspace can allow or deny models. Keys are ``harness/model``,
``harness/*`` (every model on that harness) or a bare ``model`` (that
model on any harness). Deny wins over allow. An empty allow list means
"everything not denied". A workspace with no entry of its own uses the
global entry.

Stored in ``<state>/model_policy.json``. No model is called here.

Picking: the verifier (critic) gets the strongest allowed model,
whatever the effort slider says. Authors (investigators, writers,
synthesizer) get a model from their harness's allowed pool by effort:
low effort → cheapest, high effort → strongest other than the critic,
otherwise the middle of the pool. ``model_strength`` is a name heuristic,
not a price list.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .paths import state_dir

GLOBAL = "_global"


def policy_path() -> Path:
    return state_dir() / "model_policy.json"


def _clean(raw: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        key = str(item or "").strip()
        if "/" in key:
            h, _, m = key.partition("/")
            key = f"{h.strip().lower()}/{m.strip()}"
        if key and key not in out:
            out.append(key)
    return out


def _load() -> dict[str, Any]:
    try:
        raw = json.loads(policy_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    ws = raw.get("workspaces")
    return {"workspaces": ws if isinstance(ws, dict) else {}}


def _save(data: dict[str, Any]) -> None:
    path = policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"version": 1, **data}, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _ws_key(workspace_id: str | None) -> str:
    return str(workspace_id or "").strip() or GLOBAL


def get(workspace_id: str | None = None) -> dict[str, Any]:
    """Effective lists for a workspace (falls back to the global entry)."""
    data = _load().get("workspaces", {})
    key = _ws_key(workspace_id)
    entry = data.get(key)
    inherited = False
    if not isinstance(entry, dict) and key != GLOBAL:
        entry = data.get(GLOBAL)
        inherited = True
    entry = entry if isinstance(entry, dict) else {}
    return {
        "workspace": key,
        "inherited": inherited,
        "allowed": _clean(entry.get("allowed")),
        "denied": _clean(entry.get("denied")),
    }


def set_lists(
    workspace_id: str | None = None,
    *,
    allowed: list[str] | None = None,
    denied: list[str] | None = None,
) -> dict[str, Any]:
    """Replace one workspace's lists (``None`` leaves a list as it is)."""
    data = _load()
    ws = data.setdefault("workspaces", {})
    key = _ws_key(workspace_id)
    cur = get(workspace_id)
    entry = {
        "allowed": _clean(allowed) if allowed is not None else cur["allowed"],
        "denied": _clean(denied) if denied is not None else cur["denied"],
    }
    ws[key] = entry
    _save(data)
    return get(workspace_id)


def add(workspace_id: str | None, key: str, *, deny: bool) -> dict[str, Any]:
    """Allow or deny one key; it is taken off the other list."""
    k = (_clean([key]) or [""])[0]
    if not k:
        return get(workspace_id)
    cur = get(workspace_id)
    field, other = ("denied", "allowed") if deny else ("allowed", "denied")
    return set_lists(
        workspace_id,
        **{field: cur[field] + [k], other: [x for x in cur[other] if x != k]},
    )


def remove(workspace_id: str | None, key: str) -> dict[str, Any]:
    """Take one key off both lists."""
    k = (_clean([key]) or [""])[0]
    cur = get(workspace_id)
    return set_lists(
        workspace_id,
        allowed=[x for x in cur["allowed"] if x != k],
        denied=[x for x in cur["denied"] if x != k],
    )


def reset(workspace_id: str | None = None) -> dict[str, Any]:
    """Drop a workspace's own entry so it inherits the global one again."""
    data = _load()
    data.setdefault("workspaces", {}).pop(_ws_key(workspace_id), None)
    _save(data)
    return get(workspace_id)


def _matches(key: str, harness: str, model: str | None) -> bool:
    h = (harness or "").strip().lower()
    m = (model or "").strip()
    if "/" in key:
        kh, _, km = key.partition("/")
        return kh == h and (km == "*" or km == m)
    return bool(m) and key == m


def is_allowed(harness: str, model: str | None, workspace_id: str | None = None,
               *, policy: dict[str, Any] | None = None) -> bool:
    pol = policy or get(workspace_id)
    if any(_matches(k, harness, model) for k in pol["denied"]):
        return False
    allowed = pol["allowed"]
    return not allowed or any(_matches(k, harness, model) for k in allowed)


def filter_pairs(
    pairs: list[tuple[str, str | None]],
    workspace_id: str | None = None,
    *,
    policy: dict[str, Any] | None = None,
) -> list[tuple[str, str | None]]:
    pol = policy or get(workspace_id)
    return [(h, m) for h, m in pairs if is_allowed(h, m, policy=pol)]


def current_workspace_id(desk_id: str | None = None) -> str | None:
    """The desk's bound workspace, else ``OKSTRATR_WORKSPACE``, else None (global)."""
    import os

    try:
        from . import desks

        reg = desks.default_registry()
        d = reg.desks.get(desk_id) if desk_id else reg.active()
        if d is not None and str(getattr(d, "okbay_workspace_id", "") or "").strip():
            return str(d.okbay_workspace_id).strip()
    except Exception:  # noqa: BLE001
        pass
    for key in ("OKSTRATR_WORKSPACE", "OKSTRATR_OKBAY_WORKSPACE"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return None


# ── strength and picking ───────────────────────────────────────────

Pair = tuple[str, "str | None"]

_CHEAP = ("mini", "nano", "haiku", "flash", "small", "tiny", "lite", "luna")
_FLAGSHIP = ("opus", "o3", "o1", "gpt-5.5", "gpt-5.4", "gpt-5", "grok-4", "ultra")


def model_strength(model: str | None) -> float:
    """0..1 guess at how strong a model is from its name.

    Cheap or small names (mini, haiku, flash, ≤8b …) score low; opus,
    o3, gpt-5, grok-4 score high; sonnet / *-pro sit between.
    """
    m = (model or "").strip().lower()
    if not m:
        return 0.35
    token = m.partition("/")[2] or m
    score = 0.48
    cheap = any(s in token for s in _CHEAP)
    size = re.search(r"(\d+)\s*b\b", token)
    if size:
        n = int(size.group(1))
        if n <= 8:
            cheap = True
            score -= 0.08
        elif n >= 27:
            score += 0.12
    if cheap:
        score -= 0.22
    elif any(s in token for s in _FLAGSHIP):
        score += 0.28
    elif "sonnet" in token or token.endswith("-pro") or "-pro-" in token or "pro-preview" in token:
        score += 0.18
    elif "gemini" in token:
        score += 0.12
    return max(0.05, min(1.0, score))


def candidate_pairs(
    harnesses: list[str],
    workspace_id: str | None = None,
    *,
    cfg: Any = None,
    policy: dict[str, Any] | None = None,
) -> list[Pair]:
    """Allowed (harness, model) pairs from each harness's configured pool."""
    if cfg is None:
        try:
            from .harness import config as harness_config

            cfg = harness_config.load()
        except Exception:  # noqa: BLE001
            cfg = None
    pairs: list[Pair] = []
    for h in harnesses:
        h = (h or "").strip().lower()
        if not h:
            continue
        models: list[str] = []
        if cfg is not None:
            try:
                models = [ms.id for ms in cfg.models_for(h)]
                dm = cfg.default_model_for(h)
                if dm and dm not in models:
                    models.append(dm)
            except Exception:  # noqa: BLE001
                models = []
        if not models:
            pairs.append((h, None))
        else:
            pairs.extend((h, m) for m in models if (h, m) not in pairs)
    return filter_pairs(pairs, workspace_id, policy=policy)


def pick_critic(pairs: list[Pair], *, avoid_harnesses: Any = ()) -> Pair | None:
    """Strongest allowed pair. Ties go to a harness the authors did not use,
    then to the earlier harness in ``pairs`` (preference order)."""
    if not pairs:
        return None
    avoid = {str(h) for h in avoid_harnesses or () if h}
    order = {h: i for i, h in enumerate(dict.fromkeys(h for h, _ in pairs))}
    return max(
        pairs,
        key=lambda p: (model_strength(p[1]), p[0] not in avoid, -order[p[0]]),
    )


def author_model(
    harness: str,
    effort: float | None,
    pairs: list[Pair],
    *,
    critic: Pair | None = None,
    task_class: str = "general",
    stats: Any = None,
) -> str | None:
    """Model for an author seat on ``harness``.

    The strongest model in the harness's pool (the critic's pair is kept for
    the critic when there are others), unless a cheaper one has a record on
    this task class that makes it the better expected utility at this effort
    once rework and spinning are priced in (:mod:`okstratr.model_routing`).
    """
    from . import model_routing

    pool = [p for p in pairs if p[0] == harness]
    if not pool:
        return None
    if critic is not None and len(pool) > 1:
        pool = [p for p in pool if p != critic] or pool
    e = 0.5 if effort is None else max(0.0, min(1.0, float(effort)))
    model, _ = model_routing.choose([m for _, m in pool], task_class or "general", e, stats=stats)
    return model


def assign_models(
    harnesses: list[str],
    effort: float | None,
    *,
    workspace_id: str | None = None,
    pinned: dict[str, str] | None = None,
    cfg: Any = None,
    policy: dict[str, Any] | None = None,
    task_class: str = "general",
    stats: Any = None,
) -> dict[str, Any]:
    """Pick models for one run.

    Returns ``{"harnesses": [...allowed...], "authors": {harness: model},
    "pairs": [...]}``. ``pinned`` (e.g. ``OKSTRATR_MODEL_BY_HARNESS``) wins
    for authors when the pinned model is allowed. A harness with nothing
    allowed is dropped. The critic is picked later with
    :func:`pick_critic`, once the plan knows which harnesses the authors used.
    """
    pol = policy or get(workspace_id)
    pairs = candidate_pairs(harnesses, workspace_id, cfg=cfg, policy=pol)
    pinned = {k.strip().lower(): v for k, v in (pinned or {}).items() if k and v}
    for h, m in pinned.items():
        if h in harnesses and (h, m) not in pairs and is_allowed(h, m, policy=pol):
            pairs.append((h, m))
    allowed_h = [h for h in harnesses if any(p[0] == h for p in pairs)]
    best = pick_critic(pairs)
    authors: dict[str, Any] = {}
    for h in allowed_h:
        pm = pinned.get(h)
        if pm and is_allowed(h, pm, policy=pol):
            authors[h] = pm
        else:
            authors[h] = author_model(h, effort, pairs, critic=best, task_class=task_class, stats=stats)
    return {"harnesses": allowed_h, "authors": authors, "pairs": pairs}
