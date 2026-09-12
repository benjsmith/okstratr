"""Herdr bridge — launch/focus UI + finite-job seat for ready DAG nodes.

Role split: Herdr = runtime; okstratr = desk brain (DAG/CoS/blackboard).
Finite-job rule: always stop/release agents after a node; never leave them running.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from time import time
from typing import Any

from . import blackboard, dag, status

DEFAULT_KIND = "grok"
DEFAULT_TIMEOUT_SEC = 120
DEFAULT_LIMIT = 1
AGENT_ID_MAX = 64
AGENT_ID_FORMAT = "okstratr-{desk}-{role}-{node}"

# QML close-dialog copy (bind status.ui.close_warning). Kernel suspends; desks quiet.
CLOSE_WARNING = (
    "Closing Okstratr will shut down the kernel. "
    "Standing desks will suspend (quiet) and the session returns to regular Herdr. "
    "Continue?"
)


def herdr_bin() -> str | None:
    return shutil.which("herdr") or shutil.which("omarchy-herdr")


def _launch_candidates(objective: str = "") -> list[list[str]]:
    """Ordered Omarchy-friendly Herdr launch commands (only bins that exist)."""
    obj = (objective or "").strip()
    out: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def add(cmd: list[str]) -> None:
        key = tuple(cmd)
        if key not in seen:
            seen.add(key)
            out.append(cmd)

    for name in ("herdr", "omarchy-herdr"):
        path = shutil.which(name)
        if path:
            add([path] + ([obj] if obj else []))

    uwsm = shutil.which("uwsm-app")
    if uwsm:
        # uwsm may resolve herdr even when our which missed a wrapper
        add([uwsm, "--", "herdr"] + ([obj] if obj else []))
        if shutil.which("omarchy-herdr"):
            add([uwsm, "--", "omarchy-herdr"] + ([obj] if obj else []))

    xdg = shutil.which("xdg-open")
    # Last-resort raise only when no herdr/uwsm candidate — no objective argv
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
    Best-effort: run Herdr with objective as argv / env.

    Tries common Omarchy launchers in order: herdr, omarchy-herdr,
    uwsm-app -- herdr (if present), then xdg-open *.desktop (if present).
    Logs each attempt in the return dict.
    """
    obj = (objective or "").strip()
    env = os.environ.copy()
    if obj:
        env["OKSTRATR_OBJECTIVE"] = obj
        env["HERDR_OBJECTIVE"] = obj
    if focus:
        env["HERDR_FOCUS"] = "1"

    candidates = _launch_candidates(obj)
    if not candidates:
        would = ["herdr", obj] if obj else ["herdr"]
        return {
            "ok": False,
            "dry_run": True,
            "message": "Herdr not on PATH; install native Omarchy Herdr",
            "objective": obj,
            "would_exec": would,
            "attempts": [],
            "candidates": [],
        }

    attempts: list[dict[str, Any]] = []
    for cmd in candidates:
        try:
            subprocess.Popen(cmd, env=env, start_new_session=True)
            attempts.append({"ok": True, "exec": cmd})
            return {
                "ok": True,
                "exec": cmd,
                "objective": obj,
                "attempts": attempts,
                "candidates": candidates,
                "launcher": cmd[0],
            }
        except OSError as e:
            attempts.append({"ok": False, "exec": cmd, "error": str(e)})

    return {
        "ok": False,
        "error": attempts[-1].get("error") if attempts else "no launcher",
        "objective": obj,
        "attempts": attempts,
        "candidates": candidates,
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
    out = []
    for ch in s:
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        else:
            out.append("-")
    return "".join(out)[: max(1, int(max_len))].strip("-") or "okstratr-node"


def _clip(s: str, n: int) -> str:
    return re_sub_safe(s, max_len=n)


def make_agent_id(desk_id: str, role: str, node_id: str) -> str:
    """okstratr-{desk}-{role}-{node} capped safely (filesystem / Herdr id)."""
    desk = _clip(desk_id or "desk", 20)
    role_s = _clip(role or "worker", 16)
    node = _clip(node_id or "node", 16)
    raw = f"okstratr-{desk}-{role_s}-{node}"
    return re_sub_safe(raw, max_len=AGENT_ID_MAX)


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
    reg.focus_id = desk.id
    if desk.state != "dismissed":
        reg.active_id = desk.id
        if desk.state == "working":
            reg._sync_global_dag_from_desk(desk)
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


def _live_run_node(
    node: dag.Node,
    *,
    bin_path: str,
    timeout: float,
) -> dict[str, Any]:
    """
    Start → prompt → wait (bounded) → always stop.
    Never leaves the agent running after return.
    """
    agent_id = _agent_id_for(node)
    prompt = _node_prompt(node)
    kind = (os.environ.get("OKSTRATR_HERDR_KIND") or DEFAULT_KIND).strip() or DEFAULT_KIND
    env = os.environ.copy()
    env["OKSTRATR_NODE_ID"] = node.id
    env["OKSTRATR_OBJECTIVE"] = prompt

    steps: list[dict[str, Any]] = []
    start_cmd = [bin_path, "agent", "start", agent_id, "--kind", kind, "--", prompt]
    start_res = _run_cmd(start_cmd, timeout=min(60.0, timeout), env=env)
    steps.append({"phase": "start", **start_res})

    if not start_res.get("ok"):
        # Still attempt stop in case partial start
        stop_res = _stop_agent(bin_path, agent_id, timeout=30.0)
        steps.append({"phase": "stop", **stop_res})
        return {
            "ok": False,
            "agent_id": agent_id,
            "dry_run": False,
            "steps": steps,
            "error": start_res.get("error") or start_res.get("stderr") or "start failed",
        }

    # Optional explicit prompt (some Herdr builds separate start/prompt)
    prompt_cmd = [bin_path, "agent", "prompt", agent_id, "--", prompt]
    prompt_res = _run_cmd(prompt_cmd, timeout=min(60.0, timeout), env=env)
    steps.append({"phase": "prompt", **prompt_res})

    wait_cmd = [bin_path, "agent", "wait", agent_id]
    wait_res = _run_cmd(wait_cmd, timeout=timeout, env=env)
    steps.append({"phase": "wait", **wait_res})

    # Finite-job rule: always stop/release
    stop_res = _stop_agent(bin_path, agent_id, timeout=30.0)
    steps.append({"phase": "stop", **stop_res})

    ok = bool(wait_res.get("ok")) or (
        wait_res.get("returncode") == 0 and "error" not in wait_res
    )
    return {
        "ok": ok,
        "agent_id": agent_id,
        "dry_run": False,
        "steps": steps,
        "stdout": wait_res.get("stdout") or prompt_res.get("stdout") or "",
        "error": None if ok else (wait_res.get("error") or wait_res.get("stderr") or "wait failed"),
    }


def _dry_run_node(node: dag.Node) -> dict[str, Any]:
    agent_id = _agent_id_for(node)
    prompt = _node_prompt(node)
    kind = (os.environ.get("OKSTRATR_HERDR_KIND") or DEFAULT_KIND).strip() or DEFAULT_KIND
    would = [
        ["herdr", "agent", "start", agent_id, "--kind", kind, "--", prompt],
        ["herdr", "agent", "prompt", agent_id, "--", prompt],
        ["herdr", "agent", "wait", agent_id],
        ["herdr", "agent", "stop", agent_id],
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

    ctx = _active_desk_ctx()
    return {
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
