"""Publish status snapshot (HTTP SSOT) + optional status.json compat mirror.

P4: clients prefer GET /api/status (DeskSession). status.json is a daemon
write-through compat mirror for offline bar chips — not authoritative when HTTP is up.
"""

from __future__ import annotations

import os

import json
from pathlib import Path
from time import time
from typing import Any

from . import PORT, __version__
from . import blackboard, dag, herdr, okbay, schedule
# desks imported lazily in snapshot to avoid cycles
from .paths import state_dir as _state_dir
from .logutil import get_logger

_log = get_logger(__name__)

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


def _dag_count(summary: dict[str, Any]) -> int:
    """Integer node count from a summary (nodes may be int or list)."""
    n = summary.get("node_count")
    if isinstance(n, int):
        return n
    nodes = summary.get("nodes")
    if isinstance(nodes, int):
        return nodes
    if isinstance(nodes, list):
        return len(nodes)
    items = summary.get("items")
    if isinstance(items, list):
        return len(items)
    return 0



def core_health() -> dict[str, Any]:
    """Shared CE / okstratr / wiki_build health block (contract C1).

    CE may be unreachable when not co-managed — report ``stopped`` with detail
    (task allows ``unknown``; we use stopped + detail for the closed enum).
    wiki_build is owned by CE; okstratr reports idle unless a local hint exists.
    """
    import urllib.error
    import urllib.request

    from . import PORT
    from .lifecycle import health_ok, is_serve_running, serve_url
    from .public_base import public_base

    # --- okstratr ---
    base = serve_url()
    pub = public_base()
    ok_url = f"{base}{pub}" if pub else base
    if health_ok():
        ok_state, ok_detail = "healthy", "GET /health ok"
    elif is_serve_running() or _port_hint():
        ok_state, ok_detail = "starting", "process/port up; /health not ready"
    else:
        ok_state, ok_detail = "stopped", "serve not running"

    # --- CE (optional co-managed) ---
    ce_url = (os.environ.get("OKSTRATR_CE_URL") or os.environ.get("CE_URL") or "http://127.0.0.1:8766").rstrip("/")
    ce_state, ce_detail = "stopped", "not co-managed / unreachable"
    try:
        with urllib.request.urlopen(ce_url + "/health", timeout=0.35) as resp:
            if 200 <= int(getattr(resp, "status", None) or resp.getcode()) < 300:
                ce_state, ce_detail = "healthy", "GET /health ok"
            else:
                ce_state, ce_detail = "unhealthy", f"HTTP {resp.status}"
    except (urllib.error.URLError, TimeoutError, OSError):
        # Distinguish "starting" only when explicitly co-managed
        if (os.environ.get("OKSTRATR_CE_URL") or os.environ.get("CE_URL") or "").strip():
            ce_state, ce_detail = "stopped", "configured CE URL unreachable"
        else:
            ce_state, ce_detail = "stopped", "unknown (not co-managed)"

    # --- wiki_build (CE-owned; optional file/env hint) ---
    wiki_state, wiki_pages, wiki_detail = "idle", None, "not co-managed by okstratr"
    hint = (os.environ.get("OKSTRATR_WIKI_BUILD") or "").strip().lower()
    if hint in ("building", "idle", "failed"):
        wiki_state = hint
        wiki_detail = f"OKSTRATR_WIKI_BUILD={hint}"
    pages_raw = os.environ.get("OKSTRATR_WIKI_PAGES")
    if pages_raw is not None and pages_raw.strip() != "":
        try:
            wiki_pages = int(pages_raw)
        except ValueError:
            wiki_pages = pages_raw

    return {
        "ce": {"state": ce_state, "url": ce_url, "detail": ce_detail},
        "okstratr": {"state": ok_state, "url": ok_url, "detail": ok_detail},
        "wiki_build": {"state": wiki_state, "pages": wiki_pages, "detail": wiki_detail},
    }


def _port_hint() -> bool:
    """True if :PORT accepts TCP (serve may still be starting)."""
    import socket

    from . import PORT

    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
            return True
    except OSError:
        return False



def snapshot() -> dict[str, Any]:
    mark_ready()
    # Prefer focused/active desk file so status.dag matches GET /api/dag.
    # Keep summary.nodes as an **int** count for dag_nodes / bar chips; list under items.
    try:
        from . import desks as desks_mod

        api = desks_mod.load_dag_for_api(None)
        items = list(api.get("items") or [])
        if isinstance(api.get("nodes"), list):
            items = list(api["nodes"])
        d = dict(api)
        d["items"] = items
        d["nodes"] = int(api.get("node_count") or len(items))
        d["node_count"] = d["nodes"]
    except Exception:  # noqa: BLE001
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
        from . import roles as roles_mod

        reg = desks_mod.default_registry()
        active = reg.active()
        focus_desk_id = reg.focus_id or reg.active_id
        effort = active.effort if active else None
        standing_full = desks_mod.default_standing_rows(reg)
        standing_list = [
            {
                "id": row.get("id"),
                "kind": row.get("kind"),
                "state": row.get("state"),
                "objective": row.get("objective") or "",
                "placeholder": bool(row.get("placeholder")),
                "schedule": row.get("schedule"),
            }
            for row in standing_full
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
            "default_kinds": list(roles_mod.DEFAULT_DESK_KINDS),
            "okbay_workspace_id": (
                active.okbay_workspace_id if active else str(okbay.active_workspace().get("id") or "")
            ),
            "thread_id": active.thread_id if active else "",
            "dag_nodes": _dag_count(d),
        }
        if active:
            labels = herdr.labels_for_desk(active)
            labels["focus_desk_id"] = focus_desk_id
    except Exception:  # noqa: BLE001
        _log.exception("status.snapshot: desk brief failed")
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
        _log.warning("status.snapshot: effort_slider failed", exc_info=True)
        effort_slider = {"value": effort, "stub": False, "bandit": True}

    web_egress = None
    try:
        from . import web_egress as web_mod

        web_egress = web_mod.status()
    except Exception:  # noqa: BLE001
        _log.warning("status.snapshot: web_egress failed", exc_info=True)
        web_egress = {"mode": "off", "label": "Off", "chip": "Web: Off", "gate": True}

    roles_config = None
    try:
        from . import roles as roles_cfg

        roles_config = roles_cfg.load_role_config()
    except Exception:  # noqa: BLE001
        _log.warning("status.snapshot: roles_config failed", exc_info=True)
        roles_config = None

    workspaces = None
    try:
        workspaces = okbay.list_workspaces()
    except Exception:  # noqa: BLE001
        _log.warning("status.snapshot: okbay workspaces failed", exc_info=True)
        workspaces = {"reachable": False, "workspaces": [], "local_fallback": True}

    if isinstance(web_egress, dict) and web_egress.get("pending_approval"):
        deny_msg = web_egress.get("message") or web_egress.get("note") or "Web egress denied — needs approval"
        msg = f"{msg} · {deny_msg}" if msg else str(deny_msg)
        web_egress = dict(web_egress)
        web_egress.setdefault("message", deny_msg)

    herdr_job = None
    herdr_error = None
    try:
        from . import herdr_jobs

        herdr_job = herdr_jobs.snapshot_for_status()
        herdr_error = herdr_jobs.last_error()
        if herdr_job and herdr_job.get("state") == "running":
            jid = herdr_job.get("id")
            prog = herdr_job.get("progress") or {}
            ran_n = prog.get("ran")
            lim = prog.get("limit") or herdr_job.get("limit")
            extra = f"Herdr job {jid} running"
            if ran_n is not None and lim is not None:
                extra = f"Herdr job {jid} running ({ran_n}/{lim})"
            msg = f"{msg} · {extra}" if msg else extra
        elif herdr_error:
            msg = f"{msg} · Herdr error: {herdr_error}" if msg else f"Herdr error: {herdr_error}"
    except Exception:  # noqa: BLE001
        _log.warning("status.snapshot: herdr_jobs failed", exc_info=True)
        herdr_job = None
        herdr_error = None


    desk_session_snap = None
    try:
        from . import desk_session as desk_session_mod

        desk_session_snap = desk_session_mod.snapshot(
            registry=None,
            dag_summary=d,
            objective=obj,
        )
    except Exception:  # noqa: BLE001
        _log.warning("status.snapshot: desk_session failed", exc_info=True)
        desk_session_snap = None

    harness_snap = None
    try:
        from .harness import config as harness_config

        harness_snap = harness_config.list_for_api()
    except Exception:  # noqa: BLE001
        _log.warning("status.snapshot: harness list failed", exc_info=True)
        harness_snap = None

    return {
        "ts": time(),
        "state": display_state,
        "objective": obj,
        "seated": bool(obj),  # compat; UI should bind desk.state not this
        "desk": desk_brief,
        "desk_kind": kind,
        "desk_state": (desk_brief or {}).get("state"),
        "dag_nodes": _dag_count(d),
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
        "okbay_workspaces": workspaces,
        "roles_config": roles_config,
        "herdr_job": herdr_job,
        "herdr_error": herdr_error,
        "ui": {
            "left_pane": "desk_switch",
            "show_dag": True,
            "show_blackboard": True,
            "text_input": True,
            "query_input": True,
            "config_roles": True,
            "close_warning": herdr.CLOSE_WARNING,
        },
        "version": __version__,
        "message": msg,
        # Phase 3: canonical DeskSession + harness allowlist (Panel/HTTP SSOT path)
        "desk_session": desk_session_snap,
        "desks": (desk_session_snap or {}).get("desks") or [],
        "standing": (desk_session_snap or {}).get("standing")
        or (desk_brief or {}).get("standing")
        or [],
        "harness": harness_snap,
        "health": core_health(),
        "status_channel": {
            "primary": "GET /api/status",
            "compat_file": str(status_path()),
            "dual_source": False,
            "mirror": _mirror_enabled(),
            "mirror_env": "OKSTRATR_STATUS_MIRROR",
            "notes": (
                "P4: DeskSession via HTTP is SSOT. status.json is a daemon "
                "write-through compat mirror for offline/stale bar chips "
                "(OKSTRATR_STATUS_MIRROR=0 skips the disk write; eventual removal still TBD); "
                "clients must not treat FileView as authoritative when HTTP is up."
            ),
        },
    }



def _mirror_enabled() -> bool:
    """Compat status.json write-through; set OKSTRATR_STATUS_MIRROR=0 to skip."""
    raw = (os.environ.get("OKSTRATR_STATUS_MIRROR") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def write_status(data: dict[str, Any] | None = None) -> dict[str, Any]:
    # Cheap reconcile: fire due schedules + auto-quiet finished desks.
    if data is None:
        try:
            from . import schedule as schedule_mod

            schedule_mod.fire_due(emit_notify=True)
        except Exception:  # noqa: BLE001
            _log.warning("write_status: schedule.fire_due failed", exc_info=True)
        try:
            from . import desks as desks_mod

            quieted = desks_mod.maybe_quiet_if_finished()
            if quieted.get("action") == "auto_quiet":
                # stop() already wrote status; rebuild snapshot
                snap = snapshot()
                if _mirror_enabled():
                    path = status_path()
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
                return snap
        except Exception:  # noqa: BLE001
            _log.warning("write_status: maybe_quiet_if_finished failed", exc_info=True)
    snap = data or snapshot()
    if _mirror_enabled():
        path = status_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    return snap
