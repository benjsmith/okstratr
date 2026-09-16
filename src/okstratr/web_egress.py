"""Web egress gate: all network search goes through authorize / request_web.

States: ``off`` (default) | ``once`` (single search then off) | ``session``
(until revoke / desk stop / dismiss). No network calls happen here — callers
must check authorize before any egress.
"""

from __future__ import annotations

import json
from pathlib import Path
from time import time
from typing import Any

from .paths import state_dir

VALID_MODES = frozenset({"off", "once", "session"})
STATE_NAME = "web_egress.json"

_CACHE: dict[str, Any] | None = None
_CACHE_PATH: Path | None = None


def _path() -> Path:
    return state_dir() / STATE_NAME


def _default_state() -> dict[str, Any]:
    return {
        "mode": "off",
        "updated_at": time(),
        "last_authorize": None,
        "last_deny": None,
        "searches_allowed": 0,
        "pending_approval": False,
        "pending_query": None,
    }


def _load(*, force: bool = False) -> dict[str, Any]:
    global _CACHE, _CACHE_PATH
    path = _path()
    if not force and _CACHE is not None and _CACHE_PATH == path:
        return _CACHE
    data = _default_state()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                mode = str(raw.get("mode") or "off").lower()
                if mode not in VALID_MODES:
                    mode = "off"
                data.update({k: raw.get(k, data.get(k)) for k in data})
                data["mode"] = mode
        except (OSError, json.JSONDecodeError):
            pass
    _CACHE = data
    _CACHE_PATH = path
    return data


def _save(data: dict[str, Any]) -> dict[str, Any]:
    global _CACHE, _CACHE_PATH
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["updated_at"] = time()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    _CACHE = data
    _CACHE_PATH = path
    return data


def reset_cache() -> None:
    """Test helper: drop in-memory cache."""
    global _CACHE, _CACHE_PATH
    _CACHE = None
    _CACHE_PATH = None


def status() -> dict[str, Any]:
    """Public status for CLI / HTTP / status.json (QML binds ``status.web_egress``)."""
    data = _load()
    mode = data.get("mode") or "off"
    label = {"off": "Off", "once": "Once", "session": "Session"}.get(mode, "Off")
    pending = bool(data.get("pending_approval"))
    message = None
    if pending:
        q = data.get("pending_query")
        message = (
            f"Web egress denied — needs approval"
            + (f": {q}" if q else "")
        )
    elif mode == "off":
        message = "Web egress off — approve with okstratr web on --once|--session"
    return {
        "mode": mode,
        "label": label,
        "chip": f"Web: {label}",
        "allowed": mode in ("once", "session"),
        "pending_approval": pending,
        "pending_query": data.get("pending_query"),
        "searches_allowed": int(data.get("searches_allowed") or 0),
        "updated_at": data.get("updated_at"),
        "last_authorize": data.get("last_authorize"),
        "last_deny": data.get("last_deny"),
        "gate": True,
        "message": message,
        "note": "All web egress goes through web_egress.authorize / request_web",
    }


def set_mode(mode: str) -> dict[str, Any]:
    """Set gate mode: off | once | session."""
    m = (mode or "off").strip().lower()
    if m in ("on", "enable"):
        # Interactive callers should choose once|session; default session when bare "on"
        m = "session"
    if m == "search":
        m = "off"
    if m not in VALID_MODES:
        return {"ok": False, "error": f"invalid web mode: {mode!r}; expected off|once|session"}
    data = _load(force=True)
    data["mode"] = m
    if m == "off":
        data["pending_approval"] = False
        data["pending_query"] = None
    data = _save(data)
    out = status()
    out["ok"] = True
    out["action"] = m
    return out


def revoke() -> dict[str, Any]:
    """Force off (CLI ``web off`` / desk stop / dismiss)."""
    return set_mode("off")


def authorize(*, consume_once: bool = True) -> dict[str, Any]:
    """
    Check whether a web search is allowed.

    - ``off`` → denied (needs_approval)
    - ``once`` → allowed once, then auto-off when consume_once
    - ``session`` → allowed until revoke
    """
    data = _load(force=True)
    mode = data.get("mode") or "off"
    now = time()
    if mode == "off":
        data["last_deny"] = now
        data["pending_approval"] = True
        _save(data)
        return {
            "ok": False,
            "allowed": False,
            "needs_approval": True,
            "mode": "off",
            "message": "Web egress off — approve with okstratr web on --once|--session",
        }
    if mode == "once":
        data["searches_allowed"] = int(data.get("searches_allowed") or 0) + 1
        data["last_authorize"] = now
        data["pending_approval"] = False
        data["pending_query"] = None
        if consume_once:
            data["mode"] = "off"
        _save(data)
        return {
            "ok": True,
            "allowed": True,
            "needs_approval": False,
            "mode": "once",
            "consumed": bool(consume_once),
            "message": "Web egress once — consumed; now off" if consume_once else "Web egress once",
        }
    # session
    data["searches_allowed"] = int(data.get("searches_allowed") or 0) + 1
    data["last_authorize"] = now
    data["pending_approval"] = False
    data["pending_query"] = None
    _save(data)
    return {
        "ok": True,
        "allowed": True,
        "needs_approval": False,
        "mode": "session",
        "message": "Web egress session active",
    }


def request_web(
    query: str | None = None,
    *,
    author: str = "researcher",
    post_blackboard: bool = True,
) -> dict[str, Any]:
    """
    Researcher / web tool entry: authorize or return needs_approval (no network).

    When denied, posts a blackboard note so CoS/UI can surface approval.
    """
    q = (query or "").strip() or None
    auth = authorize()
    if auth.get("allowed"):
        return {
            "ok": True,
            "allowed": True,
            "needs_approval": False,
            "query": q,
            "mode": auth.get("mode"),
            "network": False,  # gate never performs network; caller may after approve
            "message": auth.get("message"),
            "authorize": auth,
        }

    data = _load(force=True)
    data["pending_approval"] = True
    data["pending_query"] = q
    data["last_deny"] = time()
    _save(data)

    note_id = None
    if post_blackboard:
        try:
            from . import blackboard

            text = "Web search needs approval"
            if q:
                text = f"Web search needs approval: {q[:200]}"
            note = blackboard.post(
                text,
                author=author,
                kind="decision",
                tags=["web_egress", "needs_approval"],
                provenance="okstratr.web_egress.request_web",
            )
            note_id = note.get("id")
        except Exception:  # noqa: BLE001
            note_id = None

    try:
        from . import status as status_mod

        status_mod.write_status()
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": False,
        "allowed": False,
        "needs_approval": True,
        "query": q,
        "mode": "off",
        "network": False,
        "blackboard_note_id": note_id,
        "message": "Web egress denied — needs_approval",
        "authorize": auth,
        "status": status(),
    }


def on_desk_stop_or_dismiss() -> dict[str, Any] | None:
    """Revoke session (and once) on desk stop/dismiss per design."""
    data = _load(force=True)
    if data.get("mode") in ("session", "once"):
        return revoke()
    return None
