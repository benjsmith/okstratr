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


def resolve_workspace_path(workspace_id: str, *, path: str | None = None) -> str:
    """Resolve a filesystem path for a workspace id (explicit path wins)."""
    explicit = (path or "").strip()
    if explicit:
        return str(Path(explicit).expanduser())
    wid = (workspace_id or "").strip()
    if not wid or wid in ("local",):
        return ""
    pack = list_workspaces()
    for row in pack.get("workspaces") or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or row.get("name") or "")
        if rid == wid and row.get("path"):
            return str(Path(str(row["path"]).strip()).expanduser())
    # Fallbacks used by active_workspace()
    if wid == DEMO_WORKSPACE_ID:
        return str(Path("~/Work/Biocure").expanduser())
    if wid in (DEFAULT_WORKSPACE_ID, "okbay"):
        return str(Path(DEFAULT_WORK_ROOT).expanduser())
    return ""


def activate_remote_workspace(workspace_id: str, *, timeout: float = 0.8) -> dict[str, Any]:
    """Ask okbay to switch active workspace (POST /api/workspace/use)."""
    import urllib.error
    import urllib.request

    wid = (workspace_id or "").strip()
    if not wid or wid in ("local",):
        return {"ok": True, "skipped": True, "reason": "local-or-empty"}
    # Map okstratr default id → okbay hub name
    remote_name = "okbay" if wid == DEFAULT_WORKSPACE_ID else wid
    url = f"{OKBAY_API_URL}/api/workspace/use"
    body = json.dumps({"name": remote_name, "workspace": remote_name}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
        if isinstance(data, dict):
            data.setdefault("ok", True)
            data["api_url"] = url
            return data
        return {"ok": True, "raw": data, "api_url": url}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as e:
        return {
            "ok": False,
            "reachable": False,
            "error": str(e),
            "api_url": url,
            "workspace_id": wid,
        }


def apply_workspace_selection(
    workspace_id: str, *, path: str | None = None, set_operating_cwd: bool = True
) -> dict[str, Any]:
    """Select okbay workspace, optionally set okstratr operating cwd, activate remote.

    This is the path the observer workspace-switcher must take so the displayed
    lifecycle cwd updates immediately after a switch.
    """
    wid = (workspace_id or "").strip() or "local"
    resolved = resolve_workspace_path(wid, path=path)
    selected = set_selected_workspace(wid, path=resolved or path)

    cwd_result: dict[str, Any] | None = None
    if set_operating_cwd and resolved:
        p = Path(resolved).expanduser()
        if p.is_dir():
            from . import workspace as ws_mod

            cwd_result = ws_mod.set_cwd(p)
        else:
            cwd_result = {"ok": False, "error": f"path does not exist: {p}", "cwd": None}
    elif set_operating_cwd and wid == "local":
        cwd_result = {"ok": True, "skipped": True, "reason": "local"}

    remote = activate_remote_workspace(wid)
    from . import workspace as ws_mod

    return {
        "ok": True,
        "workspace_id": wid,
        "path": resolved or None,
        "okbay": selected,
        "cwd": cwd_result,
        "operating_cwd": ws_mod.get_cwd(),
        "activate": remote,
        "workspaces": list_workspaces(),
    }


def _workspace_label(name: str, path: str = "", *, local: bool = False) -> str:
    """Human label for workspace dropdowns (name + path; local = serve cwd)."""
    n = (name or "").strip() or ("local" if local else "")
    p = (path or "").strip()
    if local or n in ("local",):
        return f"local (serve cwd) — {p}" if p else "local (serve cwd)"
    if p:
        return f"{n} — {p}"
    return n or p or "workspace"


def _local_workspace_row() -> dict[str, Any]:
    cwd = ""
    try:
        from . import workspace as ws_mod

        cwd = str(ws_mod.get_cwd() or "").strip()
    except Exception:
        cwd = ""
    return {
        "id": "local",
        "name": "local",
        "path": cwd,
        "label": _workspace_label("local", cwd, local=True),
        "source": "local",
    }


def switchbay_workspaces_path() -> Path:
    override = (os.environ.get("OKSTRATR_SWITCHBAY_WORKSPACES") or "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "switchbay" / "workspaces.json"


def _rows_from_path_list(
    paths: list[str], *, source: str, active: str = ""
) -> tuple[list[dict[str, Any]], str]:
    """Build workspace rows from absolute/relative directory paths."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    active_id = ""
    active_norm = str(Path(active).expanduser()) if active else ""
    for raw in paths:
        p = str(Path(str(raw)).expanduser())
        if not p or p in seen:
            continue
        seen.add(p)
        name = Path(p).name or p
        # Prefer unique id = basename; collide → full path slug
        wid = name
        if any(i["id"] == wid for i in items):
            wid = p.replace("/", "_").lstrip("_")
        row = {
            "id": wid,
            "name": name,
            "path": p,
            "label": _workspace_label(name, p),
            "source": source,
        }
        items.append(row)
        if active_norm and str(Path(p)) == active_norm:
            active_id = wid
    return items, active_id


def list_switchbay_workspaces(*, timeout: float = 0.3) -> dict[str, Any]:
    """Registered Switchbay workspaces (HTTP :8765 or ~/.config/switchbay/workspaces.json)."""
    import urllib.error
    import urllib.request

    base = (os.environ.get("OKSTRATR_SWITCHBAY_URL") or "http://127.0.0.1:8765").rstrip("/")
    url = f"{base}/api/workspaces"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("paths"), list):
            paths = [str(p) for p in data["paths"] if p]
            items, active_id = _rows_from_path_list(
                paths, source="switchbay", active=str(data.get("active") or "")
            )
            return {
                "ok": True,
                "reachable": True,
                "source": "switchbay-http",
                "workspaces": items,
                "active": active_id or str(data.get("active") or ""),
                "api_url": url,
            }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        pass

    cfg = switchbay_workspaces_path()
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict) and isinstance(data.get("paths"), list):
            paths = [str(p) for p in data["paths"] if p]
            items, active_id = _rows_from_path_list(
                paths, source="switchbay", active=str(data.get("active") or "")
            )
            return {
                "ok": True,
                "reachable": True,
                "source": "switchbay-file",
                "workspaces": items,
                "active": active_id or str(data.get("active") or ""),
                "path": str(cfg),
            }
    return {
        "ok": True,
        "reachable": False,
        "source": "switchbay",
        "workspaces": [],
        "active": "",
    }


def _enrich_workspace_labels(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        nid = str(row.get("id") or row.get("name") or "")
        name = str(row.get("name") or nid)
        path = str(row.get("path") or "")
        local = nid == "local" or bool(row.get("local"))
        label = str(row.get("label") or "").strip()
        if not label or label == name or label == nid or (local and "serve cwd" not in label):
            label = _workspace_label(name, path, local=local)
        enriched = dict(row)
        enriched["id"] = nid
        enriched["name"] = name
        enriched["path"] = path
        enriched["label"] = label
        out.append(enriched)
    return out


def _merge_workspace_rows(
    primary: list[dict[str, Any]], extra: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge by id then by path; primary wins on id collision."""
    out = _enrich_workspace_labels(primary)
    seen_ids = {str(i.get("id") or "") for i in out}
    seen_paths = {str(i.get("path") or "") for i in out if i.get("path")}
    for row in _enrich_workspace_labels(extra):
        rid = str(row.get("id") or "")
        rpath = str(row.get("path") or "")
        if rid and rid in seen_ids:
            continue
        if rpath and rpath in seen_paths:
            continue
        out.append(row)
        if rid:
            seen_ids.add(rid)
        if rpath:
            seen_paths.add(rpath)
    return out


def list_workspaces(*, timeout: float = 0.4) -> dict[str, Any]:
    """
    Fetch okbay workspace list from http://127.0.0.1:8766/api/workspace/list.

    Returns {reachable, workspaces:[{id,name,path,label}], active, local_fallback}.
    When okbay is down → Switchbay registered workspaces (HTTP or config file)
    plus a clearly labeled ``local (serve cwd)`` fallback row.
    """
    import urllib.error
    import urllib.request

    url = f"{OKBAY_API_URL}/api/workspace/list"
    selected = get_selected_workspace_id()
    sy = list_switchbay_workspaces(timeout=min(timeout, 0.35))
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        items = list(sy.get("workspaces") or [])
        items = _merge_workspace_rows(items, [_local_workspace_row()])
        active = selected or str(sy.get("active") or "") or "local"
        return {
            "ok": True,
            "reachable": False,
            "workspaces": _enrich_workspace_labels(items),
            "active": active,
            "selected": selected or active,
            "local_fallback": True,
            "api_url": url,
            "switchbay": {
                "reachable": bool(sy.get("reachable")),
                "source": sy.get("source"),
                "count": len(sy.get("workspaces") or []),
            },
        }

    named = data.get("workspaces") or {}
    items: list[dict[str, Any]] = []
    if isinstance(named, dict):
        for name, wpath in named.items():
            p = str(wpath) if wpath is not None else ""
            items.append({
                "id": str(name),
                "name": str(name),
                "path": p,
                "label": _workspace_label(str(name), p),
                "source": "okbay",
            })
    elif isinstance(named, list):
        for entry in named:
            if isinstance(entry, dict):
                nid = str(entry.get("id") or entry.get("name") or "")
                if not nid:
                    continue
                name = str(entry.get("name") or nid)
                p = str(entry.get("path") or "")
                items.append({
                    "id": nid,
                    "name": name,
                    "path": p,
                    "label": _workspace_label(name, p, local=(nid == "local")),
                    "source": "okbay",
                })
            elif entry:
                items.append({
                    "id": str(entry),
                    "name": str(entry),
                    "path": "",
                    "label": _workspace_label(str(entry)),
                    "source": "okbay",
                })

    # Ensure biocure demo surfaces even if not yet in okbay coverage cfg
    ids = {i["id"] for i in items}
    if DEMO_WORKSPACE_ID not in ids:
        items.append({
            "id": DEMO_WORKSPACE_ID,
            "name": DEMO_WORKSPACE_ID,
            "path": "~/Work/Biocure",
            "label": _workspace_label(DEMO_WORKSPACE_ID, "~/Work/Biocure"),
            "demo": True,
            "source": "okbay",
        })
    if DEFAULT_WORKSPACE_ID not in ids and "okbay" not in ids:
        items.insert(0, {
            "id": DEFAULT_WORKSPACE_ID,
            "name": DEFAULT_WORKSPACE_ID,
            "path": DEFAULT_WORK_ROOT,
            "label": _workspace_label(DEFAULT_WORKSPACE_ID, DEFAULT_WORK_ROOT),
            "source": "okbay",
        })

    # Merge Switchbay registered dirs so Agents embed sees vaults even when
    # okbay list is sparse / demo-only.
    items = _merge_workspace_rows(items, list(sy.get("workspaces") or []))
    # Always keep a clear local (serve cwd) option at the end.
    items = _merge_workspace_rows(items, [_local_workspace_row()])

    active = str(data.get("active") or selected or sy.get("active") or DEFAULT_WORKSPACE_ID)
    return {
        "ok": True,
        "reachable": True,
        "workspaces": _enrich_workspace_labels(items),
        "active": active,
        "selected": selected or active,
        "local_fallback": False,
        "api_url": url,
        "raw_active": data.get("active"),
        "current": data.get("current"),
        "switchbay": {
            "reachable": bool(sy.get("reachable")),
            "source": sy.get("source"),
            "count": len(sy.get("workspaces") or []),
        },
    }


def active_workspace() -> dict[str, Any]:
    """
    Which okbay workspace the desk should bind.

    Uses the same rule as the read-only Context label
    (:func:`resolve_host_workspace`), so the bound desk and the label always
    name the same workspace:

      1. The host's active workspace (Switchbay or okbay), when hosted
      2. The workspace chosen through the select API or CLI
         (OKSTRATR_STATE_DIR/selected_workspace.json)
      3. OKSTRATR_WORKSPACE / OKSTRATR_OKBAY_WORKSPACE
      4. The registered workspace containing the working directory
      5. The default all-Work workspace

    OKSTRATR_OKBAY_WORK_ROOT overrides the path.
    """
    selected = get_selected_workspace_id()
    try:
        resolved = resolve_host_workspace()
    except Exception:  # noqa: BLE001
        resolved = {}
    workspace_id = str(resolved.get("id") or DEFAULT_WORKSPACE_ID).strip().lower() or DEFAULT_WORKSPACE_ID
    if workspace_id in ("okbay", "local"):
        workspace_id = DEFAULT_WORKSPACE_ID
    root_raw = (os.environ.get("OKSTRATR_OKBAY_WORK_ROOT") or "").strip()
    if not root_raw and workspace_id != DEFAULT_WORKSPACE_ID:
        root_raw = str(resolved.get("path") or "").strip()
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
        "selected": bool(selected) and resolved.get("resolution") == "selected",
        "resolution": resolved.get("resolution") or "default-work",
        "notes": (
            "Work-coverage ingest lives in okbay (magical all-~/Work). "
            "Biocure is the current demo workspace in use, not an opt-in. "
            "Optional = split more focused workspaces (see split_workspace). "
            "okstratr only binds desk/thread ids."
        ),
    }



def _env_workspace_hint() -> str:
    """Explicit workspace path or id from OKSTRATR_WORKSPACE / OKSTRATR_OKBAY_WORKSPACE."""
    for key in ("OKSTRATR_WORKSPACE", "OKSTRATR_OKBAY_WORKSPACE"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return raw
    return ""


def _row_from_path_or_id(hint: str, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build a workspace row from an absolute path or known id."""
    hint = (hint or "").strip()
    items = list(rows or [])
    if not hint:
        return {}
    # Match id/name first
    for row in items:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or row.get("name") or "")
        if rid and rid == hint:
            return dict(row)
    # Path-like hint
    try:
        p = Path(hint).expanduser()
        if p.exists() or "/" in hint or hint.startswith("~"):
            resolved = str(p.resolve()) if p.exists() else str(p.expanduser())
            name = Path(resolved).name or hint
            for row in items:
                if not isinstance(row, dict):
                    continue
                rpath = str(row.get("path") or "").strip()
                if not rpath:
                    continue
                try:
                    if str(Path(rpath).expanduser().resolve()) == str(Path(resolved).expanduser().resolve()):
                        return dict(row)
                except OSError:
                    if rpath == resolved or rpath == hint:
                        return dict(row)
            return {
                "id": name,
                "name": name,
                "path": resolved,
                "label": _workspace_label(name, resolved),
                "source": "env",
            }
    except OSError:
        pass
    return {
        "id": hint,
        "name": hint,
        "path": "",
        "label": _workspace_label(hint),
        "source": "env",
    }


def _selection_row(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Row for the workspace chosen through the select API or CLI (empty if none)."""
    wid = get_selected_workspace_id()
    if not wid:
        return {}
    path = ""
    try:
        raw = json.loads(selected_workspace_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            path = str(raw.get("path") or "").strip()
    except (OSError, json.JSONDecodeError):
        path = ""
    for row in rows or []:
        if isinstance(row, dict) and str(row.get("id") or row.get("name") or "") == wid:
            out = dict(row)
            if path:
                out["path"] = path
            return out
    return {
        "id": wid,
        "name": wid,
        "path": path,
        "label": _workspace_label(wid, path) if path else _workspace_label(wid),
        "source": "selected",
    }


def _nearest_workspace_row(cwd: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Map seat cwd to the nearest registered workspace root (longest prefix win)."""
    if not cwd:
        return None
    try:
        cwd_p = Path(cwd).expanduser().resolve()
    except OSError:
        return None
    best: dict[str, Any] | None = None
    best_len = -1
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or row.get("name") or "")
        if rid == "local" or str(row.get("source") or "") == "local":
            continue
        raw = str(row.get("path") or "").strip()
        if not raw:
            continue
        try:
            root = Path(raw).expanduser().resolve()
        except OSError:
            continue
        try:
            cwd_p.relative_to(root)
        except ValueError:
            continue
        n = len(str(root))
        if n > best_len:
            best_len = n
            best = dict(row)
    return best


def _default_work_row() -> dict[str, Any]:
    path = str(Path(DEFAULT_WORK_ROOT).expanduser())
    return {
        "id": DEFAULT_WORKSPACE_ID,
        "name": DEFAULT_WORKSPACE_ID,
        "path": DEFAULT_WORK_ROOT,
        "expanded_path": path,
        "label": _workspace_label(DEFAULT_WORKSPACE_ID, DEFAULT_WORK_ROOT),
        "source": "default",
    }


def context_workspace_display(row: dict[str, Any] | None) -> str:
    """Short read-only label, e.g. ``biocure-membership (Biotech)`` or ``work``."""
    if not row:
        return "work"
    title = str(row.get("title") or row.get("display_name") or "").strip()
    name = str(row.get("name") or row.get("id") or "").strip()
    path = str(row.get("path") or row.get("expanded_path") or "").strip()
    if not name and path:
        name = Path(path).expanduser().name or path
    if not name:
        name = "work"
    # Drop long hash suffixes from directory basenames when no title.
    if not title and "-" in name:
        parts = name.rsplit("-", 1)
        if len(parts) == 2 and len(parts[1]) >= 7 and all(c in "0123456789abcdef" for c in parts[1].lower()):
            name = parts[0]
    if title and title != name:
        return f"{name} ({title})"
    return name


def resolve_host_workspace(*, timeout: float = 0.4) -> dict[str, Any]:
    """Resolve the host's currently active workspace (no UI picker).

    * **Switchbay** (``OKSTRATR_HOSTED``/``OKSTRATR_HOST=switchbay``): live active
      from Switchbay ``GET /api/workspaces`` (or ``~/.config/switchbay/workspaces.json``).
      Spawn-time ``OKSTRATR_WORKSPACE`` is a seed when Switchbay is unreachable.
      When Switchbay's active path changes, this follows on the next resolve.
    * **okbay** host: okbay list API ``active`` / ``current`` when reachable;
      otherwise same fallbacks as bare CLI.
    * **Bare CLI / Herdr**: ``OKSTRATR_WORKSPACE`` (or ``--workspace`` → that env),
      else seat cwd mapped to the nearest registered workspace, else default
      all-Work workspace (``work`` / ``~/Work``).

    Returns a row dict with ``id``, ``name``, ``path``, ``label``, ``display``,
    ``source``, ``host``, and ``resolution`` explaining which rule won.
    """
    from .public_base import hosted_shell_from_env

    host = hosted_shell_from_env() or ""
    hint = _env_workspace_hint()
    sy = list_switchbay_workspaces(timeout=min(timeout, 0.35))
    sy_rows = list(sy.get("workspaces") or [])
    sy_active = str(sy.get("active") or "").strip()

    cwd = ""
    try:
        from . import workspace as ws_mod

        cwd = str(ws_mod.get_cwd() or "").strip()
    except Exception:  # noqa: BLE001
        cwd = ""

    def _finish(row: dict[str, Any], *, resolution: str, host_name: str) -> dict[str, Any]:
        out = dict(row)
        out.setdefault("id", str(out.get("name") or "work"))
        out.setdefault("name", str(out.get("id") or "work"))
        path = str(out.get("path") or out.get("expanded_path") or "").strip()
        if path and not out.get("expanded_path"):
            try:
                out["expanded_path"] = str(Path(path).expanduser())
            except OSError:
                out["expanded_path"] = path
        out["label"] = str(out.get("label") or _workspace_label(out["name"], path))
        out["display"] = context_workspace_display(out)
        out["host"] = host_name
        out["resolution"] = resolution
        out["ok"] = True
        return out

    # --- Switchbay hosted ---
    if host == "switchbay":
        if sy_active:
            row = next((r for r in sy_rows if str(r.get("id") or "") == sy_active), None)
            if row is None and sy_active:
                row = _row_from_path_or_id(sy_active, sy_rows)
            if row:
                return _finish(row, resolution="switchbay-active", host_name="switchbay")
        picked = _selection_row(sy_rows)
        if picked:
            return _finish(picked, resolution="selected", host_name="switchbay")
        if hint:
            return _finish(
                _row_from_path_or_id(hint, sy_rows),
                resolution="OKSTRATR_WORKSPACE",
                host_name="switchbay",
            )
        nearest = _nearest_workspace_row(cwd, sy_rows)
        if nearest:
            return _finish(nearest, resolution="cwd-nearest", host_name="switchbay")
        return _finish(_default_work_row(), resolution="default-work", host_name="switchbay")

    # --- okbay hosted ---
    if host == "okbay":
        pack = list_workspaces(timeout=timeout)
        items = list(pack.get("workspaces") or [])
        active = str(pack.get("raw_active") or pack.get("active") or "").strip()
        current = pack.get("current")
        if isinstance(current, dict):
            cid = str(current.get("id") or current.get("name") or "").strip()
            if cid:
                active = active or cid
        if active:
            row = next(
                (r for r in items if str(r.get("id") or r.get("name") or "") == active),
                None,
            )
            if row is None:
                row = _row_from_path_or_id(active, items)
            if row and str(row.get("id") or "") != "local":
                return _finish(row, resolution="okbay-active", host_name="okbay")
        # Fall through like CLI when okbay active is unknown
        host_name = "okbay"
    else:
        host_name = host or "cli"
        pack = list_workspaces(timeout=timeout)
        items = list(pack.get("workspaces") or [])

    # Merge switchbay rows for cwd nearest matching on bare hosts
    items = _merge_workspace_rows(list(items), sy_rows)

    picked = _selection_row(items)
    if picked:
        return _finish(picked, resolution="selected", host_name=host_name)
    if hint:
        return _finish(
            _row_from_path_or_id(hint, items),
            resolution="OKSTRATR_WORKSPACE",
            host_name=host_name,
        )
    nearest = _nearest_workspace_row(cwd, items)
    if nearest:
        return _finish(nearest, resolution="cwd-nearest", host_name=host_name)
    return _finish(_default_work_row(), resolution="default-work", host_name=host_name)


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
    Hook to okbay reviews — the land/commit path for curate desks.

    Configured when OKSTRATR_OKBAY_REVIEWS or OKSTRATR_CURATE_COMMIT is truthy,
    or OKSTRATR_OKBAY_COMMIT_PATH points at an existing writable path (file or
    directory). Still a hook (no ingest / no commit execution here).
    """
    path = (os.environ.get("OKSTRATR_OKBAY_COMMIT_PATH") or "").strip()
    path_ok = False
    path_writable = False
    if path:
        p = Path(path).expanduser()
        try:
            if p.exists():
                path_ok = True
                if p.is_dir():
                    path_writable = os.access(p, os.W_OK)
                else:
                    path_writable = os.access(p, os.W_OK)
            else:
                # Parent writable → treat as configurable land target
                parent = p.parent
                path_writable = parent.is_dir() and os.access(parent, os.W_OK)
                path_ok = path_writable
        except OSError:
            path_ok = False
            path_writable = False
    flag = _truthy("OKSTRATR_OKBAY_REVIEWS") or _truthy("OKSTRATR_CURATE_COMMIT")
    configured = bool(flag) or (bool(path) and path_ok and path_writable)
    return {
        "configured": configured,
        "path": path or None,
        "path_exists": path_ok,
        "path_writable": path_writable,
        "owner": "okbay",
        "hook": "reviews",
        "stub": not configured,
        "notes": (
            "Curate desks must not spawn curator_worker unless this land path "
            "is configured (Switchbay bug: token burn without commit)."
        ),
    }


def thread_ids_for_desk(desk_id: str | None = None) -> list[str]:
    """okbay thread ids the desk should label Herdr panes with.

    Prefers OKSTRATR_OKBAY_THREAD_IDS, then persisted remember_desk_thread map,
    then ``thread-{desk_id}``.
    """
    ws = active_workspace()
    ids = list(ws.get("thread_ids") or [])
    if desk_id:
        remembered = list_remembered_threads().get("threads") or {}
        tid = remembered.get(str(desk_id))
        if tid and tid not in ids:
            ids = [tid] + ids
        if not ids:
            ids = [f"thread-{desk_id}"]
    return ids


_THREAD_LIST_NAME = "okbay_threads.json"


def _thread_list_path() -> Path:
    from .paths import state_dir

    return state_dir() / _THREAD_LIST_NAME


def remember_desk_thread(desk_id: str, thread_id: str) -> dict[str, Any]:
    """Persist desk→thread_id mapping for Herdr labels (okbay workspace stub)."""
    did = (desk_id or "").strip()
    tid = (thread_id or "").strip()
    if not did or not tid:
        return {"ok": False, "error": "desk_id and thread_id required"}
    path = _thread_list_path()
    data: dict[str, Any] = {"threads": {}, "order": []}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data["threads"] = dict(raw.get("threads") or {})
                data["order"] = list(raw.get("order") or [])
        except (OSError, json.JSONDecodeError):
            pass
    data["threads"][did] = tid
    if did in data["order"]:
        data["order"] = [x for x in data["order"] if x != did]
    data["order"].append(did)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "desk_id": did, "thread_id": tid, "count": len(data["threads"])}


def list_remembered_threads() -> dict[str, Any]:
    """Return persisted desk thread ids (stub list for status / Herdr labels)."""
    path = _thread_list_path()
    if not path.is_file():
        return {"ok": True, "threads": {}, "order": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": True, "threads": {}, "order": []}
    if not isinstance(raw, dict):
        return {"ok": True, "threads": {}, "order": []}
    return {
        "ok": True,
        "threads": dict(raw.get("threads") or {}),
        "order": list(raw.get("order") or []),
    }
