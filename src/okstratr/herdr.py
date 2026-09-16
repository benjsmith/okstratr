"""Herdr bridge — launch/focus UI + finite-job seat for ready DAG nodes.

Role split: Herdr = runtime; okstratr = desk brain (DAG/CoS/blackboard).
Finite-job rule: always stop/release agents after a node; never leave them running.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from time import sleep, time
from typing import Any

from . import blackboard, dag, status

DEFAULT_KIND = "grok"
DEFAULT_TIMEOUT_SEC = 120
DEFAULT_LIMIT = 1
# Herdr agent names: [a-z][a-z0-9_-]{0,31} (max 32). Desk/thread stay in labels metadata.
AGENT_ID_MAX = 32
AGENT_ID_FORMAT = "o{desk8}{role6}{node6}"
HERDR_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
PANE_SHELL_WAIT_SEC = 0.5

# QML close-dialog copy (bind status.ui.close_warning). Kernel suspends; desks quiet.
CLOSE_WARNING = (
    "Closing Okstratr will shut down the kernel. "
    "Standing desks will suspend (quiet) and the session returns to regular Herdr. "
    "Continue?"
)


def herdr_bin(path: str | None = None) -> str | None:
    """Resolve herdr / omarchy-herdr on PATH (optional PATH override)."""
    return shutil.which("herdr", path=path) or shutil.which("omarchy-herdr", path=path)


NOT_INSTALLED_MSG = (
    "Herdr not installed — install with: omarchy pkg add herdr "
    "or curl -fsSL https://herdr.dev/install.sh | sh"
)

# Session/display keys to import from systemd --user (serve often lacks these).
_SYSTEMD_ENV_KEYS = (
    "WAYLAND_DISPLAY",
    "DISPLAY",
    "XDG_RUNTIME_DIR",
    "HYPRLAND_INSTANCE_SIGNATURE",
    "HYPRLAND_CMD",
    "DBUS_SESSION_BUS_ADDRESS",
    "QT_QPA_PLATFORM",
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
)


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _is_omarchy_terminal_launcher(cmd: list[str]) -> bool:
    """True when cmd is omarchy-launch-terminal-herdr or omarchy-launch-terminal …"""
    if not cmd:
        return False
    name = _basename(cmd[0])
    return name in ("omarchy-launch-terminal-herdr", "omarchy-launch-terminal")


def _parse_systemd_env_line(line: str) -> tuple[str, str] | None:
    if "=" not in line:
        return None
    key, _, val = line.partition("=")
    key = key.strip()
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        val = val[1:-1]
    if not key or not val:
        return None
    return key, val


def systemd_user_environment() -> dict[str, str]:
    """Parse `systemctl --user show-environment` (best-effort)."""
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        parsed = _parse_systemd_env_line(line)
        if parsed:
            out[parsed[0]] = parsed[1]
    return out


def merge_user_session_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Copy process env and overlay Wayland/Hyprland/DBus keys from systemd --user."""
    env = dict(base if base is not None else os.environ)
    sysd = systemd_user_environment()
    for key in _SYSTEMD_ENV_KEYS:
        val = (sysd.get(key) or "").strip()
        if not val:
            continue
        # Skip obviously broken placeholders
        if val in ("-", "none", "null"):
            continue
        env[key] = val
    # Ensure ~/.local/bin (herdr install.sh default) is on PATH for which + child
    home = os.path.expanduser("~")
    local_bin = os.path.join(home, ".local", "bin")
    path_val = env.get("PATH") or ""
    parts = [p for p in path_val.split(":") if p]
    if local_bin not in parts:
        env["PATH"] = f"{local_bin}:{path_val}" if path_val else local_bin
    return env


def _which(cmd: str, path: str | None = None) -> str | None:
    return shutil.which(cmd, path=path)


def _launch_candidates(
    objective: str = "",
    *,
    path: str | None = None,
    home: str | None = None,
) -> list[list[str]]:
    """Ordered Herdr launch commands that avoid omarchy-cmd-terminal-cwd.

    Prefer uwsm-app + xdg-terminal-exec/foot with an explicit --dir $HOME so
    the daemon never hits `pgrep -P \"\"` from hyprctl activewindow.
    Omarchy terminal wrappers are last-resort fallbacks only.
    Objective is passed via OKSTRATR_OBJECTIVE / HERDR_OBJECTIVE env; never as
    argv to terminal wrappers.
    """
    obj = (objective or "").strip()
    home_dir = home or os.path.expanduser("~")
    out: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def add(cmd: list[str]) -> None:
        key = tuple(cmd)
        if key not in seen:
            seen.add(key)
            out.append(cmd)

    uwsm = _which("uwsm-app", path=path)
    xdg_term = _which("xdg-terminal-exec", path=path)
    foot = _which("foot", path=path)

    # 1) uwsm-app + terminal + herdr (no cwd probe / pgrep)
    if uwsm and xdg_term:
        add([uwsm, "--", xdg_term, "--dir", home_dir, "herdr"])
    if uwsm and foot:
        add([uwsm, "--", foot, "herdr"])

    # 2) Direct herdr binaries (objective argv OK; needs display env)
    for name in ("herdr", "omarchy-herdr"):
        bin_path = _which(name, path=path)
        if bin_path:
            add([bin_path] + ([obj] if obj else []))

    # 3) uwsm-app -- herdr (no terminal wrapper)
    if uwsm:
        add([uwsm, "--", "herdr"] + ([obj] if obj else []))
        if _which("omarchy-herdr", path=path):
            add([uwsm, "--", "omarchy-herdr"] + ([obj] if obj else []))

    # 4) Omarchy wrappers last — they call omarchy-cmd-terminal-cwd (fragile from serve)
    term_herdr = _which("omarchy-launch-terminal-herdr", path=path)
    if term_herdr:
        add([term_herdr])
    term = _which("omarchy-launch-terminal", path=path)
    if term:
        add([term, "herdr"])

    # 5) Last-resort desktop file only when nothing else
    xdg = _which("xdg-open", path=path)
    if xdg and not out:
        for desktop in (
            "herdr.desktop",
            "omarchy-herdr.desktop",
            "org.omarchy.herdr.desktop",
        ):
            add([xdg, desktop])

    return out


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _timeout_sec() -> float:
    for key in ("OKSTRATR_HERDR_TIMEOUT", "OKSTRATR_HERDR_WAIT_TIMEOUT"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            try:
                return max(1.0, float(raw))
            except ValueError:
                pass
    return float(DEFAULT_TIMEOUT_SEC)


def dry_run_enabled(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return _env_truthy("OKSTRATR_HERDR_DRY_RUN", default=False)


def launch(objective: str = "", *, focus: bool = True) -> dict[str, Any]:
    """
    Best-effort: open Herdr in a terminal with session display env.

    Merges systemd --user environment (WAYLAND_DISPLAY, HIS, …) before spawn so
    foot/uwsm work when serve was started without a compositor env.

    Prefer:
      uwsm-app -- xdg-terminal-exec --dir $HOME herdr
      uwsm-app -- foot herdr
    then direct herdr / uwsm-app -- herdr; omarchy-launch-terminal* only as
    fallback (those hit omarchy-cmd-terminal-cwd / pgrep from daemon context).

    Child stdout/stderr discarded so pgrep Usage / wayland noise never hits the
    serve TTY. Missing herdr binary → ok:false with install hint (even if a
    terminal wrapper was spawned).
    """
    obj = (objective or "").strip()
    env = merge_user_session_env()
    if obj:
        env["OKSTRATR_OBJECTIVE"] = obj
        env["HERDR_OBJECTIVE"] = obj
    if focus:
        env["HERDR_FOCUS"] = "1"

    path = env.get("PATH")
    home = os.path.expanduser("~")
    bin_path = herdr_bin(path=path)
    candidates = _launch_candidates(obj, path=path, home=home)

    if not candidates:
        return {
            "ok": False,
            "dry_run": True,
            "message": NOT_INSTALLED_MSG,
            "objective": obj,
            "would_exec": ["uwsm-app", "--", "xdg-terminal-exec", "--dir", home, "herdr"],
            "attempts": [],
            "candidates": [],
            "herdr_bin": None,
        }

    attempts: list[dict[str, Any]] = []
    launched: list[str] | None = None
    for cmd in candidates:
        try:
            subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            attempts.append({"ok": True, "exec": cmd})
            launched = cmd
            break
        except OSError as e:
            attempts.append({"ok": False, "exec": cmd, "error": str(e)})

    if launched is None:
        return {
            "ok": False,
            "error": attempts[-1].get("error") if attempts else "no launcher",
            "message": NOT_INSTALLED_MSG if not bin_path else None,
            "objective": obj,
            "attempts": attempts,
            "candidates": candidates,
            "herdr_bin": bin_path,
        }

    if not bin_path:
        return {
            "ok": False,
            "exec": launched,
            "objective": obj,
            "attempts": attempts,
            "candidates": candidates,
            "launcher": launched[0],
            "herdr_bin": None,
            "message": NOT_INSTALLED_MSG,
            "error": "herdr binary not on PATH",
        }

    return {
        "ok": True,
        "exec": launched,
        "objective": obj,
        "attempts": attempts,
        "candidates": candidates,
        "launcher": launched[0],
        "herdr_bin": bin_path,
    }


def focus(objective: str = "") -> dict[str, Any]:
    """Focus / reopen Herdr on the given (or seated) objective."""
    obj = (objective or "").strip() or status.get_objective()
    return launch(obj, focus=True)


def _node_prompt(node: dag.Node) -> str:
    parts = [node.title or node.id]
    if node.objective:
        parts.append(node.objective)
    return " — ".join(parts)


def re_sub_safe(s: str, max_len: int = AGENT_ID_MAX) -> str:
    """Filesystem-ish slug (legacy helper; prefer _herdr_token for agent names)."""
    out = []
    for ch in s:
        if ch.isalnum() or ch in "-_":
            out.append(ch.lower() if ch.isalpha() else ch)
        else:
            out.append("-")
    clipped = "".join(out)[: max(1, int(max_len))].strip("-_")
    return clipped or "node"


def _clip(s: str, n: int) -> str:
    return re_sub_safe(s, max_len=n)


def _herdr_token(s: str, n: int) -> str:
    """Lowercase [a-z0-9_-] token clipped to n (may be empty)."""
    out: list[str] = []
    for ch in (s or ""):
        if ch.isalpha():
            out.append(ch.lower())
        elif ch.isdigit() or ch in "-_":
            out.append(ch)
        else:
            out.append("-")
    tok = "".join(out).strip("-_")
    # collapse runs of dashes
    while "--" in tok:
        tok = tok.replace("--", "-")
    return tok[: max(0, int(n))]


def _ensure_herdr_name(name: str) -> str:
    """Force Herdr name grammar: [a-z][a-z0-9_-]{0,31}."""
    raw = _herdr_token(name, AGENT_ID_MAX)
    if not raw or not raw[0].isalpha():
        raw = ("o" + raw)[:AGENT_ID_MAX]
    if not HERDR_NAME_RE.match(raw):
        digest = hashlib.sha1((name or "node").encode()).hexdigest()
        raw = ("o" + digest)[:AGENT_ID_MAX]
    return raw


def make_agent_id(desk_id: str, role: str, node_id: str) -> str:
    """Herdr-safe agent name (≤32): o{desk8}{role6}{node6}, else hash clip.

    Full desk_id / thread_id remain in labels metadata, not the agent name.
    """
    desk = _herdr_token(desk_id or "desk", 8) or "desk"
    role_s = _herdr_token(role or "worker", 6) or "worker"
    node = _herdr_token(node_id or "node", 6) or "node"
    # Trim role/node further if needed so total ≤ 32 (1 + 8 + 6 + 6 = 21 typical).
    candidate = f"o{desk}{role_s}{node}"
    if len(candidate) > AGENT_ID_MAX or not HERDR_NAME_RE.match(candidate):
        digest = hashlib.sha1(
            f"{desk_id}:{role}:{node_id}".encode()
        ).hexdigest()
        candidate = ("o" + digest)[:AGENT_ID_MAX]
    return _ensure_herdr_name(candidate)


def _active_desk_ctx() -> dict[str, str]:
    try:
        from . import desks

        d = desks.default_registry().active()
        if d is not None:
            return {
                "desk_id": d.id,
                "thread_id": d.thread_id or f"thread-{d.id}",
                "kind": d.kind,
            }
    except Exception:  # noqa: BLE001
        pass
    return {"desk_id": "desk", "thread_id": "thread", "kind": "auto"}


def labels_for_desk(
    desk: Any | None = None,
    *,
    role: str = "cos",
    node_id: str = "root",
) -> dict[str, Any]:
    """Every Herdr agent label includes desk_id + thread_id."""
    if desk is None:
        ctx = _active_desk_ctx()
        desk_id = ctx["desk_id"]
        thread_id = ctx["thread_id"]
    else:
        desk_id = getattr(desk, "id", None) or (desk.get("id") if isinstance(desk, dict) else None) or "desk"
        thread_id = (
            getattr(desk, "thread_id", None)
            or (desk.get("thread_id") if isinstance(desk, dict) else None)
            or f"thread-{desk_id}"
        )
    agent_id = make_agent_id(str(desk_id), role, node_id)
    return {
        "desk_id": str(desk_id),
        "thread_id": str(thread_id),
        "role": role,
        "node_id": node_id,
        "agent_id": agent_id,
        "label": f"{desk_id} {thread_id}",
        "format": AGENT_ID_FORMAT,
        "focus_desk_id": str(desk_id),
    }


def labels_for_node(node: dag.Node, *, desk: Any | None = None) -> dict[str, Any]:
    role = getattr(node, "role", None) or node.kind or "worker"
    return labels_for_desk(desk, role=str(role), node_id=node.id)


def _agent_id_for(node: dag.Node, *, desk_id: str | None = None, role: str | None = None) -> str:
    ctx = _active_desk_ctx()
    did = desk_id or ctx["desk_id"]
    r = role or getattr(node, "role", None) or node.kind or "worker"
    return make_agent_id(did, str(r), node.id)


def focus_desk(desk_id: str | None = None) -> dict[str, Any]:
    """
    Stub: bidirectional Herdr ↔ okstratr focus sync.

    Records focus_desk_id, makes the standing desk active, and would later
    focus that CoS pane in Herdr. Live pane sync is not wired yet.
    """
    from . import desks as desks_mod

    reg = desks_mod.default_registry()
    target_id = (desk_id or "").strip() or reg.active_id
    if not target_id:
        return {"ok": False, "error": "no desk to focus", "stub": True}
    desk = reg.desks.get(target_id)
    if desk is None or desk.state == "dismissed":
        return {
            "ok": False,
            "error": "unknown or dismissed desk",
            "desk_id": target_id,
            "stub": True,
        }
    # Any non-dismissed desk: focus + activate, always sync DAG + status objective.
    reg.focus_id = desk.id
    reg.active_id = desk.id
    reg._sync_global_dag_from_desk(desk)
    status.set_objective(desk.objective or "")
    # Keep thread_id stable and visible on Herdr labels / status.
    if not (desk.thread_id or "").strip():
        desk.thread_id = f"thread-{desk.id}"
    try:
        from . import okbay

        okbay.remember_desk_thread(desk.id, desk.thread_id)
    except Exception:  # noqa: BLE001 — best-effort stub persistence
        from .logutil import get_logger

        get_logger(__name__).warning("okbay.remember_desk_thread failed", exc_info=True)
    reg.save()
    status.write_status()
    labels = labels_for_desk(desk)
    return {
        "ok": True,
        "stub": True,
        "action": "focus",
        "focus_desk_id": desk.id,
        "desk_id": desk.id,
        "thread_id": desk.thread_id,
        "objective": desk.objective or "",
        "herdr_labels": labels,
        "herdr_sync": "pending",
        "close_warning": CLOSE_WARNING,
        "message": "Focus recorded; live Herdr pane sync not wired yet",
    }


def _run_cmd(
    cmd: list[str],
    *,
    timeout: float,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-2000:],
            "cmd": cmd,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "error": "timeout",
            "timeout": timeout,
            "stdout": ((e.stdout or b"") if isinstance(e.stdout, (bytes, bytearray)) else (e.stdout or ""))[-4000:]
            if e.stdout
            else "",
            "stderr": ((e.stderr or b"") if isinstance(e.stderr, (bytes, bytearray)) else (e.stderr or ""))[-2000:]
            if e.stderr
            else "",
            "cmd": cmd,
        }
    except OSError as e:
        return {"ok": False, "error": str(e), "cmd": cmd}


def _stop_agent(bin_path: str, agent_id: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """Best-effort stop/release — finite-job rule."""
    env = os.environ.copy()
    # Try common stop shapes; first success wins
    candidates = [
        [bin_path, "agent", "stop", agent_id],
        [bin_path, "agent", "kill", agent_id],
        [bin_path, "stop", agent_id],
    ]
    last: dict[str, Any] = {"ok": False, "error": "no stop attempted"}
    for cmd in candidates:
        last = _run_cmd(cmd, timeout=timeout, env=env)
        if last.get("ok") or last.get("returncode") == 0:
            last["stopped"] = True
            return last
        # Non-zero but binary ran — still count as attempted release
        if "returncode" in last:
            last["stopped"] = True
            last["attempted"] = cmd
            return last
    last["stopped"] = False
    return last


def _loads_json_blob(text: str) -> Any | None:
    raw = (text or "").strip()
    if not raw:
        return None
    # Prefer last JSON object/array in the blob (CLI may prefix logs).
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start >= 0 and end > start:
            chunk = raw[start : end + 1]
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                pass
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _herdr_error_message(res: dict[str, Any], *, fallback: str = "herdr failed") -> str:
    """Parse Herdr JSON stderr/stdout errors into a clear string."""
    if not isinstance(res, dict):
        return fallback
    if res.get("error") and res.get("error") not in ("timeout",):
        # Keep structured timeout below after JSON scan
        err = str(res.get("error") or "").strip()
        if err and not err.startswith("{"):
            # Still prefer JSON detail when present
            pass
    for key in ("stderr", "stdout"):
        blob = res.get(key) or ""
        data = _loads_json_blob(str(blob))
        if isinstance(data, dict):
            for k in ("error", "message", "detail", "reason"):
                val = data.get(k)
                if val:
                    code = data.get("code") or data.get("error_code") or data.get("name")
                    if code and str(code) not in str(val):
                        return f"{code}: {val}"
                    return str(val)
            err_obj = data.get("result") if isinstance(data.get("result"), dict) else None
            if err_obj:
                for k in ("error", "message"):
                    if err_obj.get(k):
                        return str(err_obj[k])
            if data.get("ok") is False and data.get("error"):
                return str(data["error"])
    if res.get("error"):
        return str(res["error"])
    stderr = str(res.get("stderr") or "").strip()
    if stderr:
        return stderr.splitlines()[-1][:500]
    stdout = str(res.get("stdout") or "").strip()
    if stdout:
        return stdout.splitlines()[-1][:500]
    rc = res.get("returncode")
    if rc not in (None, 0):
        return f"{fallback} (rc={rc})"
    return fallback


def _cmd_payload(res: dict[str, Any]) -> Any | None:
    for key in ("stdout", "stderr"):
        data = _loads_json_blob(str(res.get(key) or ""))
        if data is not None:
            return data
    return None


def _pane_id_from_obj(obj: Any) -> str | None:
    if isinstance(obj, str) and obj.strip():
        return obj.strip()
    if not isinstance(obj, dict):
        return None
    for key in ("pane_id", "id", "paneId"):
        val = obj.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    pane = obj.get("pane")
    if isinstance(pane, dict):
        return _pane_id_from_obj(pane)
    return None


def _iter_panes(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, list):
        return [p for p in data if isinstance(p, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("panes", "items", "windows"):
        val = data.get(key)
        if isinstance(val, list):
            return [p for p in val if isinstance(p, dict)]
    result = data.get("result")
    if isinstance(result, dict):
        return _iter_panes(result)
    if isinstance(result, list):
        return [p for p in result if isinstance(p, dict)]
    # Single pane object
    if _pane_id_from_obj(data):
        return [data]
    return []


def _is_shell_pane(pane: dict[str, Any]) -> bool:
    kind = str(
        pane.get("kind")
        or pane.get("type")
        or pane.get("pane_kind")
        or pane.get("role")
        or ""
    ).lower()
    if kind in ("shell", "terminal", "pty", ""):
        # empty kind: treat as eligible shell-like unless marked agent
        if kind == "" and str(pane.get("agent") or pane.get("agent_id") or "").strip():
            return False
        return True
    return "shell" in kind or "term" in kind


def _is_focused_pane(pane: dict[str, Any]) -> bool:
    for key in ("focused", "is_focused", "active", "is_active"):
        val = pane.get(key)
        if val is True or val == 1 or str(val).lower() in ("1", "true", "yes"):
            return True
    return False


def _pick_base_pane(
    bin_path: str,
    *,
    env: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """herdr pane list JSON → prefer focused shell pane, else first pane."""
    run_env = env if env is not None else os.environ.copy()
    list_res = _run_cmd([bin_path, "pane", "list"], timeout=timeout, env=run_env)
    data = _cmd_payload(list_res)
    panes = _iter_panes(data)
    if not panes:
        return {
            "ok": False,
            "error": _herdr_error_message(list_res, fallback="no panes from herdr pane list"),
            "list": list_res,
            "pane_id": None,
        }
    focused_shell = [p for p in panes if _is_focused_pane(p) and _is_shell_pane(p)]
    shell_panes = [p for p in panes if _is_shell_pane(p)]
    focused = [p for p in panes if _is_focused_pane(p)]
    chosen = (focused_shell or shell_panes or focused or panes)[0]
    pane_id = _pane_id_from_obj(chosen)
    if not pane_id:
        return {
            "ok": False,
            "error": "herdr pane list returned panes without pane_id",
            "list": list_res,
            "pane_id": None,
        }
    return {
        "ok": True,
        "pane_id": pane_id,
        "pane": chosen,
        "list": list_res,
        "count": len(panes),
    }


def _split_seat_pane(
    bin_path: str,
    *,
    cwd: str | None = None,
    direction: str = "right",
    env: dict[str, str] | None = None,
    timeout: float = 30.0,
    shell_wait: float | None = None,
) -> dict[str, Any]:
    """Split from base pane; return new seat pane_id (wait briefly for interactive shell)."""
    run_env = env if env is not None else merge_user_session_env()
    base = _pick_base_pane(bin_path, env=run_env, timeout=min(15.0, timeout))
    if not base.get("ok"):
        return base
    base_id = str(base["pane_id"])
    workdir = (cwd or os.getcwd() or os.path.expanduser("~")).strip() or os.path.expanduser("~")
    direction = (direction or "right").strip() or "right"
    if direction not in ("right", "down", "left", "up"):
        direction = "right"
    cmd = [
        bin_path,
        "pane",
        "split",
        base_id,
        "--direction",
        direction,
        "--cwd",
        workdir,
        "--no-focus",
    ]
    split_res = _run_cmd(cmd, timeout=timeout, env=run_env)
    data = _cmd_payload(split_res)
    pane_id = None
    if isinstance(data, dict):
        result = data.get("result") if isinstance(data.get("result"), dict) else data
        if isinstance(result, dict):
            pane_id = _pane_id_from_obj(result.get("pane") if "pane" in result else result)
        if not pane_id:
            pane_id = _pane_id_from_obj(data)
    if not pane_id and split_res.get("ok"):
        # Some builds print bare id
        for line in str(split_res.get("stdout") or "").splitlines():
            line = line.strip()
            if line and " " not in line and not line.startswith("{"):
                pane_id = line
                break
    if not pane_id or not split_res.get("ok"):
        return {
            "ok": False,
            "error": _herdr_error_message(split_res, fallback="pane split failed"),
            "base_pane_id": base_id,
            "split": split_res,
            "pane_id": None,
            "cmd": cmd,
        }
    wait_s = PANE_SHELL_WAIT_SEC if shell_wait is None else max(0.0, float(shell_wait))
    if wait_s > 0:
        sleep(wait_s)
    return {
        "ok": True,
        "pane_id": pane_id,
        "base_pane_id": base_id,
        "cwd": workdir,
        "direction": direction,
        "split": split_res,
        "cmd": cmd,
        "shell_wait_sec": wait_s,
    }


def _close_pane(
    bin_path: str,
    pane_id: str,
    *,
    env: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Best-effort close of the seat pane only (never the user's base pane)."""
    if not pane_id:
        return {"ok": False, "error": "no pane_id", "closed": False}
    run_env = env if env is not None else os.environ.copy()
    candidates = [
        [bin_path, "pane", "close", pane_id],
        [bin_path, "pane", "close", pane_id, "--force"],
    ]
    last: dict[str, Any] = {"ok": False, "error": "no close attempted", "closed": False}
    for cmd in candidates:
        last = _run_cmd(cmd, timeout=timeout, env=run_env)
        last["cmd"] = cmd
        if last.get("ok") or last.get("returncode") == 0:
            last["closed"] = True
            return last
        if "returncode" in last:
            last["closed"] = True  # attempted; pane may already be gone
            return last
    last["closed"] = False
    return last


def _live_run_node(
    node: dag.Node,
    *,
    bin_path: str,
    timeout: float,
) -> dict[str, Any]:
    """
    Split seat pane → agent start --pane → prompt → wait → always stop + pane close.
    Never leaves the agent or seat pane running after return (finite-job).
    """
    agent_id = _agent_id_for(node)
    prompt = _node_prompt(node)
    kind = (os.environ.get("OKSTRATR_HERDR_KIND") or DEFAULT_KIND).strip() or DEFAULT_KIND
    env = merge_user_session_env()
    env["OKSTRATR_NODE_ID"] = node.id
    env["OKSTRATR_OBJECTIVE"] = prompt

    steps: list[dict[str, Any]] = []
    pane_id: str | None = None
    timeout_ms = max(1000, int(float(timeout) * 1000))

    try:
        split = _split_seat_pane(
            bin_path,
            cwd=os.getcwd(),
            direction="right",
            env=env,
            timeout=min(60.0, max(15.0, timeout)),
        )
        steps.append({"phase": "split", **{k: v for k, v in split.items() if k != "split"}, "detail": split.get("split")})
        if not split.get("ok"):
            return {
                "ok": False,
                "agent_id": agent_id,
                "dry_run": False,
                "steps": steps,
                "error": split.get("error") or "pane split failed",
            }
        pane_id = str(split["pane_id"])

        start_cmd = [
            bin_path,
            "agent",
            "start",
            agent_id,
            "--kind",
            kind,
            "--pane",
            pane_id,
            "--timeout",
            str(timeout_ms),
        ]
        start_res = _run_cmd(start_cmd, timeout=min(60.0, timeout), env=env)
        steps.append({"phase": "start", **start_res})
        if not start_res.get("ok"):
            return {
                "ok": False,
                "agent_id": agent_id,
                "pane_id": pane_id,
                "dry_run": False,
                "steps": steps,
                "error": _herdr_error_message(start_res, fallback="agent start failed"),
            }

        # CLI shapes: `prompt <target> <text> [--wait]` or `prompt <target> -- <text>`
        prompt_cmd = [bin_path, "agent", "prompt", agent_id, prompt, "--wait"]
        prompt_res = _run_cmd(prompt_cmd, timeout=min(60.0, timeout), env=env)
        if not prompt_res.get("ok"):
            alt = [bin_path, "agent", "prompt", agent_id, "--", prompt]
            alt_res = _run_cmd(alt, timeout=min(60.0, timeout), env=env)
            steps.append({"phase": "prompt", "attempt": "with --wait", **prompt_res})
            prompt_res = alt_res
            steps.append({"phase": "prompt", "attempt": "with --", **prompt_res})
        else:
            steps.append({"phase": "prompt", **prompt_res})

        wait_cmd = [bin_path, "agent", "wait", agent_id]
        wait_res = _run_cmd(wait_cmd, timeout=timeout, env=env)
        steps.append({"phase": "wait", **wait_res})

        ok = bool(wait_res.get("ok")) or (
            wait_res.get("returncode") == 0 and "error" not in wait_res
        )
        return {
            "ok": ok,
            "agent_id": agent_id,
            "pane_id": pane_id,
            "dry_run": False,
            "steps": steps,
            "stdout": wait_res.get("stdout") or prompt_res.get("stdout") or "",
            "error": None
            if ok
            else _herdr_error_message(wait_res, fallback="wait failed"),
        }
    finally:
        # Finite-job: always stop agent + close the *seat* pane (not the user's base).
        stop_res = _stop_agent(bin_path, agent_id, timeout=30.0)
        steps.append({"phase": "stop", **stop_res})
        if pane_id:
            close_res = _close_pane(bin_path, pane_id, env=env, timeout=15.0)
            steps.append({"phase": "pane_close", **close_res})


def _dry_run_node(node: dag.Node) -> dict[str, Any]:
    agent_id = _agent_id_for(node)
    prompt = _node_prompt(node)
    kind = (os.environ.get("OKSTRATR_HERDR_KIND") or DEFAULT_KIND).strip() or DEFAULT_KIND
    timeout_ms = max(1000, int(_timeout_sec() * 1000))
    cwd = os.getcwd() or os.path.expanduser("~")
    would = [
        ["herdr", "pane", "list"],
        [
            "herdr",
            "pane",
            "split",
            "<base_pane>",
            "--direction",
            "right",
            "--cwd",
            cwd,
            "--no-focus",
        ],
        [
            "herdr",
            "agent",
            "start",
            agent_id,
            "--kind",
            kind,
            "--pane",
            "<pane_id>",
            "--timeout",
            str(timeout_ms),
        ],
        ["herdr", "agent", "prompt", agent_id, prompt, "--wait"],
        ["herdr", "agent", "wait", agent_id],
        ["herdr", "agent", "stop", agent_id],
        ["herdr", "pane", "close", "<pane_id>"],
    ]
    return {
        "ok": True,
        "agent_id": agent_id,
        "dry_run": True,
        "would_exec": would,
        "message": f"dry-run seat for {node.id}",
    }


def run_one(
    node_id: str,
    *,
    dry_run: bool | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Seat a single DAG node via Herdr (or dry-run). Always releases the agent."""
    use_dry = dry_run_enabled(dry_run)
    g = dag.default_dag()
    g.refresh_ready(save=False)
    node = g.nodes.get(node_id)
    if node is None:
        return {"ok": False, "error": f"unknown node: {node_id}", "node_id": node_id}

    g.set_state(node_id, "running", save=True)
    blackboard.post(
        f"herdr seat start: {node_id} ({'dry-run' if use_dry else 'live'})",
        author="herdr",
        kind="note",
        tags=["herdr", "seat", "start"],
        provenance="okstratr.herdr.run_one",
        node_id=node_id,
    )

    t0 = time()
    try:
        if use_dry:
            result = _dry_run_node(node)
        else:
            bin_path = herdr_bin()
            if not bin_path:
                result = {
                    "ok": False,
                    "error": "Herdr not on PATH",
                    "dry_run": False,
                    "hint": "Set OKSTRATR_HERDR_DRY_RUN=1 for tests, or install herdr",
                }
            else:
                result = _live_run_node(
                    node,
                    bin_path=bin_path,
                    timeout=timeout if timeout is not None else _timeout_sec(),
                )
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "error": str(e), "dry_run": use_dry}

    elapsed = time() - t0
    result["node_id"] = node_id
    result["elapsed_sec"] = round(elapsed, 3)
    labels = labels_for_node(node)
    result["herdr_labels"] = labels
    result.setdefault("agent_id", labels["agent_id"])

    # Re-load in case another writer touched state
    g = dag.default_dag(force_reload=True)
    if result.get("ok"):
        notes = "herdr dry-run ok" if result.get("dry_run") else "herdr seat ok"
        if result.get("stdout"):
            notes = f"{notes}: {str(result['stdout'])[:500]}"
        g.mark_done(node_id, notes=notes, save=True)
        blackboard.post(
            f"herdr seat done: {node_id}",
            author="herdr",
            kind="evidence",
            tags=["herdr", "seat", "done"],
            provenance="okstratr.herdr.run_one",
            node_id=node_id,
        )
        result["state"] = "done"
    else:
        err = str(result.get("error") or "failed")
        g.mark_failed(node_id, notes=f"herdr seat failed: {err}"[:1000], save=True)
        blackboard.post(
            f"herdr seat failed: {node_id}: {err}",
            author="herdr",
            kind="note",
            tags=["herdr", "seat", "failed"],
            provenance="okstratr.herdr.run_one",
            node_id=node_id,
        )
        result["state"] = "failed"

    status.write_status()
    try:
        from . import desks as desks_mod

        quieted = desks_mod.maybe_quiet_if_finished()
        if quieted.get("action") == "auto_quiet":
            result["desk_quieted"] = quieted
    except Exception:  # noqa: BLE001
        pass
    return result


def run_ready(
    *,
    limit: int = DEFAULT_LIMIT,
    dry_run: bool | None = None,
    timeout: float | None = None,
    skip_root: bool = True,
) -> dict[str, Any]:
    """
    For each ready node (up to limit): start/prompt/wait via Herdr, update DAG +
    blackboard, then stop the agent. Finite jobs only.

    dry_run defaults from OKSTRATR_HERDR_DRY_RUN.
    """
    use_dry = dry_run_enabled(dry_run)
    lim = max(0, int(limit))
    g = dag.default_dag()
    g.refresh_ready(save=True)

    def _ready_list() -> list:
        cur = dag.default_dag(force_reload=True)
        cur.refresh_ready(save=True)
        nodes = list(cur.ready())
        if skip_root:
            nodes = [n for n in nodes if n.id != "root" and n.kind != "root"]
        return nodes

    ready_before = _ready_list()
    results: list[dict[str, Any]] = []
    ran_ids: set[str] = set()
    while len(results) < lim:
        ready = [n for n in _ready_list() if n.id not in ran_ids]
        if not ready:
            break
        n = ready[0]
        ran_ids.add(n.id)
        results.append(run_one(n.id, dry_run=use_dry, timeout=timeout))

    g = dag.default_dag(force_reload=True)
    g.refresh_ready(save=True)
    status.write_status()

    desk_quieted = None
    try:
        from . import desks as desks_mod

        desk_quieted = desks_mod.maybe_quiet_if_finished()
    except Exception:  # noqa: BLE001
        desk_quieted = None

    ctx = _active_desk_ctx()
    out = {
        "ok": all(r.get("ok") for r in results) if results else True,
        "dry_run": use_dry,
        "limit": lim,
        "ready_before": [n.id for n in ready_before],
        "ran": [r.get("node_id") for r in results],
        "results": results,
        "ready_after": [
            n.id
            for n in g.ready()
            if not (skip_root and (n.id == "root" or n.kind == "root"))
        ],
        "dag": g.summary(),
        "herdr_labels": labels_for_desk(),
        "focus_desk_id": ctx["desk_id"],
        "agent_id_format": AGENT_ID_FORMAT,
    }
    if desk_quieted is not None:
        out["desk_quieted"] = desk_quieted
    return out
