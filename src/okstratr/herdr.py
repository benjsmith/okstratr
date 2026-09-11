"""Launch / focus native Herdr with seated objective text — stub."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any


def herdr_bin() -> str | None:
    return shutil.which("herdr") or shutil.which("omarchy-herdr")


def launch(objective: str = "", *, focus: bool = True) -> dict[str, Any]:
    """
    Best-effort: run Herdr with objective as argv / env.
    On boxes without Herdr installed, returns a dry-run payload.
    """
    obj = (objective or "").strip()
    bin_path = herdr_bin()
    env = os.environ.copy()
    if obj:
        env["OKSTRATR_OBJECTIVE"] = obj
        env["HERDR_OBJECTIVE"] = obj

    if not bin_path:
        return {
            "ok": False,
            "dry_run": True,
            "message": "Herdr not on PATH; install native Omarchy Herdr",
            "objective": obj,
            "would_exec": ["herdr", obj] if obj else ["herdr"],
        }

    cmd = [bin_path]
    if obj:
        cmd.append(obj)
    # focus flag is advisory until Herdr CLI is documented
    if focus:
        env["HERDR_FOCUS"] = "1"
    try:
        subprocess.Popen(cmd, env=env, start_new_session=True)
        return {"ok": True, "exec": cmd, "objective": obj}
    except OSError as e:
        return {"ok": False, "error": str(e), "exec": cmd, "objective": obj}
