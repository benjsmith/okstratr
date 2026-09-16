"""Async Herdr drive jobs for non-blocking POST /api/desk/start.

ThreadingHTTPServer already handles concurrent requests; this module tracks a
single in-flight ``herdr.run_ready`` (global, or one per desk) so Start can
return immediately while seats run in a background thread.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from time import time
from typing import Any, Callable

from .logutil import get_logger
from .paths import state_dir

_log = get_logger(__name__)

JOBS_NAME = "herdr_jobs.json"

_lock = threading.RLock()
_jobs: dict[str, dict[str, Any]] = {}
# desk_id -> job_id for running jobs; also track a global active id
_running_by_desk: dict[str, str] = {}
_global_running_id: str | None = None
_last_error: str | None = None


def jobs_path() -> Path:
    return state_dir() / JOBS_NAME


def reset_for_tests() -> None:
    """Clear in-memory job state (pytest)."""
    global _global_running_id, _last_error
    with _lock:
        _jobs.clear()
        _running_by_desk.clear()
        _global_running_id = None
        _last_error = None


def _persist_unlocked() -> None:
    path = jobs_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "jobs": list(_jobs.values())[-20:],  # keep a short tail
            "running_by_desk": dict(_running_by_desk),
            "global_running_id": _global_running_id,
            "last_error": _last_error,
            "ts": time(),
        }
        path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError:
        _log.warning("herdr_jobs: persist failed", exc_info=True)


def last_error() -> str | None:
    with _lock:
        return _last_error


def get_job(job_id: str | None = None) -> dict[str, Any] | None:
    with _lock:
        if job_id:
            j = _jobs.get(str(job_id))
            return dict(j) if j else None
        if _global_running_id and _global_running_id in _jobs:
            return dict(_jobs[_global_running_id])
        # Prefer any running, else newest by created_at
        running = [j for j in _jobs.values() if j.get("state") == "running"]
        if running:
            return dict(running[-1])
        if not _jobs:
            return None
        newest = max(_jobs.values(), key=lambda j: float(j.get("created_at") or 0))
        return dict(newest)


def active_job(*, desk_id: str | None = None) -> dict[str, Any] | None:
    """Return the running job for desk (or the global running job)."""
    with _lock:
        if desk_id:
            jid = _running_by_desk.get(str(desk_id))
            if jid and jid in _jobs and _jobs[jid].get("state") == "running":
                return dict(_jobs[jid])
            return None
        if _global_running_id and _global_running_id in _jobs:
            j = _jobs[_global_running_id]
            if j.get("state") == "running":
                return dict(j)
        return None


def snapshot_for_status() -> dict[str, Any] | None:
    """Active or most recent job for /api/status."""
    with _lock:
        j = None
        if _global_running_id and _global_running_id in _jobs:
            j = _jobs[_global_running_id]
        elif _jobs:
            j = max(_jobs.values(), key=lambda x: float(x.get("updated_at") or x.get("created_at") or 0))
        if not j:
            return None
        out = {
            "id": j.get("id"),
            "state": j.get("state"),
            "desk_id": j.get("desk_id"),
            "limit": j.get("limit"),
            "created_at": j.get("created_at"),
            "updated_at": j.get("updated_at"),
            "finished_at": j.get("finished_at"),
            "error": j.get("error"),
            "ran": j.get("ran"),
            "progress": j.get("progress"),
        }
        return out


def _detect_herdr_failure(herdr_run: dict[str, Any] | None, herdr_err: str | None) -> str | None:
    if herdr_err:
        return herdr_err
    herdr_run = herdr_run or {}
    results = herdr_run.get("results") or []
    missing = any(
        "Herdr not on PATH" in str(r.get("error") or "")
        or "not on PATH" in str(r.get("error") or "")
        or "missing required --pane" in str(r.get("error") or "")
        or "pane split failed" in str(r.get("error") or "")
        for r in results
        if isinstance(r, dict)
    )
    all_failed = bool(results) and all(
        isinstance(r, dict) and r.get("ok") is False for r in results
    )
    hard_fail = herdr_run.get("ok") is False and not results
    if missing or hard_fail or all_failed:
        return (
            (results[0].get("error") if results else None)
            or herdr_run.get("error")
            or "herdr.run_ready failed"
        )
    return None


def _finish_job(
    job_id: str,
    *,
    herdr_run: dict[str, Any] | None,
    herdr_err: str | None,
    desk_id: str | None,
) -> None:
    global _global_running_id, _last_error
    from . import desks, status

    fail = _detect_herdr_failure(herdr_run, herdr_err)
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["updated_at"] = time()
        job["finished_at"] = job["updated_at"]
        job["herdr_run"] = herdr_run
        if fail:
            job["state"] = "failed"
            job["error"] = fail
            _last_error = fail
        else:
            job["state"] = "done"
            job["error"] = None
            _last_error = None
        ran = (herdr_run or {}).get("ran") or []
        job["ran"] = list(ran)
        job["progress"] = {
            "ran": len(ran),
            "limit": job.get("limit"),
            "desk_quieted": (herdr_run or {}).get("desk_quieted"),
        }
        if _global_running_id == job_id:
            _global_running_id = None
        if desk_id and _running_by_desk.get(str(desk_id)) == job_id:
            _running_by_desk.pop(str(desk_id), None)
        _persist_unlocked()

    if fail and desk_id:
        try:
            desks.stop(str(desk_id))
        except Exception:  # noqa: BLE001
            _log.warning("herdr_jobs: stop after failure failed", exc_info=True)
    try:
        status.write_status()
    except Exception:  # noqa: BLE001
        _log.warning("herdr_jobs: write_status after finish failed", exc_info=True)


def _worker(
    job_id: str,
    *,
    desk_id: str | None,
    limit: int,
    dry_run: bool | None,
    run_ready: Callable[..., dict[str, Any]],
) -> None:
    herdr_run: dict[str, Any] | None = None
    herdr_err: str | None = None
    try:
        herdr_run = run_ready(limit=limit, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001
        herdr_err = str(e)
        herdr_run = {"ok": False, "error": f"herdr.run_ready failed: {e}"}
        _log.warning("herdr_jobs: run_ready raised: %s", e)
    _finish_job(job_id, herdr_run=herdr_run, herdr_err=herdr_err, desk_id=desk_id)


def kick_run_ready(
    *,
    desk_id: str | None,
    limit: int = 4,
    dry_run: bool | None = None,
    run_ready: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Start a background ``run_ready`` job. Rejects if one is already running.

    Returns ``{ok, herdr_job, message}`` or ``{ok: False, error, herdr_job}``.
    """
    global _global_running_id, _last_error
    from . import herdr as herdr_mod

    run_fn = run_ready or herdr_mod.run_ready
    with _lock:
        if _global_running_id and _global_running_id in _jobs:
            cur = _jobs[_global_running_id]
            if cur.get("state") == "running":
                return {
                    "ok": False,
                    "error": "Herdr drive already running",
                    "herdr_job": dict(cur),
                    "message": (
                        f"Reject: Herdr job {cur.get('id')} is still running "
                        f"(desk={cur.get('desk_id')}). Stop or wait before Start again."
                    ),
                }
        if desk_id:
            jid = _running_by_desk.get(str(desk_id))
            if jid and jid in _jobs and _jobs[jid].get("state") == "running":
                cur = _jobs[jid]
                return {
                    "ok": False,
                    "error": "Herdr drive already running for this desk",
                    "herdr_job": dict(cur),
                    "message": (
                        f"Reject: desk {desk_id} already has Herdr job {cur.get('id')} running."
                    ),
                }

        job_id = uuid.uuid4().hex[:12]
        now = time()
        job: dict[str, Any] = {
            "id": job_id,
            "state": "running",
            "desk_id": desk_id,
            "limit": int(limit),
            "dry_run": dry_run,
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "error": None,
            "herdr_run": None,
            "ran": [],
            "progress": {"ran": 0, "limit": int(limit)},
        }
        _jobs[job_id] = job
        _global_running_id = job_id
        if desk_id:
            _running_by_desk[str(desk_id)] = job_id
        _last_error = None
        _persist_unlocked()
        job_snap = dict(job)

    t = threading.Thread(
        target=_worker,
        name=f"okstratr-herdr-{job_id}",
        kwargs={
            "job_id": job_id,
            "desk_id": desk_id,
            "limit": int(limit),
            "dry_run": dry_run,
            "run_ready": run_fn,
        },
        daemon=True,
    )
    t.start()
    return {
        "ok": True,
        "herdr_job": job_snap,
        "message": (
            f"Desk started; Herdr drive running in background "
            f"(job {job_id}, limit={limit})."
        ),
    }
