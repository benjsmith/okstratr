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


def herdr_bin() -> str | None:
    return shutil.which("herdr") or shutil.which("omarchy-herdr")


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
    if focus:
        env["HERDR_FOCUS"] = "1"
    try:
        subprocess.Popen(cmd, env=env, start_new_session=True)
        return {"ok": True, "exec": cmd, "objective": obj}
    except OSError as e:
        return {"ok": False, "error": str(e), "exec": cmd, "objective": obj}


def focus(objective: str = "") -> dict[str, Any]:
    """Focus / reopen Herdr on the given (or seated) objective."""
    obj = (objective or "").strip() or status.get_objective()
    return launch(obj, focus=True)


def _node_prompt(node: dag.Node) -> str:
    parts = [node.title or node.id]
    if node.objective:
        parts.append(node.objective)
    return " — ".join(parts)


def _agent_id_for(node: dag.Node) -> str:
    # Herdr agent ids: keep short, stable, filesystem-safe
    raw = f"okstratr-{node.id}"
    return re_sub_safe(raw)


def re_sub_safe(s: str) -> str:
    out = []
    for ch in s:
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        else:
            out.append("-")
    return "".join(out)[:64].strip("-") or "okstratr-node"


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
    }
