"""Direct CLI harness adapter — spawn real subprocesses when Herdr is absent."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from . import argv as argv_mod
from . import procs
from .types import SeatRequest, SeatResult



def _seat_workdir_and_web() -> tuple[str, bool]:
    """Operating cwd + whether to pass --disable-web-search (web egress off)."""
    try:
        from okstratr.workspace import seat_cwd

        workdir = seat_cwd()
    except Exception:  # noqa: BLE001
        workdir = os.getcwd()
    disable_web = True
    try:
        from okstratr import web_egress

        mode = str((web_egress.status() or {}).get("mode") or "off").lower()
        disable_web = mode == "off"
    except Exception:  # noqa: BLE001
        disable_web = True
    return workdir, disable_web


def run_direct_stub(
    req: SeatRequest,
    seat: SeatResult,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Dry-run: record what a subprocess adapter would do; do not exec."""
    if not seat.ok:
        return {
            "ok": False,
            "adapter": "direct",
            "dry_run": dry_run,
            "error": seat.error or "harness selection failed",
            "seat": seat.to_dict(),
        }
    prompt = req.objective or req.node_id
    seat_workdir, disable_web = _seat_workdir_and_web()
    try:
        would_argv = argv_mod.build_argv(
            seat.harness_id or "?",
            prompt=prompt,
            model=seat.model,
            bin_path=seat.harness_id,  # placeholder name in dry-run
            which=lambda name: f"/dry/{name}",
            cwd=seat_workdir,
            disable_web_search=disable_web,
        )
    except (ValueError, FileNotFoundError) as e:
        would_argv = [seat.harness_id or "?", str(e)]
    labels = _labels(req, seat)
    return {
        "ok": True,
        "adapter": "direct",
        "dry_run": True,
        "harness_id": seat.harness_id,
        "herdr_kind": seat.herdr_kind,
        "model": seat.model,
        "would_exec": [{"argv": would_argv, "prompt": prompt, "note": "direct dry-run"}],
        "message": f"direct-adapter dry-run for {req.node_id}",
        "seat": seat.to_dict(),
        "herdr_labels": labels,
        "labels": labels,
    }


def _labels(req: SeatRequest, seat: SeatResult) -> dict[str, Any]:
    desk_id = req.desk_id or "desk"
    thread_id = req.thread_id or f"thread-{desk_id}"
    return {
        "desk_id": desk_id,
        "thread_id": thread_id,
        "role": req.role or "worker",
        "node_id": req.node_id,
        "harness_id": seat.harness_id,
        "model": seat.model,
        "adapter": "direct",
        "label": f"{desk_id} {thread_id}",
    }


def run_direct(
    req: SeatRequest,
    seat: SeatResult,
    *,
    dry_run: bool | None = None,
    timeout: float | None = None,
    which: Callable[[str], str | None] | None = None,
    wait: bool = True,
    env: dict[str, str] | None = None,
    effort_flags: list[str] | None = None,
) -> dict[str, Any]:
    """Spawn a real CLI harness process (or dry-run stub).

    Captures stdout/stderr to a per-seat log under state dir; tracks PID;
    returns SeatResult fields + labels (desk_id, thread_id).
    """
    use_dry = bool(dry_run) if dry_run is not None else _env_dry()
    if use_dry:
        return run_direct_stub(req, seat, dry_run=True)

    if not seat.ok or not seat.harness_id:
        return {
            "ok": False,
            "adapter": "direct",
            "dry_run": False,
            "error": seat.error or "harness selection failed",
            "seat": seat.to_dict(),
        }

    labels = _labels(req, seat)
    prompt = req.objective or req.node_id
    # Derive CLI effort/reasoning flags from harnesses.toml settings when not passed.
    if not effort_flags:
        try:
            from . import config as harness_config

            cfg = harness_config.load()
            settings = dict(getattr(cfg.settings_for(seat.harness_id), 'settings', None) or {})
            effort_flags = argv_mod.effort_flags_for(seat.harness_id, settings)
            reasoning = str(settings.get("reasoning") or "").strip()
            if reasoning:
                labels["reasoning"] = reasoning
        except Exception:  # noqa: BLE001 — best-effort
            effort_flags = effort_flags or None
    seat_workdir, disable_web = _seat_workdir_and_web()
    try:
        cmd = argv_mod.build_argv(
            seat.harness_id,
            prompt=prompt,
            model=seat.model,
            which=which,
            effort_flags=effort_flags,
            cwd=seat_workdir,
            disable_web_search=disable_web,
        )
    except FileNotFoundError as e:
        return {
            "ok": False,
            "adapter": "direct",
            "dry_run": False,
            "error": str(e),
            "harness_id": seat.harness_id,
            "herdr_kind": seat.herdr_kind,
            "model": seat.model,
            "seat": seat.to_dict(),
            "herdr_labels": labels,
            "labels": labels,
        }
    except ValueError as e:
        return {
            "ok": False,
            "adapter": "direct",
            "dry_run": False,
            "error": str(e),
            "seat": seat.to_dict(),
            "herdr_labels": labels,
            "labels": labels,
        }

    log_dir = procs.seat_log_dir()
    safe_node = "".join(c if c.isalnum() or c in "-_" else "-" for c in req.node_id)[:48]
    log_path = log_dir / f"{safe_node}-{seat.harness_id}-{int(time.time())}.log"

    run_env = dict(env if env is not None else os.environ)
    run_env["OKSTRATR_NODE_ID"] = req.node_id
    run_env["OKSTRATR_HARNESS"] = seat.harness_id or ""
    if seat.model:
        run_env["OKSTRATR_MODEL"] = seat.model
    if labels.get("desk_id"):
        run_env["OKSTRATR_DESK_ID"] = str(labels["desk_id"])
    if labels.get("thread_id"):
        run_env["OKSTRATR_THREAD_ID"] = str(labels["thread_id"])
    if labels.get("reasoning"):
        run_env["OKSTRATR_REASONING"] = str(labels["reasoning"])
        run_env["OKSTRATR_REASONING_EFFORT"] = str(labels["reasoning"])
    run_env["OKSTRATR_CWD"] = seat_workdir

    t0 = time.time()
    try:
        with log_path.open("w", encoding="utf-8") as logf:
            logf.write(f"# argv: {cmd}\n")
            logf.flush()
            proc = subprocess.Popen(
                cmd,
                stdout=logf,
                stderr=subprocess.STDOUT,
                env=run_env,
                cwd=seat_workdir,
                start_new_session=True,
            )
            rec = procs.ProcRecord(
                pid=proc.pid,
                harness_id=seat.harness_id or "",
                node_id=req.node_id,
                desk_id=labels.get("desk_id"),
                thread_id=labels.get("thread_id"),
                log_path=str(log_path),
                argv=list(cmd),
            )
            procs.register(rec)
            seat.detail = dict(seat.detail or {})
            seat.detail["pid"] = proc.pid
            seat.detail["log_path"] = str(log_path)
            seat.adapter = "direct"

            if not wait:
                return {
                    "ok": True,
                    "adapter": "direct",
                    "dry_run": False,
                    "pid": proc.pid,
                    "log_path": str(log_path),
                    "harness_id": seat.harness_id,
                    "herdr_kind": seat.herdr_kind,
                    "model": seat.model,
                    "argv": cmd,
                    "seat": seat.to_dict(),
                    "herdr_labels": labels,
                    "labels": labels,
                    "running": True,
                }

            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                procs.kill_pid(proc.pid)
                return {
                    "ok": False,
                    "adapter": "direct",
                    "dry_run": False,
                    "error": "timeout",
                    "timeout": timeout,
                    "pid": proc.pid,
                    "log_path": str(log_path),
                    "harness_id": seat.harness_id,
                    "herdr_kind": seat.herdr_kind,
                    "model": seat.model,
                    "argv": cmd,
                    "elapsed_sec": round(time.time() - t0, 3),
                    "seat": seat.to_dict(),
                    "herdr_labels": labels,
                    "labels": labels,
                }
            finally:
                procs.unregister_pid(proc.pid)

            stdout_tail = _tail(log_path, 4000)
            ok = rc == 0
            return {
                "ok": ok,
                "adapter": "direct",
                "dry_run": False,
                "returncode": rc,
                "pid": proc.pid,
                "log_path": str(log_path),
                "stdout": stdout_tail,
                "harness_id": seat.harness_id,
                "herdr_kind": seat.herdr_kind,
                "model": seat.model,
                "argv": cmd,
                "elapsed_sec": round(time.time() - t0, 3),
                "error": None if ok else f"exit {rc}",
                "seat": seat.to_dict(),
                "herdr_labels": labels,
                "labels": labels,
            }
    except OSError as e:
        return {
            "ok": False,
            "adapter": "direct",
            "dry_run": False,
            "error": str(e),
            "argv": cmd,
            "harness_id": seat.harness_id,
            "herdr_kind": seat.herdr_kind,
            "model": seat.model,
            "seat": seat.to_dict(),
            "herdr_labels": labels,
            "labels": labels,
        }


def kill_direct_for_desk(desk_id: str | None = None, *, thread_id: str | None = None) -> dict[str, Any]:
    """Kill tracked direct seats for a desk (call on quiet/dismiss)."""
    return procs.kill_for_desk(desk_id, thread_id=thread_id)


def _env_dry() -> bool:
    raw = (os.environ.get("OKSTRATR_HERDR_DRY_RUN") or os.environ.get("OKSTRATR_DIRECT_DRY_RUN") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _tail(path: Path, n: int) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return data[-n:] if len(data) > n else data
