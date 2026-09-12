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


def active_workspace() -> dict[str, Any]:
    """
    Stub: which okbay workspace the desk should bind.

    Override with OKSTRATR_OKBAY_WORKSPACE (id) and/or OKSTRATR_OKBAY_WORK_ROOT.
    Default is work-coverage (magical all-~/Work). Biocure is the demo
    workspace currently in use — set OKSTRATR_OKBAY_WORKSPACE=biocure to bind it.
    """
    raw_id = (os.environ.get("OKSTRATR_OKBAY_WORKSPACE") or "").strip().lower()
    workspace_id = raw_id or DEFAULT_WORKSPACE_ID
    root_raw = (os.environ.get("OKSTRATR_OKBAY_WORK_ROOT") or "").strip()
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
