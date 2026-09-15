"""Hooks to okbay (knowledge). Ingest / work-coverage live in okbay — not here.

Omarchy product = okbay (knowledge) + okstratr (orchestrator).

Work-coverage default is okbay's magical all-~/Work watch. Biocure is the
current **demo** workspace in use (not an opt-in). Optional means: create
additional focused workspaces via the split tool (subset of ~/Work subfolders
→ new wiki; those folders join the new watch list and are excluded from
default Work coverage). okstratr desks bind the active okbay workspace /
thread ids; they do not ingest files themselves.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Magical default — owned by okbay, not reimplemented here.
DEFAULT_WORK_ROOT = "~/Work"
DEFAULT_WORKSPACE_ID = "work"
# Current demo workspace in use (not opt-in / not "optional named").
DEMO_WORKSPACE_ID = "biocure"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _TRUTHY


OKBAY_API_URL = (os.environ.get("OKSTRATR_OKBAY_URL") or "http://127.0.0.1:8766").rstrip("/")
_SELECTED_WORKSPACE_NAME = "selected_workspace.json"


def selected_workspace_path() -> Path:
    from .paths import state_dir

    return state_dir() / _SELECTED_WORKSPACE_NAME


def get_selected_workspace_id() -> str:
    """Persisted UI selection under OKSTRATR_STATE_DIR (empty if unset)."""
    path = selected_workspace_path()
    if not path.is_file():
        return ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(raw, dict):
        return ""
    return str(raw.get("id") or raw.get("workspace_id") or "").strip()


def set_selected_workspace(workspace_id: str, *, path: str | None = None) -> dict[str, Any]:
    """Persist selected okbay workspace id for desk bind + panel dropdown."""
    wid = (workspace_id or "").strip()
    payload = {
        "id": wid,
        "workspace_id": wid,
        "path": (path or "").strip() or None,
        "updated_at": __import__("time").time(),
    }
    dest = selected_workspace_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(dest)
    return active_workspace()


def list_workspaces(*, timeout: float = 0.4) -> dict[str, Any]:
    """
    Fetch okbay workspace list from http://127.0.0.1:8766/api/workspace/list.

    Returns {reachable, workspaces:[{id,name,path}], active, local_fallback}.
    When okbay is down → reachable=False and a local fallback row.
    """
    import urllib.error
    import urllib.request

    url = f"{OKBAY_API_URL}/api/workspace/list"
    selected = get_selected_workspace_id()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        local = [
            {"id": "local", "name": "local", "path": "", "label": "local"},
        ]
        return {
            "ok": True,
            "reachable": False,
            "workspaces": local,
            "active": selected or "local",
            "selected": selected or "local",
            "local_fallback": True,
            "api_url": url,
        }

    named = data.get("workspaces") or {}
    items: list[dict[str, Any]] = []
    if isinstance(named, dict):
        for name, wpath in named.items():
            items.append({
                "id": str(name),
                "name": str(name),
                "path": str(wpath) if wpath is not None else "",
                "label": str(name),
            })
    elif isinstance(named, list):
        for entry in named:
            if isinstance(entry, dict):
                nid = str(entry.get("id") or entry.get("name") or "")
                if not nid:
                    continue
                items.append({
                    "id": nid,
                    "name": str(entry.get("name") or nid),
                    "path": str(entry.get("path") or ""),
                    "label": str(entry.get("name") or nid),
                })
            elif entry:
                items.append({"id": str(entry), "name": str(entry), "path": "", "label": str(entry)})

    # Ensure biocure demo surfaces even if not yet in okbay coverage cfg
    ids = {i["id"] for i in items}
    if DEMO_WORKSPACE_ID not in ids:
        items.append({
            "id": DEMO_WORKSPACE_ID,
            "name": DEMO_WORKSPACE_ID,
            "path": "~/Work/Biocure",
            "label": DEMO_WORKSPACE_ID,
            "demo": True,
        })
    if DEFAULT_WORKSPACE_ID not in ids and "okbay" not in ids:
        items.insert(0, {
            "id": DEFAULT_WORKSPACE_ID,
            "name": DEFAULT_WORKSPACE_ID,
            "path": DEFAULT_WORK_ROOT,
            "label": DEFAULT_WORKSPACE_ID,
        })

    active = str(data.get("active") or selected or DEFAULT_WORKSPACE_ID)
    return {
        "ok": True,
        "reachable": True,
        "workspaces": items,
        "active": active,
        "selected": selected or active,
        "local_fallback": False,
        "api_url": url,
        "raw_active": data.get("active"),
        "current": data.get("current"),
    }


def active_workspace() -> dict[str, Any]:
    """
    Which okbay workspace the desk should bind.

    Resolution order:
      1. Persisted UI selection (OKSTRATR_STATE_DIR/selected_workspace.json)
      2. OKSTRATR_OKBAY_WORKSPACE env
      3. Default work-coverage id

    Override path with OKSTRATR_OKBAY_WORK_ROOT. Biocure is the demo
    workspace currently in use — select it in the panel or set the env.
    """
    selected = get_selected_workspace_id()
    raw_id = (os.environ.get("OKSTRATR_OKBAY_WORKSPACE") or "").strip().lower()
    workspace_id = (selected or raw_id or DEFAULT_WORKSPACE_ID).strip().lower() or DEFAULT_WORKSPACE_ID
    # Map okbay hub name to our default id for consistency
    if workspace_id == "okbay":
        workspace_id = DEFAULT_WORKSPACE_ID
    if workspace_id == "local":
        workspace_id = DEFAULT_WORKSPACE_ID
    root_raw = (os.environ.get("OKSTRATR_OKBAY_WORK_ROOT") or "").strip()
    # Prefer path from selection file when present
    sel_path = selected_workspace_path()
    if sel_path.is_file() and not root_raw:
        try:
            sel = json.loads(sel_path.read_text(encoding="utf-8"))
            if isinstance(sel, dict) and sel.get("path"):
                root_raw = str(sel["path"]).strip()
        except (OSError, json.JSONDecodeError):
            pass
    if not root_raw:
        if workspace_id == DEMO_WORKSPACE_ID:
            root_raw = "~/Work/Biocure"
        else:
            root_raw = DEFAULT_WORK_ROOT
    thread_raw = (os.environ.get("OKSTRATR_OKBAY_THREAD_IDS") or "").strip()
    thread_ids = [t.strip() for t in thread_raw.split(",") if t.strip()]
    is_default = workspace_id == DEFAULT_WORKSPACE_ID
    is_demo = workspace_id == DEMO_WORKSPACE_ID
    return {
        "id": workspace_id,
        "workspace_id": workspace_id,
        "path": root_raw,
        "expanded_path": str(Path(root_raw).expanduser()),
        "thread_ids": thread_ids,
        "demo": is_demo,
        "focused": not is_default,
        "default_work_coverage": is_default,
        "owner": "okbay",
        "ingest": False,
        "stub": True,
        "selected": bool(selected),
        "notes": (
            "Work-coverage ingest lives in okbay (magical all-~/Work). "
            "Biocure is the current demo workspace in use, not an opt-in. "
            "Optional = split more focused workspaces (see split_workspace). "
            "okstratr only binds desk/thread ids."
        ),
    }


def split_workspace(folders: list[str] | None = None, *, name: str | None = None) -> dict[str, Any]:
    """
    Hook stub for okbay's split tool — do not ingest here.

    Smooth path: subset of ~/Work subfolders → new wiki; those folders join
    the new workspace watch list and are excluded from default Work coverage.
    """
    folders = [str(f).strip() for f in (folders or []) if str(f).strip()]
    ws_name = (name or "").strip() or (folders[0].rstrip("/").split("/")[-1] if folders else "focused")
    return {
        "ok": True,
        "stub": True,
        "owner": "okbay",
        "tool": "split",
        "name": ws_name,
        "folders": folders,
        "excluded_from_default_work": list(folders),
        "notes": (
            "okbay split: chosen ~/Work subfolders become a focused workspace "
            "wiki + watch list, and drop out of default all-~/Work coverage."
        ),
    }


def reviews_commit_path() -> dict[str, Any]:
    """
    Hook stub to okbay reviews — the land/commit path for curate desks.

    Configured when OKSTRATR_OKBAY_REVIEWS or OKSTRATR_CURATE_COMMIT is truthy,
    or OKSTRATR_OKBAY_COMMIT_PATH is a non-empty path. No ingest here.
    """
    path = (os.environ.get("OKSTRATR_OKBAY_COMMIT_PATH") or "").strip()
    configured = bool(path) or _truthy("OKSTRATR_OKBAY_REVIEWS") or _truthy(
        "OKSTRATR_CURATE_COMMIT"
    )
    return {
        "configured": configured,
        "path": path or None,
        "owner": "okbay",
        "hook": "reviews",
        "stub": True,
        "notes": (
            "Curate desks must not spawn curator_worker unless this land path "
            "is configured (Switchbay bug: token burn without commit)."
        ),
    }


def thread_ids_for_desk(desk_id: str | None = None) -> list[str]:
    """okbay thread ids the desk should label Herdr panes with (stub)."""
    ws = active_workspace()
    ids = list(ws.get("thread_ids") or [])
    if desk_id and not ids:
        ids = [f"thread-{desk_id}"]
    return ids
