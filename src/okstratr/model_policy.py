"""Which models a desk may use.

Each workspace can allow or deny models. Keys are ``harness/model``,
``harness/*`` (every model on that harness) or a bare ``model`` (that
model on any harness). Deny wins over allow. An empty allow list means
"everything not denied". A workspace with no entry of its own uses the
global entry.

Stored in ``<state>/model_policy.json``. No model is called here.
"""

from __future__ import annotations

import json
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


def filter_pairs(pairs: list[tuple[str, str | None]], workspace_id: str | None = None) -> list[tuple[str, str | None]]:
    pol = get(workspace_id)
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
