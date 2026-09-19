"""Desk-rail control → okstratr API mapping (observer + DeskRail.qml contract).

Single lifecycle surface: Start / Stop / Dismiss / Delete (+ Quiet all).
Does not invent a second desk model — payloads hit existing ``/api/desk/*``
handlers and ``desks.*`` kernel methods.

Switchbay Agents tab still owns residual chrome (Edit→rail, Schedule dialog,
run transcript/cancel/bg, workspace switcher, Tools/Rules/Skills panels,
interrupted-orchestration resume). Thin those only after umbrella parity ✓.
"""

from __future__ import annotations

from typing import Any

# UI action id → HTTP contract (observer.js data-act / Quiet all).
DESK_RAIL_ACTIONS: dict[str, dict[str, Any]] = {
    "start": {
        "method": "POST",
        "path": "/api/desk/start",
        "body_keys": ("kind", "objective", "drive_herdr", "desk_id"),
        "required": (),
        "label_start": "Start",
        "label_continue": "Continue",
    },
    "stop": {
        "method": "POST",
        "path": "/api/desk/stop",
        "body_keys": ("desk_id",),
        "required": ("desk_id",),
        "label": "Stop",
    },
    "dismiss": {
        "method": "POST",
        "path": "/api/desk/dismiss",
        "body_keys": ("desk_id",),
        "required": ("desk_id",),
        "label": "Dismiss",
    },
    "delete": {
        "method": "POST",
        "path": "/api/desk/delete",
        "body_keys": ("desk_id", "force", "cleanup"),
        "required": ("desk_id",),
        "label": "Delete",
    },
    "quiet_all": {
        "method": "POST",
        "path": "/api/desk/quiet_standing",
        "body_keys": (),
        "required": (),
        "label": "Quiet all",
        "aliases": ("/api/desk/quiet-all",),
    },
}

# Hosted shells: HTML settings strip off; desk rail controls stay enabled.
HOSTED_SHELLS = frozenset({"switchbay", "okbay"})

# Still Switchbay-only (do not delete SB UI until these move or are waived).
SWITCHBAY_ONLY_CHROME = (
    "Edit brief → rail composer (sy:rail-set-input)",
    "Schedule create/edit dialog (sy:schedule-new; observer has badge only)",
    "Active-run transcript / cancel / background (/api/runs/active)",
    "Workspace switcher + open-Agents nav",
    "Tools / Rules / Command palettes / Providers / Skills panels",
    "Interrupted-orchestration resume list (/api/orchestration/interrupted)",
)


def is_hosted_shell(host: str | None) -> bool:
    """True when observer should hide settings (shell owns registry UI)."""
    if not host:
        return False
    return str(host).strip().lower() in HOSTED_SHELLS


def is_placeholder_desk_id(desk_id: str | None) -> bool:
    """Kind-placeholder rows (``kind:work``) are not real registry ids."""
    if not desk_id:
        return True
    s = str(desk_id).strip()
    return not s or s.startswith("kind:")


def row_actions(
    state: str | None,
    *,
    placeholder: bool = False,
) -> list[str]:
    """Which rail buttons a desk row shows (Switchbay DesksPanel + DeskRail parity).

    - Placeholder / empty kind row: Start (+ disabled Stop/Dismiss visually)
    - working: Continue, Stop, Dismiss
    - quiet/idle: Continue, Stop(disabled), Dismiss
    - dismissed: Start, Delete (no Dismiss)
    """
    st = str(state or "").strip().lower()
    if placeholder or (not st and placeholder):
        return ["start", "stop", "dismiss"]
    if st == "dismissed":
        return ["start", "stop", "delete"]
    # working, quiet, idle, or unknown standing
    return ["start", "stop", "dismiss"]


def start_label(state: str | None, *, placeholder: bool = False) -> str:
    """Start vs Continue label (DeskRail.qml / observer.js)."""
    st = str(state or "").strip().lower()
    if placeholder or st in ("", "dismissed"):
        return str(DESK_RAIL_ACTIONS["start"]["label_start"])
    return str(DESK_RAIL_ACTIONS["start"]["label_continue"])


def request_for(action: str, **fields: Any) -> dict[str, Any]:
    """Build method/path/body for a desk-rail control.

    Unknown keys are ignored. Required keys must be present and non-empty
    (except quiet_all). Raises ``ValueError`` on unknown action or missing
    required fields / placeholder desk_id where a real id is required.
    """
    act = str(action or "").strip().lower()
    if act in ("quiet", "quiet_standing", "quiet-all"):
        act = "quiet_all"
    spec = DESK_RAIL_ACTIONS.get(act)
    if spec is None:
        raise ValueError(f"unknown desk-rail action: {action!r}")

    body: dict[str, Any] = {}
    for key in spec["body_keys"]:
        if key not in fields or fields[key] is None:
            continue
        val = fields[key]
        if key == "desk_id":
            val = str(val).strip()
            if not val:
                continue
            body[key] = val
        elif key == "kind":
            body[key] = str(val).strip() or "auto"
        elif key == "objective":
            body[key] = str(val)
        elif key == "drive_herdr":
            body[key] = bool(val)
        elif key in ("force", "cleanup"):
            body[key] = bool(val)
        else:
            body[key] = val

    for req in spec["required"]:
        if req not in body or body[req] in ("", None):
            raise ValueError(f"{act} requires {req}")
        if req == "desk_id" and is_placeholder_desk_id(str(body[req])):
            raise ValueError(f"{act} requires a real desk_id, not placeholder")

    # Start: drive_herdr when objective non-empty (observer.js contract)
    if act == "start":
        obj = str(body.get("objective") or "").strip()
        if obj and "drive_herdr" not in body:
            body["drive_herdr"] = True
        if "kind" not in body:
            body["kind"] = "auto"

    return {
        "action": act,
        "method": spec["method"],
        "path": spec["path"],
        "body": body,
    }


def observer_paths() -> frozenset[str]:
    """All primary + alias paths the observer may POST for desk rail."""
    paths: set[str] = set()
    for spec in DESK_RAIL_ACTIONS.values():
        paths.add(str(spec["path"]))
        for alias in spec.get("aliases") or ():
            paths.add(str(alias))
    return frozenset(paths)
