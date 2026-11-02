"""Run the orchestration kernel outside a desk: ``okstratr run`` and ``okstratr loop``.

``run_once`` plans an objective (or uses a given recipe), runs it with
``run_plan`` and ``AdaptiveRun``, and files the outcome with the learner.
Seats run through the direct adapter or the file queue (``harness.queue``);
either way each seat files its result with ``okstratr findings add``.

``run_loop`` is the time-boxed or scheduled case: okstratr owns the loop
and does not rely on the resident harness to keep going. It runs rounds
until the objective is met with no open gaps, the time box or token budget
ends, or a round adds nothing new, checkpoints after every round
(``runs/<run_id>/loop.json``) and always records an explicit stop reason.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from . import evidence as ev
from . import handback
from . import host_profile as hp
from . import orchestration as orch
from . import orchestration_utility as ou

RunnerFactory = Callable[[str, orch.AdaptiveRun], orch.Runner]


def make_plan(
    objective: str,
    *,
    run_id: str,
    recipe: str | None = None,
    effort: float = 0.5,
    harnesses: list[str] | None = None,
    task_type: str = "",
) -> orch.OrchestrationPlan:
    from . import cos

    if recipe:
        harns, models_by, pairs = cos._models_for_run(
            harnesses, None, effort=effort, desk_id=None,
            task_class=ou.extract_features(objective).kind(),
        )
        feat = ou.extract_features(
            objective, preference=effort, provider_diversity=len(harns) or 1, task_type=task_type,
        )
        decision = ou.decision_for_arm(recipe, feat, reason=f"recipe forced: {recipe}")
        if decision is None:
            raise ValueError(f"unknown recipe: {recipe}")
        plan = orch.plan_from_decision(
            objective, decision, harnesses=harns, models_by_harness=models_by, run_id=run_id,
            critic_pairs=pairs,
        )
        return orch.ensure_valid(plan)
    _, plan = cos.plan_for(objective, effort=effort, harnesses=harnesses, run_id=run_id, task_type=task_type)
    return plan


def suffix_nodes(plan: orch.OrchestrationPlan, suffix: str) -> orch.OrchestrationPlan:
    """Rename every node (and its dependencies) so later rounds never reuse ids."""
    if not suffix:
        return plan
    for n in plan.nodes:
        n.node_id = f"{n.node_id}{suffix}"
        n.dependencies = [f"{d}{suffix}" for d in n.dependencies]
    return plan


def _save_store_hook(run: orch.AdaptiveRun, run_id: str) -> orch.AfterNode:
    """after_node that keeps evidence.json current so seats can read it."""

    def hook(plan: orch.OrchestrationPlan, state: orch.RunState, res: orch.NodeResult) -> Any:
        out = run(plan, state, res)
        run.store.persist(ev.run_evidence_path(run_id))
        return out

    return hook


def _record(run_id: str, event: dict[str, Any]) -> None:
    from . import live

    live.record_decision(run_id, event)


def run_once(
    objective: str,
    runner_factory: RunnerFactory,
    *,
    run_id: str | None = None,
    recipe: str | None = None,
    effort: float = 0.5,
    harnesses: list[str] | None = None,
    host: hp.HostProfile | None = None,
    budget: hp.Budget | None = None,
    plan: orch.OrchestrationPlan | None = None,
    store: Any | None = None,
    owner_loop: bool = False,
    base_tokens: float = 0.0,
    learn: bool = True,
    node_suffix: str = "",
) -> dict[str, Any]:
    rid = ev.safe_run_id(run_id or ev.new_run_id("run"))
    if plan is None:
        plan = make_plan(objective, run_id=rid, recipe=recipe, effort=effort, harnesses=harnesses)
        plan = suffix_nodes(plan, node_suffix)
    plan.run_id = rid
    d = ev.run_dir(rid)
    d.mkdir(parents=True, exist_ok=True)
    ev.write_json(d / "plan.json", plan.to_dict())
    pools = {
        "harnesses": [n.harness for n in plan.nodes if n.harness and n.node_type == "investigate"],
        "models_by_harness": {n.harness: n.model for n in plan.nodes if n.harness and n.model},
        "critic_pairs": [(n.harness, n.model) for n in plan.nodes if n.node_type == "verify" and n.harness],
    }
    pools["harnesses"] = list(dict.fromkeys(pools["harnesses"]))
    run = orch.AdaptiveRun(
        plan,
        store=store if store is not None else ev.RunEvidence(rid),
        host=host if host is not None else hp.profile_for(
            (plan.nodes[-1].harness if plan.nodes else None) or "unknown"),
        budget=budget,
        owner_loop=owner_loop,
        on_decision=lambda e: _record(rid, e),
        base_tokens=base_tokens,
        **pools,
    )
    runner = runner_factory(rid, run)
    state = orch.run_plan(plan, runner, after_node=_save_store_hook(run, rid), checkpoint=d / "state.json")
    run.store.persist(ev.run_evidence_path(rid))
    final = state.final()
    tel = orch.run_telemetry(state, run)
    out = {
        "run_id": rid,
        "recipe": str((plan.decision or {}).get("arm_id") or recipe or ""),
        "answer": (final.text if final else ""),
        "objective_met": run.objective_met,
        "stop_reason": run.stop_reason or state.stopped or "plan finished",
        "tokens": state.tokens(),
        "latency_s": round(state.critical_path_s(), 3),
        "nodes": len(plan.nodes),
        "failed_nodes": len(state.failed),
        "unique_claims": run.unique_claims(),
        "host_decisions": list(run.host_decisions),
        "events": list(run.events),
        "telemetry": tel,
    }
    ev.write_json(d / "result.json", out)
    if learn:
        try:
            orch.record_run(state, run)
        except Exception:  # noqa: BLE001
            pass
    out["_run"] = run
    return out


def _gap_objective(objective: str, last: dict[str, Any]) -> str:
    gaps = [e.get("gaps") or [] for e in last.get("host_decisions") or []]
    flat = [g for gs in gaps for g in gs]
    if not flat:
        return objective
    return f"{objective}\n\nStill open from the last round: " + "; ".join(flat[:5])


def run_loop(
    objective: str,
    runner_factory: RunnerFactory,
    *,
    run_id: str | None = None,
    for_seconds: float | None = None,
    max_tokens: float | None = None,
    max_rounds: int = 12,
    recipe: str | None = None,
    effort: float = 0.5,
    harnesses: list[str] | None = None,
    host: hp.HostProfile | None = None,
    clock: Callable[[], float] = time.time,
    resume: bool = False,
) -> dict[str, Any]:
    """Time-boxed run that okstratr owns. Always ends with an explicit stop reason."""
    rid = ev.safe_run_id(run_id or ev.new_run_id("loop"))
    d = ev.run_dir(rid)
    d.mkdir(parents=True, exist_ok=True)
    ckpt = d / "loop.json"
    loop: dict[str, Any] = {}
    if resume and ckpt.exists():
        loop = json.loads(ckpt.read_text(encoding="utf-8"))
    if not loop:
        now = clock()
        loop = {
            "run_id": rid,
            "objective": objective,
            "started_at": now,
            "deadline": (now + float(for_seconds)) if for_seconds else None,
            "max_tokens": max_tokens,
            "rounds": [],
            "tokens": 0,
            "stop_reason": "",
        }
    loop["stop_reason"] = ""
    store = ev.RunEvidence.load(ev.run_evidence_path(rid), rid) if resume else ev.RunEvidence(rid)
    budget = hp.Budget(max_tokens=loop.get("max_tokens"), deadline=loop.get("deadline"))

    def checkpoint() -> None:
        store.persist(ev.run_evidence_path(rid))
        ev.write_json(ckpt, loop)

    last: dict[str, Any] = loop["rounds"][-1] if loop["rounds"] else {}
    while True:
        budget.spent_tokens = float(loop["tokens"])
        if budget.past_deadline(clock()):
            loop["stop_reason"] = "time box reached"
            break
        if budget.exhausted():
            loop["stop_reason"] = "budget exhausted"
            break
        if len(loop["rounds"]) >= max_rounds:
            loop["stop_reason"] = f"round limit ({max_rounds})"
            break
        n = len(loop["rounds"]) + 1
        round_id = f"{rid}-r{n}"
        before = len({" ".join(f.claim.lower().split()) for f in store.findings if f.claim.strip()})
        res = run_once(
            _gap_objective(objective, last) if last else objective,
            runner_factory,
            run_id=round_id,
            recipe=recipe,
            effort=effort,
            harnesses=harnesses,
            host=host,
            budget=hp.Budget(max_tokens=budget.max_tokens, deadline=budget.deadline),
            store=store,
            owner_loop=True,
            base_tokens=float(loop["tokens"]),
            node_suffix=f"-r{n}" if n > 1 else "",
        )
        res.pop("_run", None)
        after = len({" ".join(f.claim.lower().split()) for f in store.findings if f.claim.strip()})
        loop["tokens"] = int(loop["tokens"]) + int(res["tokens"])
        last = {k: res[k] for k in ("run_id", "objective_met", "stop_reason", "tokens", "latency_s",
                                    "nodes", "host_decisions")}
        last["new_claims"] = after - before
        prev_answer = loop.get("answer") or ""
        loop["rounds"].append(last)
        loop["answer"] = res["answer"]
        progressed = (after - before) > 0 or bool(res["answer"].strip() and res["answer"] != prev_answer)
        checkpoint()
        open_gaps = any(e.get("gaps") for e in res["host_decisions"][-1:])
        if res["objective_met"] is True and not open_gaps:
            loop["stop_reason"] = "objective met"
            break
        if res["stop_reason"] in ("time box reached", "budget exhausted"):
            loop["stop_reason"] = res["stop_reason"]
            break
        if not progressed:
            loop["stop_reason"] = "no progress: last round added no new findings or answer"
            break
    loop["finished_at"] = clock()
    checkpoint()
    _record(rid, {"kind": "loop_stop", "action": "stop", "override": False,
                  "reason": loop["stop_reason"], "host": {"harness": "okstratr"},
                  "after": "", "gaps": []})
    return loop


def direct_runner_factory(*, timeout: float | None = None) -> RunnerFactory:
    """Seats via the direct CLI adapter; results come only from the handback."""

    def factory(run_id: str, run: orch.AdaptiveRun) -> orch.Runner:
        from . import harness as harness_mod

        cfg = harness_mod.load()

        def runner(node: orch.PlanNode, inputs: dict[str, orch.NodeResult]) -> orch.NodeResult:
            ctx = run.context_for(node) if node.node_type in ("verify", "synthesize") else ""
            prompt = orch.prompt_for(node, inputs, ctx) + "\n\n" + handback.instructions(
                run_id, node.node_id, node.node_type)
            req = harness_mod.SeatRequest(
                node_id=node.node_id, role=node.role or node.node_type,
                prefer_harness=node.harness, prefer_model=node.model, objective=prompt,
                run_id=run_id, plan_node_id=node.node_id,
            )
            seat = harness_mod.choose_harness(req, cfg=cfg, require_installed=True)
            t0 = time.time()
            r = harness_mod.run_direct(req, seat, dry_run=False, timeout=timeout)
            data = handback.read(run_id, node.node_id)
            return orch.NodeResult(
                node_id=node.node_id, ok=bool(r.get("ok")), text=handback.result_text(node.node_type, data),
                tokens=int((data or {}).get("tokens") or r.get("tokens") or 0),
                latency_s=round(time.time() - t0, 3), error=str(r.get("error") or ""),
                data={"handback": bool(data), "adapter": "direct"},
            )

        return runner

    return factory


def queue_runner_factory(*, poll_s: float = 1.0, timeout_s: float | None = None) -> RunnerFactory:
    def factory(run_id: str, run: orch.AdaptiveRun) -> orch.Runner:
        from .harness.queue import QueueRunner

        return QueueRunner(run_id, context_for=run.context_for, poll_s=poll_s, timeout_s=timeout_s)

    return factory
