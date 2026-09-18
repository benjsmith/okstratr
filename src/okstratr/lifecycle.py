"""Service lifecycle: start / stop / restart / status / ensure_running / doctor.

Manages okstratr serve (:8767) and optional observer-panel static host (:8768).
Consent-first for skill/CLI paths (use ``prompt=False`` / ``--yes`` to skip).
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import PORT
from .paths import state_dir
from .public_base import public_base

OBSERVER_PORT = int(os.environ.get("OKSTRATR_OBSERVER_PORT") or "8768")
SERVE_HOST = "127.0.0.1"
CONSENT_PROMPT = (
    "okstratr serve is not running. Start it on :8767 (+ observer panel)?"
)
PIDFILE_NAME = "okstratr.pid"
OBSERVER_PIDFILE_NAME = "observer.pid"
STARTED_AT_NAME = "serve_started_at"


def serve_url(host: str = SERVE_HOST, port: int = PORT) -> str:
    return f"http://{host}:{port}"


def observer_url(host: str = SERVE_HOST, port: int | None = None) -> str:
    """Prefer same-server /observer/ when serve is up; else dedicated observer port.

    Honors ``OKSTRATR_PUBLIC_BASE`` (e.g. ``/embed/okstratr``) for reverse-proxy embeds.
    """
    base = public_base()  # "" or "/embed/okstratr"
    if health_ok():
        return f"{serve_url()}{base}/observer/"
    p = OBSERVER_PORT if port is None else port
    return f"http://{host}:{p}/"


def observer_asset_dir() -> Path:
    """Packaged Observer static assets (HTML/JS/CSS)."""
    return Path(__file__).resolve().parent / "observer"


def pidfile_path() -> Path:
    return state_dir() / PIDFILE_NAME


def observer_pidfile_path() -> Path:
    return state_dir() / OBSERVER_PIDFILE_NAME


def started_at_path() -> Path:
    return state_dir() / STARTED_AT_NAME


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        return int(raw.split()[0])
    except ValueError:
        return None


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


def _port_open(host: str, port: int, *, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def health_ok(base: str | None = None, *, timeout: float = 0.8) -> bool:
    url = (base or serve_url()).rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {}
            return bool(data.get("ok"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def observer_reachable(*, timeout: float = 0.6) -> bool:
    """True if the observer panel is served (same-origin /observer/ or :8768)."""
    base = public_base()
    candidates = [
        f"{serve_url()}{base}/observer/",
        f"{serve_url()}{base}/observer/index.html",
        f"{serve_url()}/observer/",
        f"{serve_url()}/observer/index.html",
        f"http://{SERVE_HOST}:{OBSERVER_PORT}/",
        f"http://{SERVE_HOST}:{OBSERVER_PORT}/index.html",
    ]
    for url in candidates:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                if 200 <= resp.status < 400:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return False


def is_serve_running() -> bool:
    if health_ok():
        return True
    pid = _read_pid(pidfile_path())
    if pid and _pid_alive(pid) and _port_open(SERVE_HOST, PORT):
        return True
    return False


def is_observer_running() -> bool:
    if observer_reachable():
        return True
    pid = _read_pid(observer_pidfile_path())
    return bool(pid and _pid_alive(pid) and _port_open(SERVE_HOST, OBSERVER_PORT))


def ensure_running(*, prompt: bool = True, yes: bool = False) -> dict[str, Any]:
    """Skill invoke helper.

    Returns ``{running, need_consent, message, observer_url, serve_url}``.
    When not running and ``prompt`` and not ``yes``, sets need_consent and
    does not start.
    """
    running = is_serve_running()
    observer_up = is_observer_running()
    if running:
        return {
            "running": True,
            "need_consent": False,
            "message": f"okstratr serve is up on :{PORT}; observer panel at {observer_url()}",
            "serve_url": serve_url(),
            "observer_url": observer_url(),
            "observer_running": observer_up or running,  # /observer/ via serve
        }
    if prompt and not yes:
        return {
            "running": False,
            "need_consent": True,
            "message": CONSENT_PROMPT,
            "serve_url": serve_url(),
            "observer_url": observer_url(),
            "observer_running": False,
        }
    started = start(yes=True, observer=True)
    return {
        "running": bool(started.get("serve_running")),
        "need_consent": False,
        "message": started.get("message") or "started",
        "serve_url": serve_url(),
        "observer_url": observer_url(),
        "observer_running": bool(started.get("observer_running")),
        "start": started,
    }


def doctor() -> dict[str, Any]:
    """Return ensure_running(prompt=True) plus asset / port diagnostics."""
    base = ensure_running(prompt=True, yes=False)
    assets = observer_asset_dir()
    index = assets / "index.html"
    return {
        **base,
        "port": PORT,
        "observer_port": OBSERVER_PORT,
        "pidfile": str(pidfile_path()),
        "observer_pidfile": str(observer_pidfile_path()),
        "observer_assets": str(assets),
        "observer_index_exists": index.is_file(),
        "serve_health": health_ok(),
        "observer_reachable": observer_reachable(),
        "port_8767_open": _port_open(SERVE_HOST, PORT),
        "port_8768_open": _port_open(SERVE_HOST, OBSERVER_PORT),
    }


def _python_exe() -> str:
    return sys.executable or "python3"


def _spawn_serve(*, host: str = SERVE_HOST, port: int = PORT) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("OKSTRATR_MODEL", env.get("OKSTRATR_MODEL") or "grok-4.6")
    log_path = state_dir() / "serve.log"
    state_dir().mkdir(parents=True, exist_ok=True)
    cmd = [
        _python_exe(),
        "-m",
        "okstratr",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
    ]
    with open(log_path, "a", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            cmd,
            stdout=logf,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    _write_pid(pidfile_path(), proc.pid)
    started_at_path().write_text(str(time.time()), encoding="utf-8")
    # Wait briefly for health
    deadline = time.time() + 4.0
    healthy = False
    while time.time() < deadline:
        if health_ok():
            healthy = True
            break
        time.sleep(0.15)
    return {
        "pid": proc.pid,
        "healthy": healthy,
        "log": str(log_path),
        "cmd": cmd,
    }


def _spawn_observer_host(*, host: str = SERVE_HOST, port: int = OBSERVER_PORT) -> dict[str, Any]:
    """Dedicated observer-panel static host on :8768 (fallback when not using /observer/)."""
    assets = observer_asset_dir()
    if not (assets / "index.html").is_file():
        return {"ok": False, "error": f"observer panel assets missing under {assets}"}
    log_path = state_dir() / "observer.log"
    # Use stdlib http.server bound to observer dir
    cmd = [
        _python_exe(),
        "-m",
        "http.server",
        str(port),
        "--bind",
        host,
        "--directory",
        str(assets),
    ]
    with open(log_path, "a", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            cmd,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _write_pid(observer_pidfile_path(), proc.pid)
    deadline = time.time() + 2.5
    ok = False
    while time.time() < deadline:
        if _port_open(host, port):
            ok = True
            break
        time.sleep(0.1)
    return {
        "ok": ok,
        "pid": proc.pid,
        "port": port,
        "log": str(log_path),
        "url": f"http://{host}:{port}/",
    }


def start(
    *,
    yes: bool = False,
    prompt: bool = True,
    observer: bool = True,
    host: str = SERVE_HOST,
    port: int = PORT,
) -> dict[str, Any]:
    """Start serve (+ observer panel) with consent unless already running or yes=True."""
    if is_serve_running():
        out: dict[str, Any] = {
            "ok": True,
            "already_running": True,
            "serve_running": True,
            "observer_running": is_observer_running() or True,
            "message": f"already running on :{port}",
            "serve_url": serve_url(host, port),
            "observer_url": observer_url(),
        }
        # Ensure observer-panel dedicated host only if serve lacks /observer and observer requested
        if observer and not observer_reachable():
            out["observer_spawn"] = _spawn_observer_host()
            out["observer_running"] = is_observer_running()
        return out

    if prompt and not yes:
        if sys.stdin.isatty():
            print(CONSENT_PROMPT, file=sys.stderr)
            ans = (input("[y/N] ").strip() or "").lower()
            if ans not in ("y", "yes"):
                return {
                    "ok": False,
                    "need_consent": True,
                    "serve_running": False,
                    "observer_running": False,
                    "message": "cancelled — not started",
                    "consent_prompt": CONSENT_PROMPT,
                }
        else:
            return {
                "ok": False,
                "need_consent": True,
                "serve_running": False,
                "observer_running": False,
                "message": CONSENT_PROMPT,
                "consent_prompt": CONSENT_PROMPT,
            }

    spawned = _spawn_serve(host=host, port=port)
    observer_info: dict[str, Any] | None = None
    # Serve hosts /observer/; optional dedicated host for Omarchy display convenience
    if observer:
        # Prefer same-server /observer/; also start :8768 if env asks or serve not healthy yet
        if os.environ.get("OKSTRATR_OBSERVER_DEDICATED", "").strip() in ("1", "true", "yes"):
            observer_info = _spawn_observer_host()
        elif not health_ok():
            observer_info = _spawn_observer_host()

    return {
        "ok": bool(spawned.get("healthy") or is_serve_running()),
        "already_running": False,
        "serve_running": is_serve_running(),
        "observer_running": observer_reachable() or is_observer_running(),
        "serve": spawned,
        "observer": observer_info,
        "message": f"started serve on :{port}"
        + (f"; observer panel {observer_url()}" if observer else ""),
        "serve_url": serve_url(host, port),
        "observer_url": observer_url(),
        "consent_prompt": CONSENT_PROMPT,
    }


def _kill_pidfile(path: Path, *, label: str) -> dict[str, Any]:
    pid = _read_pid(path)
    info: dict[str, Any] = {"label": label, "pid": pid, "killed": False}
    if pid and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.35)
            if _pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
            info["killed"] = True
        except OSError as e:
            info["error"] = str(e)
    try:
        path.unlink(missing_ok=True)  # type: ignore[call-arg]
    except TypeError:
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    except OSError:
        pass
    return info


def _kill_okstratr_children() -> list[dict[str, Any]]:
    """Best-effort: stop seat supervisors owned by okstratr (harness procs)."""
    out: list[dict[str, Any]] = []
    try:
        from .harness import procs as harness_procs

        recs = harness_procs.load_registry()
        for pid, rec in list(recs.items()):
            try:
                out.append(harness_procs.kill_pid(int(pid)))
            except Exception as e:  # noqa: BLE001
                out.append({"pid": pid, "error": str(e)})
    except Exception as e:  # noqa: BLE001
        out.append({"error": str(e)})
    return out


def shutdown(*, kill_seats: bool = True) -> dict[str, Any]:
    """Stop serve, Observer static host, and optional child seat supervisors."""
    serve_kill = _kill_pidfile(pidfile_path(), label="serve")
    observer_kill = _kill_pidfile(observer_pidfile_path(), label="observer")
    # Also try pkill patterns if still healthy/open
    extra: list[str] = []
    if health_ok() or _port_open(SERVE_HOST, PORT):
        try:
            subprocess.run(
                ["pkill", "-f", "okstratr serve"],
                check=False,
                capture_output=True,
                timeout=3,
            )
            extra.append("pkill okstratr serve")
        except (OSError, subprocess.TimeoutExpired):
            pass
    if _port_open(SERVE_HOST, OBSERVER_PORT):
        try:
            # Only kill http.server bound to observer assets path if possible
            subprocess.run(
                ["pkill", "-f", f"http.server {OBSERVER_PORT}"],
                check=False,
                capture_output=True,
                timeout=3,
            )
            extra.append(f"pkill http.server {OBSERVER_PORT}")
        except (OSError, subprocess.TimeoutExpired):
            pass

    seats: list[dict[str, Any]] = []
    if kill_seats:
        seats = _kill_okstratr_children()

    time.sleep(0.2)
    return {
        "ok": not is_serve_running(),
        "serve": serve_kill,
        "observer": observer_kill,
        "seats": seats,
        "extra": extra,
        "serve_running": is_serve_running(),
        "observer_running": is_observer_running(),
        "message": "shutdown complete" if not is_serve_running() else "shutdown partial — serve still up",
    }


def restart(*, yes: bool = True, observer: bool = True) -> dict[str, Any]:
    stopped = shutdown(kill_seats=True)
    time.sleep(0.4)
    started = start(yes=yes, prompt=False, observer=observer)
    return {
        "ok": bool(started.get("ok")),
        "shutdown": stopped,
        "start": started,
        "serve_url": serve_url(),
        "observer_url": observer_url(),
        "message": "restarted" if started.get("ok") else "restart failed",
    }


def _uptime_seconds() -> float | None:
    path = started_at_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
        started = float(raw)
        return max(0.0, time.time() - started)
    except (OSError, ValueError):
        pass
    pid = _read_pid(pidfile_path())
    if not pid:
        return None
    # Best-effort via /proc (Linux) — Mac apply may differ
    try:
        stat = Path(f"/proc/{pid}")
        if stat.exists():
            # no reliable start without ps; leave None
            return None
    except OSError:
        pass
    return None


def _fmt_dur(sec: float | None) -> str:
    if sec is None:
        return "n/a"
    s = int(sec)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def _desk_counts() -> dict[str, Any]:
    try:
        from . import desks

        snap = desks.status_snapshot()
        rows = snap.get("standing") or snap.get("desks") or snap.get("items") or []
        by_kind: dict[str, int] = {}
        by_state: dict[str, int] = {}
        working = 0
        quiet = 0
        if isinstance(rows, list):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                k = str(r.get("kind") or "?")
                st = str(r.get("state") or "?")
                by_kind[k] = by_kind.get(k, 0) + 1
                by_state[st] = by_state.get(st, 0) + 1
                if st == "working":
                    working += 1
                elif st in ("quiet", "idle"):
                    quiet += 1
        return {
            "by_kind": by_kind,
            "by_state": by_state,
            "working": working,
            "quiet": quiet,
            "total": sum(by_kind.values()),
            "active_id": snap.get("active_id") or snap.get("focused_id"),
        }
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "by_kind": {}, "by_state": {}, "working": 0, "quiet": 0, "total": 0}


def _tokens_used() -> dict[str, Any]:
    """Best-effort token counters; stub 0 / n/a when unknown."""
    # Look for any existing counter files under state
    candidates = [
        state_dir() / "tokens.json",
        state_dir() / "usage.json",
        state_dir() / "counters.json",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                tok = data.get("tokens") or data.get("tokens_used") or data.get("total_tokens")
                if tok is not None:
                    return {"tokens": int(tok), "source": str(p.name), "n_a": False}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return {"tokens": 0, "source": "n/a", "n_a": True}


def _files_lines_written() -> dict[str, Any]:
    """From ops_audit file ops + harness_logs sizes/line counts (metadata)."""
    files = 0
    lines = 0
    audit_file_ops = 0
    try:
        from . import ops_audit

        for rec in ops_audit.tail(500):
            if not isinstance(rec, dict):
                continue
            op = str(rec.get("op") or "")
            kind = str(rec.get("kind") or "")
            if "file" in op.lower() or kind in ("file", "fs", "write"):
                audit_file_ops += 1
                files += 1
    except Exception:  # noqa: BLE001
        pass

    log_dir = state_dir() / "harness_logs"
    log_files = 0
    log_bytes = 0
    log_lines = 0
    if log_dir.is_dir():
        for p in log_dir.rglob("*"):
            if not p.is_file():
                continue
            log_files += 1
            try:
                log_bytes += p.stat().st_size
            except OSError:
                continue
            # Cheap line count for small files only
            try:
                if p.stat().st_size < 2_000_000:
                    log_lines += p.read_text(encoding="utf-8", errors="replace").count("\n")
            except OSError:
                pass
    lines = log_lines
    if files == 0 and log_files:
        files = log_files
    return {
        "files": files,
        "lines": lines,
        "audit_file_ops": audit_file_ops,
        "harness_log_files": log_files,
        "harness_log_bytes": log_bytes,
    }


def status_payload() -> dict[str, Any]:
    """Structured status used by the CLI box and API consumers."""
    serve_up = is_serve_running()
    observer_up = observer_reachable() or is_observer_running()
    uptime = _uptime_seconds() if serve_up else None

    board_chip = "n/a"
    web_chip = "n/a"
    cwd = "n/a"
    backend = "n/a"
    harnesses: list[str] = []
    try:
        from . import bb_settings

        board_chip = bb_settings.mode_chip()
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import web_egress

        w = web_egress.status()
        web_chip = str(w.get("chip") or w.get("mode") or w.get("label") or w)
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import workspace

        ws = workspace.status()
        cwd = str(ws.get("cwd") or ws.get("path") or "n/a")
    except Exception:  # noqa: BLE001
        pass
    try:
        from .harness import config as harness_config

        cfg = harness_config.load()
        backend = str(getattr(cfg, "backend", None) or cfg.to_dict().get("backend") or "n/a")
        harnesses = list(cfg.enabled or []) if getattr(cfg, "enabled", None) else list(
            cfg.preference_order() if hasattr(cfg, "preference_order") else []
        )
    except Exception:  # noqa: BLE001
        pass

    desks = _desk_counts()
    tokens = _tokens_used()
    files = _files_lines_written()

    return {
        "services": {
            "serve": {
                "up": serve_up,
                "port": PORT,
                "url": serve_url(),
                "health": health_ok() if serve_up else False,
                "pid": _read_pid(pidfile_path()),
            },
            "observer": {
                "up": observer_up or (serve_up and True),  # /observer/ via serve
                "url": observer_url() if serve_up or observer_up else f"http://{SERVE_HOST}:{OBSERVER_PORT}/",
                "port_dedicated": OBSERVER_PORT,
                "reachable": observer_reachable(),
            },
        },
        "board_duration_chip": board_chip,
        "web_egress": web_chip,
        "cwd": cwd,
        "backend": backend,
        "harnesses": harnesses,
        "desks": desks,
        "time": {
            "process_uptime_sec": uptime,
            "process_uptime": _fmt_dur(uptime),
            "desks_working": desks.get("working", 0),
            "desks_quiet": desks.get("quiet", 0),
        },
        "tokens": tokens,
        "files": files,
        "consent_prompt": CONSENT_PROMPT,
    }


def format_status_box(payload: dict[str, Any] | None = None) -> str:
    """Pretty CLI status box."""
    p = payload or status_payload()
    svc = p.get("services") or {}
    serve = svc.get("serve") or {}
    observer = svc.get("observer") or {}
    desks = p.get("desks") or {}
    time_info = p.get("time") or {}
    tokens = p.get("tokens") or {}
    files = p.get("files") or {}

    def yn(up: bool) -> str:
        return "UP" if up else "DOWN"

    serve_line = (
        f"serve  {yn(bool(serve.get('up')))}  :{serve.get('port', PORT)}  "
        f"{serve.get('url') or serve_url()}"
    )
    observer_line = (
        f"observer {yn(bool(observer.get('up') or observer.get('reachable')))}  "
        f"{observer.get('url') or observer_url()}"
    )
    kind_bits = ", ".join(f"{k}={v}" for k, v in sorted((desks.get("by_kind") or {}).items())) or "none"
    state_bits = ", ".join(f"{k}={v}" for k, v in sorted((desks.get("by_state") or {}).items())) or "none"
    harness = ",".join(p.get("harnesses") or []) or "n/a"
    tok = "n/a" if tokens.get("n_a") else str(tokens.get("tokens", 0))
    width = 62
    inner = width - 2

    def row(label: str, value: str) -> str:
        text = f" {label} {value}"
        if len(text) > inner:
            text = text[: inner - 1] + "…"
        return "│" + text.ljust(inner) + "│"

    box = [
        "┌" + "─" * inner + "┐",
        "│" + " okstratr status ".center(inner) + "│",
        "├" + "─" * inner + "┤",
        row("", serve_line),
        row("", observer_line),
        row("board ", str(p.get("board_duration_chip"))),
        row("web   ", str(p.get("web_egress"))),
        row("cwd   ", str(p.get("cwd"))),
        row("back  ", str(p.get("backend"))),
        row("harn  ", harness),
        row("desks ", f"kinds[{kind_bits}]"),
        row("      ", f"states[{state_bits}]"),
        row(
            "time  ",
            f"up {_fmt_dur(time_info.get('process_uptime_sec'))}  "
            f"working={time_info.get('desks_working', 0)} quiet={time_info.get('desks_quiet', 0)}",
        ),
        row("tok   ", f"{tok}" + (" (n/a)" if tokens.get("n_a") else "")),
        row(
            "files ",
            f"{files.get('files', 0)} files / {files.get('lines', 0)} lines "
            f"(logs={files.get('harness_log_files', 0)})",
        ),
        "└" + "─" * inner + "┘",
    ]
    return "\n".join(box)


