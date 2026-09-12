"""Publish ~/.local/state/okstratr/status.json for QML FileView."""

from __future__ import annotations

import json
from pathlib import Path
from time import time
from typing import Any

from . import PORT, __version__
from . import blackboard, dag, schedule
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
        _state = str(data.get("state") or "seated")
    elif data.get("state") in ("ready", "seated", "running"):
        _state = str(data.get("state"))


def get_objective() -> str:
    _load_from_disk()
    return _seated_objective


def set_objective(objective: str) -> None:
    global _seated_objective, _state, _loaded, _loaded_from
    _loaded = True
    _loaded_from = status_path()
    _seated_objective = (objective or "").strip()
    _state = "seated" if _seated_objective else "ready"


def mark_ready() -> None:
    global _state
    _load_from_disk()
    if _state == "setup":
        _state = "ready"


def snapshot() -> dict[str, Any]:
    mark_ready()
    d = dag.default_dag().summary()
    bb = blackboard.summary()
    return {
        "ts": time(),
        "state": _state if _seated_objective or _state != "setup" else "ready",
        "objective": _seated_objective,
        "seated": bool(_seated_objective),
        "dag_nodes": d.get("nodes") or 0,
        "dag": d,
        "schedule": schedule.summary(),
        "blackboard": bb,
        "api_url": f"http://127.0.0.1:{PORT}",
        "herdr": "herdr",
        "version": __version__,
        "message": (
            f"Seated: {_seated_objective}" if _seated_objective else "No objective seated"
        ),
    }


def write_status(data: dict[str, Any] | None = None) -> dict[str, Any]:
    snap = data or snapshot()
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    return snap
