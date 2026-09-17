"""Operating workspace directory for seats + TUI `/cd`.

Seats MUST run inside a strict sandbox rooted at the operating directory:
chdir into the resolved path; reject path escapes (symlinks that leave the
root, `..` resolution outside root). Documented policy:

* Default root: process cwd at first `get_cwd()` (or `$OKSTRATR_CWD` if set).
* Persisted under state_dir()/workspace.json.
* Seats receive `cwd=get_cwd()` and should not receive paths outside the root.
* Network egress is orthogonal (see web_egress) — deny-by-default.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .paths import state_dir

STATE_NAME = "workspace.json"
SANDBOX_POLICY = (
    "strict-root: seats chdir into operating dir; path resolution must stay "
    "inside the realpath of that dir (no .. escapes, no symlink escape). "
    "Network deny-by-default via web_egress."
)


def _path() -> Path:
    return state_dir() / STATE_NAME


def _default_cwd() -> str:
    env = (os.environ.get("OKSTRATR_CWD") or "").strip()
    if env:
        return str(Path(env).expanduser().resolve())
    return str(Path.cwd().resolve())


def get_cwd() -> str:
    """Return the current operating directory (absolute)."""
    path = _path()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cwd = str(raw.get("cwd") or "").strip()
                if cwd:
                    p = Path(cwd).expanduser()
                    if p.is_dir():
                        return str(p.resolve())
        except (OSError, json.JSONDecodeError):
            pass
    return _default_cwd()


def set_cwd(path: str | Path) -> dict[str, Any]:
    """Set operating directory. Must exist and be a directory."""
    p = Path(str(path)).expanduser()
    if not p.exists():
        return {"ok": False, "error": f"path does not exist: {p}", "cwd": get_cwd()}
    if not p.is_dir():
        return {"ok": False, "error": f"not a directory: {p}", "cwd": get_cwd()}
    resolved = str(p.resolve())
    payload = {
        "cwd": resolved,
        "sandbox": "strict-root",
        "policy": SANDBOX_POLICY,
    }
    dest = _path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(dest)
    os.environ["OKSTRATR_CWD"] = resolved
    return {"ok": True, **payload}


def status() -> dict[str, Any]:
    cwd = get_cwd()
    return {
        "cwd": cwd,
        "sandbox": "strict-root",
        "policy": SANDBOX_POLICY,
        "env": "OKSTRATR_CWD",
    }


def resolve_in_sandbox(path: str | Path, *, root: str | None = None) -> dict[str, Any]:
    """Resolve *path* under sandbox root; reject escapes.

    Relative paths are resolved against the operating cwd. Absolute paths must
    still lie under the sandbox root after realpath.
    """
    root_s = str(Path(root or get_cwd()).resolve())
    root_p = Path(root_s)
    raw = Path(str(path)).expanduser()
    candidate = raw if raw.is_absolute() else (root_p / raw)
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as e:
        return {"ok": False, "error": f"resolve failed: {e}", "root": root_s}
    try:
        resolved.relative_to(root_p)
    except ValueError:
        return {
            "ok": False,
            "error": f"path escapes sandbox root {root_s}: {resolved}",
            "root": root_s,
            "path": str(resolved),
        }
    return {"ok": True, "path": str(resolved), "root": root_s}


def seat_cwd() -> str:
    """cwd to hand to Herdr/direct seats (always absolute sandbox root)."""
    return get_cwd()
