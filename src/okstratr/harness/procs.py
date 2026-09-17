"""Track direct-CLI seat processes; kill on desk quiet/dismiss."""

from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..paths import state_dir


REGISTRY_NAME = "direct_procs.json"


@dataclass
class ProcRecord:
    pid: int
    harness_id: str
    node_id: str
    desk_id: str | None = None
    thread_id: str | None = None
    log_path: str | None = None
    started_at: float = field(default_factory=time.time)
    argv: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _registry_path() -> Path:
    return state_dir() / REGISTRY_NAME


def load_registry() -> dict[str, ProcRecord]:
    p = _registry_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, ProcRecord] = {}
    if isinstance(data, dict):
        for key, raw in data.items():
            if not isinstance(raw, dict):
                continue
            try:
                out[str(key)] = ProcRecord(
                    pid=int(raw["pid"]),
                    harness_id=str(raw.get("harness_id") or ""),
                    node_id=str(raw.get("node_id") or ""),
                    desk_id=raw.get("desk_id"),
                    thread_id=raw.get("thread_id"),
                    log_path=raw.get("log_path"),
                    started_at=float(raw.get("started_at") or time.time()),
                    argv=list(raw.get("argv") or []),
                )
            except (KeyError, TypeError, ValueError):
                continue
    return out


def save_registry(recs: dict[str, ProcRecord]) -> Path:
    p = _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v.to_dict() for k, v in recs.items()}
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def register(rec: ProcRecord) -> None:
    regs = load_registry()
    key = f"{rec.desk_id or 'nodes'}:{rec.node_id}:{rec.pid}"
    regs[key] = rec
    save_registry(regs)


def unregister_pid(pid: int) -> None:
    regs = load_registry()
    drop = [k for k, v in regs.items() if v.pid == pid]
    for k in drop:
        del regs[k]
    if drop:
        save_registry(regs)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_pid(pid: int, *, grace_sec: float = 0.5) -> dict[str, Any]:
    """SIGTERM then SIGKILL a direct seat process."""
    if not _pid_alive(pid):
        unregister_pid(pid)
        return {"ok": True, "pid": pid, "already_dead": True}
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        return {"ok": False, "pid": pid, "error": str(e)}
    deadline = time.time() + max(0.0, grace_sec)
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(0.05)
    if _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError as e:
            return {"ok": False, "pid": pid, "error": str(e), "sigterm": True}
    unregister_pid(pid)
    return {"ok": True, "pid": pid, "killed": True}


def kill_for_desk(desk_id: str | None = None, *, thread_id: str | None = None) -> dict[str, Any]:
    """Kill tracked direct seats matching desk_id and/or thread_id (or all if both None)."""
    regs = load_registry()
    killed: list[dict[str, Any]] = []
    for key, rec in list(regs.items()):
        if desk_id and rec.desk_id != desk_id:
            continue
        if thread_id and rec.thread_id != thread_id:
            continue
        # If both filters None, kill everything (desk quiet global)
        if desk_id is None and thread_id is None:
            pass
        result = kill_pid(rec.pid)
        result["key"] = key
        result["node_id"] = rec.node_id
        killed.append(result)
    return {"ok": True, "killed": killed, "count": len(killed)}


def seat_log_dir() -> Path:
    d = state_dir() / "harness_logs"
    d.mkdir(parents=True, exist_ok=True)
    return d
