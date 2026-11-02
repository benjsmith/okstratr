"""The adaptive kernel on live desks, one seat at a time.

Hosts (Herdr, the direct adapter, Switchbay without Herdr, a bare CLI) run
desk DAG nodes as finite seats and say when each is done. After each seat,
``after_seat`` reads what the seat filed with ``okstratr findings add``,
feeds it to the same ``AdaptiveRun`` hook ``run_plan`` uses, and adds any
nodes the kernel buys (expansion, continue wave, verify round) to the desk
DAG as new pending seats. The host's own completion state is never touched:
going past a host's done always means new seats.

State per run: ``runs/<run_id>/live.json`` (plan, results, kernel counters)
next to ``plan.json`` and ``evidence.json``; decisions about the host's done
also go to ``runs/<run_id>/decisions.jsonl`` and the blackboard.
"""

from __future__ import annotations

import fcntl
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import evidence as ev
from . import handback
from . import host_profile as hp
from . import orchestration as orch

LIVE_FILE = "live.json"
DECISIONS_FILE = "decisions.jsonl"


def live_path(run_id: str) -> Path:
    return ev.run_dir(run_id) / LIVE_FILE


@contextmanager
def _run_lock(run_id: str) -> Iterator[None]:
    d = ev.run_dir(run_id)
    d.mkdir(parents=True, exist_ok=True)
    with (d / "live.lock").open("a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _seat_pools(plan: orch.OrchestrationPlan) -> dict[str, Any]:
    harnesses: list[str] = []
    models: dict[str, str] = {}
    critics: list[tuple[str, str | None]] = []
    for n in plan.nodes:
        if n.harness and n.node_type in ("investigate", "execute") and n.harness not in harnesses:
            harnesses.append(n.harness)
        if n.harness and n.model:
            models.setdefault(n.harness, n.model)
        if n.node_type == "verify" and n.harness:
            critics.append((n.harness, n.model))
    return {"harnesses": harnesses, "models_by_harness": models, "critic_pairs": critics}


def load(run_id: str) -> tuple[orch.OrchestrationPlan, orch.RunState, orch.AdaptiveRun] | None:
    rid = ev.safe_run_id(run_id)
    live = _read_json(live_path(rid))
    raw_plan = live.get("plan") or _read_json(ev.run_dir(rid) / "plan.json")
    if not raw_plan:
        return None
    plan = orch.OrchestrationPlan.from_dict(raw_plan)
    state = orch.RunState.from_dict({**(live.get("state") or {}), "plan": plan.to_dict()})
    state.plan = plan
    store = ev.open_run(rid)
    if live.get("kernel"):
        run = orch.AdaptiveRun.from_dict(plan, live["kernel"], store=store)
    else:
        run = orch.AdaptiveRun(plan, store=store, **_seat_pools(plan))
    return plan, state, run


def save(run_id: str, plan: orch.OrchestrationPlan, state: orch.RunState, run: orch.AdaptiveRun) -> None:
    rid = ev.safe_run_id(run_id)
    st = state.to_dict()
    st.pop("plan", None)
    ev.write_json(live_path(rid), {
        "run_id": rid,
        "plan": plan.to_dict(),
        "state": st,
        "kernel": run.to_dict(),
        "updated_at": time.time(),
    })
    ev.save_run(run.store)


def record_decision(run_id: str, event: dict[str, Any], *, desk_id: str | None = None) -> None:
    """Write a host-done decision to the run folder and the blackboard."""
    rid = ev.safe_run_id(run_id)
    path = ev.run_dir(rid) / DECISIONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({**event, "run_id": rid, "at": time.time()}) + "\n")
    try:
        from . import blackboard

        host = event.get("host") or {}
        verb = {"respect": "respecting", "continue": "continuing past", "verify": "verifying after",
                "stop": "stopping at"}.get(str(event.get("action")), str(event.get("action")))
        text = f"okstratr {verb} {host.get('harness', 'host')}'s done: {event.get('reason', '')}"
        tags = ["host-done", str(event.get("action")), f"run:{rid}"]
        if event.get("override"):
            tags.append("override")
        if desk_id:
            tags.append(f"desk:{desk_id}")
        blackboard.Blackboard().post(
            text[:2000], author="okstratr", kind="decision", tags=tags,
            provenance=f"okstratr.live:{rid}", node_id=str(event.get("after") or "") or None,
        )
    except Exception:  # noqa: BLE001
        pass


def _desk_ids(g: Any, run_id: str) -> dict[str, str]:
    return {
        n.plan_node_id: n.id
        for n in g.nodes.values()
        if getattr(n, "plan_node_id", None) and (n.run_id or "") == run_id
    }


def _add_desk_nodes(g: Any, run_id: str, ext: orch.Extension) -> list[str]:
    from . import cos

    mapping = _desk_ids(g, run_id)
    taken = set(g.nodes) | set(getattr(g, "archived_ids", []) or [])
    added: list[str] = []
    for n in ext.nodes:
        did = n.node_id
        i = 1
        while did in taken:
            i += 1
            did = f"{n.node_id}-{i}"
        taken.add(did)
        mapping[n.node_id] = did
        deps = [mapping.get(d, d) for d in n.dependencies]
        role = n.role or cos._ROLE_FOR_TYPE.get(n.node_type, "worker")
        g.add(
            did,
            f"{cos._TITLE_FOR_TYPE.get(n.node_type, 'Work')}: {n.objective}"[:200],
            depends_on=[d for d in deps if d in g.nodes],
            kind=role,
            role=role,
            objective=n.objective,
            state="pending",
            prefer_harness=n.harness,
            prefer_model=n.model,
            node_type=n.node_type,
            run_id=run_id,
            plan_node_id=n.node_id,
            method_hint=n.method_hint,
            retrieval_query=n.retrieval_query,
            independence=n.independence,
            save=False,
        )
        added.append(did)
    for pnid, deps in ext.rewire.items():
        did = mapping.get(pnid)
        if did and did in g.nodes and g.nodes[did].state in ("pending", "ready", "blocked"):
            g.nodes[did].depends_on = [mapping.get(d, d) for d in deps if mapping.get(d, d) in g.nodes]
    g.refresh_ready(save=False)
    g.save()
    return added


def after_seat(
    g: Any,
    node: Any,
    *,
    ok: bool,
    tokens: int = 0,
    latency_s: float = 0.0,
    error: str = "",
    harness: str | None = None,
    host: str | None = None,
    desk_id: str | None = None,
) -> dict[str, Any]:
    """Run the kernel after the host says one desk seat is done."""
    rid = getattr(node, "run_id", None)
    pnid = getattr(node, "plan_node_id", None)
    if not rid or not pnid:
        return {"action": "noop", "reason": "not an orchestration seat"}
    rid = ev.safe_run_id(rid)
    with _run_lock(rid):
        loaded = load(rid)
        if loaded is None:
            return {"action": "noop", "reason": "no plan for run"}
        plan, state, run = loaded
        pnode = plan.node_map().get(pnid)
        if pnode is None:
            return {"action": "noop", "reason": f"{pnid} not in plan"}
        if pnid in state.results:
            return {"action": "noop", "reason": "already recorded"}
        data = handback.read(rid, pnid)
        text = handback.result_text(pnode.node_type, data)
        try:
            tok = int((data or {}).get("tokens") or tokens or 0)
        except (TypeError, ValueError):
            tok = int(tokens or 0)
        res = orch.NodeResult(
            node_id=pnid, ok=bool(ok), text=text, tokens=tok,
            latency_s=float(latency_s or 0.0), error=error or "",
            data={"handback": bool(data)},
        )
        state.results[pnid] = res
        if run.host is None:
            run.host = hp.profile_for(harness or node.prefer_harness or pnode.harness, host=host)
        events: list[dict[str, Any]] = []
        run.on_decision = events.append
        out = run(plan, state, res)
        ext = out if isinstance(out, orch.Extension) else orch.Extension(nodes=list(out or []))
        added: list[str] = []
        if ext.nodes:
            bounds = plan.bounds.clamp()
            started = set(state.results)
            if orch._apply_extension(plan, ext, bounds, started):
                added = _add_desk_nodes(g, rid, ext)
            else:
                run.events.append({"after": pnid, "kind": "extension", "applied": False,
                                   "reason": "would break a limit"})
        if pnode.node_type == "verify":
            try:
                ev.promote_supported(run.store, desk_id=desk_id)
            except Exception:  # noqa: BLE001
                pass
        save(rid, plan, state, run)
    for e in events:
        record_decision(rid, e, desk_id=desk_id)
    if not data:
        try:
            from . import blackboard

            blackboard.Blackboard().post(
                f"{pnid} finished without filing findings (okstratr findings add)",
                author="okstratr", kind="note", tags=["findings", "missing", f"run:{rid}"],
                provenance=f"okstratr.live:{rid}", node_id=pnid,
            )
        except Exception:  # noqa: BLE001
            pass
    return {
        "action": "extend" if added else "recorded",
        "run_id": rid,
        "plan_node_id": pnid,
        "added": added,
        "handback": bool(data),
        "stop_reason": run.stop_reason,
        "decisions": events,
    }


def node_finished(
    g: Any,
    node_id: str,
    *,
    ok: bool,
    host: str | None,
    tokens: int = 0,
    latency_s: float = 0.0,
    error: str = "",
    harness: str | None = None,
    desk_id: str | None = None,
) -> dict[str, Any] | None:
    """Host-agnostic entry: call right after a host marks a desk node done/failed.

    Returns None for nodes outside an orchestration run. Never raises.
    """
    try:
        node = g.nodes.get(node_id)
        if node is None or not getattr(node, "run_id", None) or not getattr(node, "plan_node_id", None):
            return None
        if desk_id is None:
            try:
                from . import herdr

                desk_id = herdr._active_desk_ctx().get("desk_id")
            except Exception:  # noqa: BLE001
                desk_id = None
        return after_seat(
            g, node, ok=ok, tokens=tokens, latency_s=latency_s, error=error,
            harness=harness, host=host, desk_id=desk_id,
        )
    except Exception as e:  # noqa: BLE001
        return {"action": "error", "error": str(e)}
