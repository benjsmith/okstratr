"""Publish ~/.local/state/okstratr/status.json for QML FileView."""

from __future__ import annotations

import json
from pathlib import Path
from time import time
from typing import Any

from . import PORT, __version__
from . import blackboard, dag, herdr, okbay, schedule
# desks imported lazily in snapshot to avoid cycles
from .paths import state_dir as _state_dir

STATUS_NAME = "status.json"

_seated_objective: str = ""
_state: str = "setup"
_loaded = False
_loaded_from: Path | None = None


def state_dir() -> Path:
    return _state_dir()


def status_path() -> Path:
    return state_dir() / STATUS_NAME


def _load_from_disk() -> None:
    global _seated_objective, _state, _loaded, _loaded_from
    path = status_path()
    if _loaded and _loaded_from == path:
        return
    _loaded = True
    _loaded_from = path
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    obj = str(data.get("objective") or "").strip()
    if obj:
        _seated_objective = obj
        st = str(data.get("state") or "ready")
        # Prefer working|quiet; map legacy "seated" → working
        if st == "seated":
            st = "working"
        _state = st
    elif data.get("state") in ("ready", "working", "quiet", "seated", "running"):
        st = str(data.get("state"))
        _state = "working" if st == "seated" else st


def get_objective() -> str:
    _load_from_disk()
    return _seated_objective


def set_objective(objective: str) -> None:
    global _seated_objective, _state, _loaded, _loaded_from
    _loaded = True
    _loaded_from = status_path()
    _seated_objective = (objective or "").strip()
    _state = "ready" if not _seated_objective else "working"


def mark_ready() -> None:
    global _state
    _load_from_disk()
    if _state == "setup":
        _state = "ready"


def snapshot() -> dict[str, Any]:
    mark_ready()
    d = dag.default_dag().summary()
    bb = blackboard.summary()
    desk_brief = None
    focus_desk_id = None
    effort = None
    labels: dict[str, Any] = {
        "desk_id": None,
        "thread_id": None,
        "focus_desk_id": None,
        "format": herdr.AGENT_ID_FORMAT,
    }
    try:
        from . import desks as desks_mod
        from . import kernel

        reg = desks_mod.default_registry()
        active = reg.active()
        focus_desk_id = reg.focus_id or reg.active_id
        effort = active.effort if active else None
        standing_list = [
            {
                "id": sd.id,
                "kind": sd.kind,
                "state": sd.state,
                "objective": sd.objective,
            }
            for sd in reg.standing()
        ]
        desk_brief = {
            "active_id": reg.active_id,
            "focus_desk_id": focus_desk_id,
            "state": active.state if active else None,
            "kind": active.kind if active else None,
            "objective": active.objective if active else None,
            "effort": effort,
            "roles": list(active.roles) if active else [],
            "org": dict(active.org) if active else {},
            "standing": standing_list,
            "standing_count": len(standing_list),
            "okbay_workspace_id": active.okbay_workspace_id if active else "",
            "thread_id": active.thread_id if active else "",
            "dag_nodes": d.get("nodes") or 0,
        }
        if active:
            labels = herdr.labels_for_desk(active)
            labels["focus_desk_id"] = focus_desk_id
    except Exception:  # noqa: BLE001
        desk_brief = None
        kernel = None  # type: ignore[assignment]

    display_state = (desk_brief or {}).get("state") or (
        "working" if _seated_objective else ("ready" if _state != "setup" else "ready")
    )
    kind = (desk_brief or {}).get("kind")
    obj = _seated_objective or ((desk_brief or {}).get("objective") or "")
    if obj and kind and display_state in ("working", "quiet"):
        msg = f"{kind} · {display_state}: {obj}"
    elif obj:
        msg = f"Desk: {obj}"
    else:
        msg = "No desk objective"

    effort_slider = None
    try:
        from . import kernel as kernel_mod

        desk_id = (desk_brief or {}).get("active_id")
        effort_slider = kernel_mod.effort_slider(effort, desk_id=desk_id)
    except Exception:  # noqa: BLE001
        effort_slider = {"value": effort, "stub": False, "bandit": True}

    web_egress = None
    try:
        from . import web_egress as web_mod

        web_egress = web_mod.status()
    except Exception:  # noqa: BLE001
        web_egress = {"mode": "off", "label": "Off", "chip": "Web: Off", "gate": True}

    return {
        "ts": time(),
        "state": display_state,
        "objective": obj,
        "seated": bool(obj),  # compat; UI should bind desk.state not this
        "desk": desk_brief,
        "desk_kind": kind,
        "desk_state": (desk_brief or {}).get("state"),
        "dag_nodes": d.get("nodes") or 0,
        "dag": d,
        "schedule": schedule.summary(),
        "blackboard": bb,
        "api_url": f"http://127.0.0.1:{PORT}",
        "herdr": "herdr",
        "herdr_labels": labels,
        "focus_desk_id": focus_desk_id,
        "effort": effort,
        "effort_slider": effort_slider,
        "web_egress": web_egress,
        "okbay": okbay.active_workspace(),
        "ui": {
            "left_pane": "desk_switch",
            "show_dag": True,
            "show_blackboard": True,
            "text_input": False,
            "close_warning": herdr.CLOSE_WARNING,
        },
        "version": __version__,
        "message": msg,
    }


def write_status(data: dict[str, Any] | None = None) -> dict[str, Any]:
    snap = data or snapshot()
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    return snap
