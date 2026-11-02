"""Typed orchestration plans and a small dependency-aware scheduler.

A plan is a DAG of typed nodes (investigate, verify, synthesize, reduce,
execute). Plans are validated against hard limits before they run; an
invalid plan is repaired, then simplified, and finally replaced by a
single-node plan so a run always has something valid to execute.

The scheduler is runner-agnostic: it calls ``runner(node, inputs)`` for each
ready node and never talks to a model itself.

Where the kernel runs:

- ``run_plan`` drives a whole plan in one process: the benchmark (fake
  runners), ``okstratr run`` (direct seats or the file queue) and the
  time-boxed loop (``okstratr.loop``).
- Live desks (Herdr, the direct adapter, Switchbay) run one seat at a time;
  ``okstratr.live`` calls the same ``AdaptiveRun`` hook after each seat and
  adds any new nodes to the desk DAG.
- Either way a node's answer comes from what the seat filed with
  ``okstratr findings add`` (``okstratr.handback``), never from pane text.
  The host only says when a seat is done.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import orchestration_utility as ou
from .limits import Bounds

PLAN_VERSION = 1

NODE_TYPES = ("investigate", "verify", "synthesize", "reduce", "execute")
INDEPENDENCE_LEVELS = ("low", "medium", "high")
DIFFICULTIES = ("trivial", "normal", "hard")
ACCESS = ("none", "read", "write")
OUTPUT_CONTRACTS = ("findings", "verification", "synthesis", "concat", "reduction")

_DEFAULT_CONTRACT = {
    "investigate": "findings",
    "verify": "verification",
    "synthesize": "synthesis",
    "reduce": "reduction",
    "execute": "findings",
}

# okstratr role names used on the desk DAG for each node type.
ROLE_FOR_TYPE = {
    "investigate": "investigator",
    "verify": "verifier",
    "synthesize": "synthesizer",
    "reduce": "reducer",
    "execute": "executor",
}


@dataclass
class PlanNode:
    node_id: str
    node_type: str
    objective: str
    dependencies: list[str] = field(default_factory=list)
    role: str = ""
    difficulty: str = "normal"
    access: str = "read"
    independence: str = "medium"
    output_contract: str = "findings"
    method_hint: str = ""
    retrieval_query: str = ""
    harness: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> PlanNode:
        if not isinstance(raw, dict):
            raise ValueError("node must be an object")
        deps = raw.get("dependencies") or []
        if not isinstance(deps, list):
            deps = []
        ntype = str(raw.get("node_type") or raw.get("kind") or "").strip()
        return cls(
            node_id=str(raw.get("node_id") or "").strip(),
            node_type=ntype,
            objective=str(raw.get("objective") or "").strip(),
            dependencies=[str(d) for d in deps if d],
            role=str(raw.get("role") or ""),
            difficulty=str(raw.get("difficulty") or "normal"),
            access=str(raw.get("access") or "read"),
            independence=str(raw.get("independence") or "medium"),
            output_contract=str(raw.get("output_contract") or _DEFAULT_CONTRACT.get(ntype, "findings")),
            method_hint=str(raw.get("method_hint") or ""),
            retrieval_query=str(raw.get("retrieval_query") or ""),
            harness=str(raw["harness"]) if raw.get("harness") else None,
            model=str(raw["model"]) if raw.get("model") else None,
        )


@dataclass
class OrchestrationPlan:
    run_id: str
    strategy: str
    nodes: list[PlanNode]
    objective: str = ""
    version: int = PLAN_VERSION
    bounds: Bounds = field(default_factory=Bounds)
    preference: float = ou.PREF_BALANCED
    features: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    allow_expand: bool = False
    # Ids of nodes dropped from this run; never reused for new nodes.
    archived_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = {
            "version": self.version,
            "run_id": self.run_id,
            "strategy": self.strategy,
            "objective": self.objective,
            "nodes": [n.to_dict() for n in self.nodes],
            "bounds": self.bounds.to_dict(),
            "preference": self.preference,
            "features": self.features,
            "decision": self.decision,
            "allow_expand": self.allow_expand,
        }
        if self.archived_ids:
            out["archived_ids"] = list(self.archived_ids)
        return out

    @classmethod
    def from_dict(cls, raw: Any) -> OrchestrationPlan:
        if not isinstance(raw, dict):
            raise ValueError("plan must be an object")
        nodes_raw = raw.get("nodes") or []
        if not isinstance(nodes_raw, list):
            raise ValueError("plan.nodes must be an array")
        return cls(
            run_id=str(raw.get("run_id") or raw.get("orchestration_id") or ""),
            strategy=str(raw.get("strategy") or "single"),
            nodes=[PlanNode.from_dict(n) for n in nodes_raw],
            objective=str(raw.get("objective") or ""),
            version=int(raw.get("version") or PLAN_VERSION),
            bounds=Bounds.from_dict(raw.get("bounds")),
            preference=ou.clamp_preference(raw.get("preference")),
            features=raw.get("features") if isinstance(raw.get("features"), dict) else {},
            decision=raw.get("decision") if isinstance(raw.get("decision"), dict) else {},
            allow_expand=bool(raw.get("allow_expand")),
            archived_ids=[str(x) for x in (raw.get("archived_ids") or []) if isinstance(x, str) and x],
        )

    def node_map(self) -> dict[str, PlanNode]:
        return {n.node_id: n for n in self.nodes}

    def reserved_ids(self) -> set[str]:
        return set(self.node_map()) | set(self.archived_ids)

    def retire(self, node_id: str) -> bool:
        """Drop a node that nothing depends on; its id stays reserved."""
        if node_id not in self.node_map():
            return False
        if any(node_id in n.dependencies for n in self.nodes):
            return False
        self.nodes = [n for n in self.nodes if n.node_id != node_id]
        if node_id not in self.archived_ids:
            self.archived_ids.append(node_id)
        return True

    def alloc_node_id(self, base: str, taken: set[str] | None = None) -> str:
        """First free id from ``base``, ``base-2``, … (live and retired ids are taken)."""
        used = self.reserved_ids() | set(taken or ())
        return _unique_id(base, used)

    def depth(self) -> int:
        return dag_depth(self.nodes)


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:10]}"


# ── validation ─────────────────────────────────────────────────────


def dag_depth(nodes: list[PlanNode]) -> int:
    by_id = {n.node_id: n for n in nodes}
    memo: dict[str, int] = {}

    def _d(nid: str, stack: frozenset[str]) -> int:
        if nid in memo:
            return memo[nid]
        node = by_id.get(nid)
        if node is None or nid in stack:
            return 0
        best = 1 + max((_d(d, stack | {nid}) for d in node.dependencies), default=0)
        memo[nid] = best
        return best

    return max((_d(n.node_id, frozenset()) for n in nodes), default=0)


def has_cycle(nodes: list[PlanNode]) -> bool:
    by_id = {n.node_id: n for n in nodes}
    visiting: set[str] = set()
    seen: set[str] = set()

    def _walk(nid: str) -> bool:
        if nid in seen:
            return False
        if nid in visiting:
            return True
        visiting.add(nid)
        node = by_id.get(nid)
        if node is not None and any(_walk(d) for d in node.dependencies):
            return True
        visiting.discard(nid)
        seen.add(nid)
        return False

    return any(_walk(n.node_id) for n in nodes)


def validate_plan(plan: OrchestrationPlan) -> list[str]:
    """Return a list of problems; empty means valid."""
    errors: list[str] = []
    if not plan.run_id:
        errors.append("missing run_id")
    if not plan.nodes:
        errors.append("plan has no nodes")
    ids = [n.node_id for n in plan.nodes]
    if len(ids) != len(set(ids)):
        errors.append("duplicate node_id")
    if any(not i for i in ids):
        errors.append("empty node_id")
    if set(ids) & set(plan.archived_ids):
        errors.append("node_id reuses a retired id")
    known = set(ids)
    for n in plan.nodes:
        if n.node_type not in NODE_TYPES:
            errors.append(f"{n.node_id}: unknown node_type {n.node_type!r}")
        if not n.objective.strip():
            errors.append(f"{n.node_id}: empty objective")
        for d in n.dependencies:
            if d == n.node_id:
                errors.append(f"{n.node_id}: self-dependency")
            elif d not in known:
                errors.append(f"{n.node_id}: missing dependency {d!r}")
        if n.independence not in INDEPENDENCE_LEVELS:
            errors.append(f"{n.node_id}: bad independence")
        if n.difficulty not in DIFFICULTIES:
            errors.append(f"{n.node_id}: bad difficulty")
        if n.access not in ACCESS:
            errors.append(f"{n.node_id}: bad access")
        elif n.access == "write" and n.node_type != "execute":
            errors.append(f"{n.node_id}: only execute nodes may write")
        if n.output_contract not in OUTPUT_CONTRACTS:
            errors.append(f"{n.node_id}: bad output_contract")
    if has_cycle(plan.nodes):
        errors.append("cycle in dependency graph")
    bounds = plan.bounds.clamp()
    if len(plan.nodes) > bounds.max_nodes:
        errors.append(f"node count {len(plan.nodes)} > max {bounds.max_nodes}")
    depth = dag_depth(plan.nodes)
    if depth > bounds.max_depth:
        errors.append(f"dag depth {depth} > max {bounds.max_depth}")
    return errors


def repair_plan(plan: OrchestrationPlan) -> OrchestrationPlan:
    """Deterministic, local repairs only. Structural problems go to fallback."""
    if not plan.run_id:
        plan.run_id = new_run_id()
    seen: set[str] = set()
    for i, n in enumerate(plan.nodes):
        nid = n.node_id.strip() or f"node-{i}"
        base, k = nid, 2
        while nid in seen:
            nid = f"{base}-{k}"
            k += 1
        seen.add(nid)
        n.node_id = nid
        if n.node_type not in NODE_TYPES:
            n.node_type = "investigate"
        if n.independence not in INDEPENDENCE_LEVELS:
            n.independence = "medium"
        if n.difficulty not in DIFFICULTIES:
            n.difficulty = "normal"
        if n.access not in ACCESS or (n.access == "write" and n.node_type != "execute"):
            n.access = "read"
        if n.output_contract not in OUTPUT_CONTRACTS:
            n.output_contract = _DEFAULT_CONTRACT[n.node_type]
        if not n.role:
            n.role = ROLE_FOR_TYPE[n.node_type]
        if not n.objective.strip():
            n.objective = plan.objective or "(no objective)"
    for n in plan.nodes:
        n.dependencies = [d for d in dict.fromkeys(n.dependencies) if d in seen and d != n.node_id]
    plan.bounds = plan.bounds.clamp()
    return plan


def fallback_plan(plan: OrchestrationPlan, errors: list[str]) -> OrchestrationPlan:
    """Simpler shape (fixed fan-out), then a single node."""
    objective = plan.objective or "user request"
    rid = plan.run_id or new_run_id()
    inv = [n for n in plan.nodes if n.node_type == "investigate"]
    if len(inv) >= 2:
        simple = plan_fixed_fanout(
            objective,
            [{"description": n.objective, "difficulty": n.difficulty} for n in inv],
            run_id=rid,
            preference=plan.preference,
        )
        simple.features = plan.features
        simple.decision = {**plan.decision, "fallback": "fixed_fanout", "errors": errors[:8]}
        if not validate_plan(simple):
            return simple
    single = plan_single(objective, run_id=rid, preference=plan.preference)
    single.decision = {**plan.decision, "fallback": "single", "errors": errors[:8]}
    return single


def ensure_valid(plan: OrchestrationPlan) -> OrchestrationPlan:
    plan = repair_plan(plan)
    errors = validate_plan(plan)
    if not errors:
        return plan
    plan = repair_plan(fallback_plan(plan, errors))
    if not validate_plan(plan):
        return plan
    return plan_single(plan.objective or "user request", run_id=plan.run_id, preference=plan.preference)


# ── plan constructors ──────────────────────────────────────────────


def plan_single(
    objective: str,
    *,
    run_id: str | None = None,
    preference: float = ou.PREF_BALANCED,
) -> OrchestrationPlan:
    node = PlanNode(
        node_id="main",
        node_type="synthesize",
        objective=objective,
        role="investigator",
        output_contract="synthesis",
        independence="low",
    )
    return OrchestrationPlan(
        run_id=run_id or new_run_id(),
        strategy="single",
        nodes=[node],
        objective=objective,
        preference=preference,
        decision={"arm_id": "single"},
    )


def plan_fixed_fanout(
    objective: str,
    tasks: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    preference: float = ou.PREF_BALANCED,
    max_n: int = 4,
) -> OrchestrationPlan:
    """N independent investigators joined by a concatenating merge."""
    n = max(1, min(max_n, len(tasks)))
    nodes: list[PlanNode] = []
    for i, t in enumerate(tasks[:n]):
        diff = str(t.get("difficulty") or "normal")
        nodes.append(
            PlanNode(
                node_id=f"w{i}",
                node_type="investigate",
                objective=str(t.get("description") or objective),
                role="investigator",
                difficulty=diff if diff in DIFFICULTIES else "normal",
            )
        )
    nodes.append(
        PlanNode(
            node_id="merge",
            node_type="synthesize",
            objective=objective,
            dependencies=[x.node_id for x in nodes],
            role="synthesizer",
            output_contract="concat",
            independence="low",
        )
    )
    return OrchestrationPlan(
        run_id=run_id or new_run_id(),
        strategy="fixed_fanout",
        nodes=nodes,
        objective=objective,
        preference=preference,
        decision={"arm_id": f"fixed:{n}", "n": n},
    )


def ready_nodes(plan: OrchestrationPlan, completed: set[str], failed: set[str]) -> list[PlanNode]:
    """Nodes whose dependencies have all finished (failed counts as finished)."""
    done = completed | failed
    return [
        n
        for n in plan.nodes
        if n.node_id not in done and all(d in done for d in n.dependencies)
    ]


# ── scheduler ──────────────────────────────────────────────────────


@dataclass
class NodeResult:
    node_id: str
    ok: bool = True
    text: str = ""
    tokens: int = 0
    latency_s: float = 0.0
    error: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> NodeResult:
        return cls(
            node_id=str(raw.get("node_id") or ""),
            ok=bool(raw.get("ok", True)),
            text=str(raw.get("text") or ""),
            tokens=int(raw.get("tokens") or 0),
            latency_s=float(raw.get("latency_s") or 0.0),
            error=str(raw.get("error") or ""),
            data=raw.get("data") if isinstance(raw.get("data"), dict) else {},
        )


Runner = Callable[[PlanNode, dict[str, NodeResult]], NodeResult]
# Called after each node finishes; may return new nodes to append.
AfterNode = Callable[[OrchestrationPlan, "RunState", NodeResult], "list[PlanNode] | Extension"]


@dataclass
class Extension:
    """Nodes to add as one unit, plus dependency rewiring for unstarted nodes.

    Applied atomically: if the result would break a limit or the plan
    checks, nothing changes.
    """

    nodes: list[PlanNode]
    rewire: dict[str, list[str]] = field(default_factory=dict)
    reason: str = ""


@dataclass
class RunState:
    plan: OrchestrationPlan
    results: dict[str, NodeResult] = field(default_factory=dict)
    expansions: int = 0
    stopped: str = ""
    started_at: float = 0.0
    # Node added mid-run → the node whose result added it (it could not start earlier).
    added_after: dict[str, str] = field(default_factory=dict)

    @property
    def completed(self) -> set[str]:
        return {k for k, r in self.results.items() if r.ok}

    @property
    def failed(self) -> set[str]:
        return {k for k, r in self.results.items() if not r.ok}

    def tokens(self) -> int:
        return sum(r.tokens for r in self.results.values())

    def critical_path_s(self) -> float:
        lat = {k: r.latency_s for k, r in self.results.items()}
        after = self.added_after
        return ou.critical_path_latency(
            self.plan.nodes,
            lambda n: lat.get(n.node_id, 0.0),
            deps_of=lambda n: list(n.dependencies) + ([after[n.node_id]] if n.node_id in after else []),
        )

    def final(self) -> NodeResult | None:
        """Result of the last-finished synthesize node, if any."""
        synth = [n.node_id for n in self.plan.nodes if n.node_type == "synthesize"]
        for nid in reversed(synth):
            r = self.results.get(nid)
            if r is not None:
                return r
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "results": {k: r.to_dict() for k, r in self.results.items()},
            "expansions": self.expansions,
            "stopped": self.stopped,
            "added_after": dict(self.added_after),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RunState:
        res = raw.get("results") if isinstance(raw.get("results"), dict) else {}
        return cls(
            plan=OrchestrationPlan.from_dict(raw.get("plan") or {}),
            results={k: NodeResult.from_dict(v) for k, v in res.items() if isinstance(v, dict)},
            expansions=int(raw.get("expansions") or 0),
            stopped=str(raw.get("stopped") or ""),
            added_after={
                str(k): str(v) for k, v in (raw.get("added_after") or {}).items()
            } if isinstance(raw.get("added_after"), dict) else {},
        )


def save_checkpoint(path: Path, state: RunState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_checkpoint(path: Path) -> RunState | None:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return RunState.from_dict(raw)
    except (ValueError, TypeError):
        return None


def _inputs_for(node: PlanNode, results: dict[str, NodeResult]) -> dict[str, NodeResult]:
    """Successful dependency results only; failed siblings are left out."""
    return {d: results[d] for d in node.dependencies if d in results and results[d].ok}


def run_plan(
    plan: OrchestrationPlan,
    runner: Runner,
    *,
    after_node: AfterNode | None = None,
    checkpoint: Path | None = None,
    resume: RunState | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> RunState:
    """Run a validated plan to completion within its bounds, in one process.

    Used by the benchmark, ``okstratr run`` (direct seats or the file queue)
    and the time-boxed loop. Live desks run one seat at a time instead and
    call the same ``after_node`` hook through ``okstratr.live``.

    Failed nodes count as finished, so dependants still run with whatever
    inputs succeeded. ``after_node`` may append nodes (expansion), but the
    node and depth limits are enforced here regardless of what it returns.
    """
    plan = ensure_valid(plan)
    bounds = plan.bounds.clamp()
    state = resume if resume is not None else RunState(plan=plan)
    state.plan = plan if resume is None else ensure_valid(state.plan)
    plan = state.plan
    state.started_at = clock()
    # A resumed run re-runs nodes that never finished.
    running: dict[Future[NodeResult], tuple[str, float]] = {}

    def _record(res: NodeResult) -> None:
        state.results[res.node_id] = res
        if after_node is not None and not state.stopped:
            try:
                extra = after_node(plan, state, res) or []
            except Exception as exc:  # noqa: BLE001
                extra = []
                state.stopped = f"after_node error: {exc}"
            if isinstance(extra, Extension):
                started = set(state.results) | {nid for nid, _ in running.values()}
                if _apply_extension(plan, extra, bounds, started):
                    state.expansions += 1
                    for n in extra.nodes:
                        state.added_after[n.node_id] = res.node_id
            else:
                for n in _append_nodes(plan, extra, bounds):
                    state.added_after[n.node_id] = res.node_id
        if checkpoint is not None:
            save_checkpoint(checkpoint, state)

    pool = ThreadPoolExecutor(max_workers=bounds.max_concurrency)
    try:
        while True:
            in_flight = {nid for nid, _ in running.values()}
            ready = [
                n
                for n in ready_nodes(plan, state.completed, state.failed)
                if n.node_id not in in_flight
            ]
            elapsed = clock() - state.started_at
            if elapsed > bounds.wall_clock_sec:
                state.stopped = state.stopped or "wall clock limit"
                ready = []
            for n in ready[: max(0, bounds.max_concurrency - len(running))]:
                fut = pool.submit(_safe_run, runner, n, _inputs_for(n, state.results))
                running[fut] = (n.node_id, clock())
            if not running:
                break
            now = clock()
            next_deadline = min(t0 + bounds.worker_timeout_sec for _, t0 in running.values())
            done, _ = wait(
                list(running), timeout=max(0.0, next_deadline - now), return_when=FIRST_COMPLETED
            )
            for fut in done:
                nid, _ = running.pop(fut)
                _record(fut.result())
            now = clock()
            for fut, (nid, t0) in list(running.items()):
                if now - t0 >= bounds.worker_timeout_sec:
                    # The thread cannot be killed; its late result is ignored.
                    fut.cancel()
                    running.pop(fut)
                    _record(NodeResult(node_id=nid, ok=False, error="timeout"))
        # Anything left unrun (wall clock) is recorded as failed.
        for n in plan.nodes:
            if n.node_id not in state.results:
                state.results[n.node_id] = NodeResult(
                    node_id=n.node_id, ok=False, error=state.stopped or "not run"
                )
    finally:
        # Do not wait on a hung worker thread.
        pool.shutdown(wait=False, cancel_futures=True)
    if checkpoint is not None:
        save_checkpoint(checkpoint, state)
    return state


def _safe_run(runner: Runner, node: PlanNode, inputs: dict[str, NodeResult]) -> NodeResult:
    try:
        res = runner(node, inputs)
    except Exception as exc:  # noqa: BLE001
        return NodeResult(node_id=node.node_id, ok=False, error=str(exc)[:500])
    if not isinstance(res, NodeResult):
        return NodeResult(node_id=node.node_id, ok=False, error="runner returned no result")
    res.node_id = node.node_id
    return res


def _append_nodes(plan: OrchestrationPlan, extra: list[PlanNode], bounds: Bounds) -> list[PlanNode]:
    """Append nodes only while the plan stays valid and within limits."""
    added: list[PlanNode] = []
    for n in extra:
        if len(plan.nodes) >= bounds.max_nodes:
            break
        if n.node_id in plan.node_map():
            continue
        plan.nodes.append(n)
        if validate_plan(plan):
            plan.nodes.pop()
            continue
        added.append(n)
    return added


def _apply_extension(plan: OrchestrationPlan, ext: Extension, bounds: Bounds, started: set[str]) -> bool:
    if not ext.nodes or len(plan.nodes) + len(ext.nodes) > bounds.max_nodes:
        return False
    if any(nid in started for nid in ext.rewire):
        return False
    ids = plan.node_map()
    if any(n.node_id in ids or n.node_id in plan.archived_ids for n in ext.nodes):
        return False
    saved = {nid: list(ids[nid].dependencies) for nid in ext.rewire if nid in ids}
    plan.nodes.extend(ext.nodes)
    for nid, deps in ext.rewire.items():
        if nid in ids:
            ids[nid].dependencies = list(deps)
    if validate_plan(plan):
        del plan.nodes[-len(ext.nodes):]
        for nid, deps in saved.items():
            ids[nid].dependencies = deps
        return False
    return True


# ── /work: specialists in sequence ─────────────────────────────────

# (id, writes, title, instruction). writes: "none" | "deliverable" | "review".
PROJECT_SPECIALISTS: dict[str, tuple[str, str, str]] = {
    "context": ("none", "Gather context",
                "Report what is true right now, with sources. Read only; gaps are gaps. "
                "No plan, no messages. For: "),
    "plan": ("deliverable", "Write the plan",
             "Write the plan of record (scope, targets, gates) from the gathered context. "
             "Do not invent metrics. For: "),
    "comms": ("deliverable", "Write the update",
              "Draft the smallest message or briefing that gets the next actions done, "
              "citing the context. For: "),
    "write": ("deliverable", "Do the work",
              "Produce the deliverable from the gathered context. For: "),
    "review": ("review", "Review",
               "Check the deliverable against the context and sources: drift, missing "
               "sources, over-promise. Do not rewrite it. For: "),
}

_PROJECT_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("review", re.compile(r"\b(scope drift|drift|review the plan|challenge the|"
                          r"does (the|this) (plan|update|status) match)\b", re.I)),
    ("comms", re.compile(r"\b(tell the team|team (update|message)|exec(utive)? (deck|update|brief)|"
                         r"community update|slides? for|standup|status update|minimal messages?)\b", re.I)),
    ("plan", re.compile(r"\b(project plan|work-plan|targets?|metrics?|milestones?|"
                        r"set (a )?gate|scope|charter)\b", re.I)),
    ("context", re.compile(r"\b(what is going on|where are we|situation|status of|catch me up)\b", re.I)),
)


def project_specialists(objective: str) -> list[str]:
    """Which specialists a /work brief needs, in run order.

    Hinted specialists if the brief names any, else context → write.
    Context is added in front of any writer, and review after it.
    """
    hinted = [sid for sid, pat in _PROJECT_HINTS if pat.search(objective or "")]
    want = hinted or ["context", "write"]
    writers = [w for w in want if PROJECT_SPECIALISTS[w][0] == "deliverable"]
    if writers and "context" not in want:
        want.insert(0, "context")
    if writers and "review" not in want:
        want.append("review")
    order = ["context", "plan", "comms", "write", "review"]
    return sorted(dict.fromkeys(want), key=order.index)


def plan_projects(
    objective: str,
    *,
    specialists: list[str] | None = None,
    harnesses: list[str] | None = None,
    models_by_harness: dict[str, str] | None = None,
    critic_pairs: list[tuple[str, str | None]] | None = None,
    run_id: str | None = None,
    preference: float = ou.PREF_BALANCED,
) -> OrchestrationPlan:
    """/work shape: gather context → write → review, one specialist each.

    Context has no dependencies, writers wait on context, review waits on
    the writers (or on context when nothing is written) and runs on the
    strongest allowed model. Authors use ``models_by_harness``.
    """
    rid = run_id or new_run_id()
    picks = [s for s in (specialists or project_specialists(objective)) if s in PROJECT_SPECIALISTS]
    harns = [h for h in (harnesses or []) if h]
    author_h = harns[0] if harns else None
    author_m = (models_by_harness or {}).get(author_h) if author_h else None
    nodes: list[PlanNode] = []
    recon: list[str] = []
    writers: list[str] = []
    for sid in picks:
        writes, _title, instr = PROJECT_SPECIALISTS[sid]
        if writes == "none":
            nodes.append(PlanNode(
                node_id=sid, node_type="investigate", objective=instr + objective,
                role="investigator", difficulty="normal", independence="medium",
                output_contract="findings", harness=author_h, model=author_m,
            ))
            recon.append(sid)
        elif writes == "deliverable":
            nodes.append(PlanNode(
                node_id=sid, node_type="synthesize", objective=instr + objective,
                dependencies=list(recon), role="synthesizer", difficulty="hard",
                independence="medium", output_contract="synthesis",
                harness=author_h, model=author_m,
            ))
            writers.append(sid)
        else:
            critic = _critic(critic_pairs, {author_h} if author_h else ())
            vh, vm = critic if critic else ((harns[-1], (models_by_harness or {}).get(harns[-1])) if harns else (None, None))
            nodes.append(PlanNode(
                node_id=sid, node_type="verify", objective=instr + objective,
                dependencies=list(writers or recon), role="verifier", difficulty="hard",
                independence="high", output_contract="verification", harness=vh, model=vm,
            ))
    if not nodes:
        return plan_single(objective, run_id=rid, preference=preference)
    return OrchestrationPlan(
        run_id=rid,
        strategy="projects",
        nodes=nodes,
        objective=objective,
        preference=preference,
        decision={"arm_id": "projects", "specialists": picks},
        allow_expand=False,
        bounds=Bounds(max_concurrency=max(1, len(recon))).clamp(),
    )


# ── plan from a utility decision ───────────────────────────────────


def plan_from_decision(
    objective: str,
    decision: ou.PolicyDecision,
    *,
    tasks: list[dict[str, Any]] | None = None,
    harnesses: list[str] | None = None,
    models_by_harness: dict[str, str] | None = None,
    run_id: str | None = None,
    critic_pairs: list[tuple[str, str | None]] | None = None,
) -> OrchestrationPlan:
    """Build the DAG for a chosen recipe.

    Shape: investigators (and an executor) in parallel → optional reducers
    → optional verifier → synthesizer. The verifier always runs before the
    synthesizer, so the synthesizer only sees checked findings.
    Diverse recipes spread investigators across the given harnesses.
    ``models_by_harness`` are the authors' models. With ``critic_pairs``
    the verifier gets the strongest of them (ties: a harness the
    investigators did not use); without, it gets a spare harness.
    """
    rid = run_id or new_run_id()
    plain_single = (
        decision.n_investigators <= 1 and not decision.include_verify and not decision.include_execute
    )
    if plain_single:
        p = plan_single(objective, run_id=rid, preference=decision.preference)
        p.decision = decision.to_dict()
        p.features = decision.features
        if harnesses:
            p.nodes[0].harness = harnesses[0]
            p.nodes[0].model = (models_by_harness or {}).get(harnesses[0])
        return p

    feat = ou.TaskFeatures.from_dict(decision.features) if decision.features else None
    n = max(1, decision.n_investigators)
    tasks = list(tasks or ou.decompose_tasks(objective, n, feat))
    while len(tasks) < n:
        tasks.append({"description": objective, "difficulty": "normal"})
    hints = ou.method_hints_for(n, decision.independence, feat)
    harns = [h for h in (harnesses or []) if h]
    models = models_by_harness or {}
    diverse = decision.diversity == "diverse" and len(harns) >= 2

    def _alloc(i: int) -> tuple[str | None, str | None]:
        if not harns:
            return None, None
        h = harns[i % len(harns)] if diverse else harns[0]
        return h, models.get(h)

    nodes: list[PlanNode] = []
    investigators: list[PlanNode] = []
    for i in range(n):
        t = tasks[i]
        hint = str(t.get("method_hint") or (hints[i] if i < len(hints) else ""))
        rq = str(t.get("retrieval_query") or "").strip() or ou.retrieval_query_for(
            str(t.get("description") or objective), hint
        )
        h, m = _alloc(i)
        diff = str(t.get("difficulty") or "normal")
        investigators.append(
            PlanNode(
                node_id=f"inv-{i}",
                node_type="investigate",
                objective=str(t.get("description") or objective),
                role="investigator",
                difficulty=diff if diff in DIFFICULTIES else "normal",
                independence=decision.independence,
                method_hint=hint,
                retrieval_query=rq[:240],
                harness=h,
                model=m,
            )
        )
    nodes.extend(investigators)
    tails = [x.node_id for x in investigators]

    exec_id: str | None = None
    if decision.include_execute:
        exec_id = "exec"
        nodes.append(
            PlanNode(
                node_id=exec_id,
                node_type="execute",
                objective=f"Run the measurement or protocol needed to resolve: {objective[:240]}",
                role="executor",
                access="write",
                independence="low",
            )
        )

    if decision.include_reduce and n >= 5:
        tails = add_reducers(nodes, investigators)

    join = list(tails) + ([exec_id] if exec_id else [])
    if decision.include_verify:
        # Prefer a harness none of the investigators used.
        used = {x.harness for x in investigators if x.harness}
        critic = _critic(critic_pairs, used)
        if critic is not None:
            vh, vm = critic
        else:
            spare = [h for h in harns if h not in used]
            vh = spare[0] if spare else (harns[-1] if harns else None)
            vm = models.get(vh) if vh else None
        nodes.append(
            PlanNode(
                node_id="verify",
                node_type="verify",
                objective=f"Check each finding against its sources for: {objective[:240]}",
                dependencies=list(join),
                role="verifier",
                difficulty="hard",
                independence="high",
                output_contract="verification",
                harness=vh,
                model=vm,
            )
        )
        join = ["verify"]

    nodes.append(
        PlanNode(
            node_id="synth",
            node_type="synthesize",
            objective=objective,
            dependencies=list(join),
            role="synthesizer",
            difficulty="hard" if decision.include_verify else "normal",
            independence="low",
            output_contract="synthesis",
        )
    )
    wave = n + (1 if exec_id else 0)
    return OrchestrationPlan(
        run_id=rid,
        strategy=decision.strategy,
        nodes=nodes,
        objective=objective,
        preference=decision.preference,
        features=decision.features,
        decision=decision.to_dict(),
        allow_expand=decision.allow_expand,
        bounds=Bounds(max_concurrency=max(1, wave)).clamp(),
    )


def _critic(pairs: list[tuple[str, str | None]] | None, used: Any = ()) -> tuple[str, str | None] | None:
    if not pairs:
        return None
    from . import model_policy

    return model_policy.pick_critic(list(pairs), avoid_harnesses=used)


def _reverify_seat(
    pairs: list[tuple[str, str | None]] | None,
    alloc: list[str | None],
    models: dict[str, str],
) -> tuple[str | None, str | None]:
    """Seat for a re-verify: the strongest allowed model, on the harness the
    spread picked when that harness has one of the strongest models."""
    fresh = alloc[-1] if alloc else None
    if not pairs:
        return fresh, (models.get(fresh) if fresh else None)
    from . import model_policy

    top = max(model_policy.model_strength(m) for _, m in pairs)
    best = [p for p in pairs if model_policy.model_strength(p[1]) == top]
    on_fresh = [p for p in best if p[0] == fresh]
    if on_fresh:
        return on_fresh[0]
    return model_policy.pick_critic(best, avoid_harnesses=[h for h in alloc[:-1] if h])


def add_reducers(nodes: list[PlanNode], investigators: list[PlanNode]) -> list[str]:
    """Pairwise reducers between a wide fan-out and the verifier.

    Offline runs feed each reducer only its siblings' findings; on a live
    desk it is an ordinary seat.
    """
    reducers: list[PlanNode] = []
    for r, start in enumerate(range(0, len(investigators), 2)):
        group = investigators[start : start + 2]
        reducers.append(
            PlanNode(
                node_id=f"red-{r}",
                node_type="reduce",
                objective="Merge sibling findings without adding claims; keep conflicts.",
                dependencies=[g.node_id for g in group],
                role="reducer",
                difficulty="trivial",
                independence="low",
                output_contract="reduction",
            )
        )
    nodes.extend(reducers)
    return [x.node_id for x in reducers]


# ── expansion: more investigators while ΔU > threshold ─────────────


def _least_used_harnesses(plan: OrchestrationPlan, harnesses: list[str] | None, k: int) -> list[str | None]:
    """Spread new seats over the harnesses used least so far.

    The first ``k - 1`` seats are investigators: they go to the harnesses
    that have investigated least (a harness that only verified is a fresh
    source). The last seat is the verifier: it prefers a harness none of the
    new investigators use.
    """
    harns = [h for h in (harnesses or []) if h]
    if not harns:
        return [None] * k
    inv_counts = {h: 0 for h in harns}
    all_counts = {h: 0 for h in harns}
    for n in plan.nodes:
        if n.harness in all_counts:
            all_counts[n.harness] += 1
            if n.node_type in ("investigate", "execute"):
                inv_counts[n.harness] += 1
    out: list[str | None] = []
    for _ in range(max(0, k - 1)):
        h = min(harns, key=lambda x: (inv_counts[x], all_counts[x], harns.index(x)))
        inv_counts[h] += 1
        all_counts[h] += 1
        out.append(h)
    if k >= 1:
        fresh = [h for h in harns if h not in out] or harns
        out.append(min(fresh, key=lambda x: (all_counts[x], harns.index(x))))
    return out


def _unique_id(base: str, existing: set[str]) -> str:
    nid, k = base, 2
    while nid in existing:
        nid = f"{base}-{k}"
        k += 1
    existing.add(nid)
    return nid


def _investigator(
    nid: str, objective: str, hint: str, independence: str, harness: str | None, model: str | None
) -> PlanNode:
    return PlanNode(
        node_id=nid,
        node_type="investigate",
        objective=objective,
        role="investigator",
        independence=independence if independence in INDEPENDENCE_LEVELS else "high",
        method_hint=hint,
        retrieval_query=ou.retrieval_query_for(objective, hint),
        harness=harness,
        model=model,
    )


def expansion_nodes(
    plan: OrchestrationPlan,
    decision: ou.ExpansionDecision,
    *,
    harnesses: list[str] | None = None,
    models_by_harness: dict[str, str] | None = None,
    after: str | None = None,
    critic_pairs: list[tuple[str, str | None]] | None = None,
) -> Extension:
    """Targeted investigators plus a re-verify; the synthesizer waits on it.

    ``after`` is the verifier that asked for more; only synthesizers waiting
    on it are rewired (finished ones from earlier waves are left alone).
    """
    existing = plan.reserved_ids()  # live + retired ids
    feat = ou.TaskFeatures.from_dict(plan.features) if plan.features else None
    n_extra = max(1, decision.n_extra)
    hints = ou.method_hints_for(max(2, n_extra), "high", feat)
    objectives = list(decision.objectives or [plan.objective] * n_extra)[:n_extra]
    alloc = _least_used_harnesses(plan, harnesses, len(objectives) + 1)
    models = models_by_harness or {}
    indep = str((plan.decision or {}).get("independence") or "high")
    new: list[PlanNode] = []
    for i, obj in enumerate(objectives):
        nid = _unique_id(f"inv-x{len(existing)}", existing)
        h = alloc[i]
        new.append(_investigator(nid, obj, hints[i % len(hints)], indep, h, models.get(h) if h else None))
    nodes_by_id = plan.node_map()
    prev_verify = nodes_by_id.get(after) if after else None
    if prev_verify is None:
        prev_verify = next((n for n in reversed(plan.nodes) if n.node_type == "verify"), None)
    vid = _unique_id("verify-x1", existing)
    vh, vm = _reverify_seat(critic_pairs, alloc, models)
    new.append(
        PlanNode(
            node_id=vid,
            node_type="verify",
            objective="Re-verify after targeted expansion",
            dependencies=[n.node_id for n in new] + ([prev_verify.node_id] if prev_verify else []),
            role="verifier",
            difficulty="hard",
            independence="high",
            output_contract="verification",
            harness=vh,
            model=vm,
        )
    )
    rewire = {
        n.node_id: [vid]
        for n in plan.nodes
        if n.node_type == "synthesize" and (prev_verify is None or prev_verify.node_id in n.dependencies)
    }
    return Extension(nodes=new, rewire=rewire, reason=decision.reason)


def continue_wave(
    plan: OrchestrationPlan,
    decision: ou.ExpansionDecision,
    *,
    harnesses: list[str] | None = None,
    models_by_harness: dict[str, str] | None = None,
    critic_pairs: list[tuple[str, str | None]] | None = None,
) -> Extension:
    """A fresh investigate → verify → synthesize subgraph after 'OBJECTIVE_MET: no'.

    It does not hang off the previous synthesizer, so depth stays flat.
    The newest synthesizer is the run's answer.
    """
    existing = plan.reserved_ids()  # live + retired ids
    wave = 1 + sum(1 for n in plan.nodes if n.node_type == "synthesize")
    feat = ou.TaskFeatures.from_dict(plan.features) if plan.features else None
    n_extra = max(1, decision.n_extra)
    hints = ou.method_hints_for(max(2, n_extra), "high", feat)
    objectives = list(decision.objectives or [plan.objective] * n_extra)[:n_extra]
    alloc = _least_used_harnesses(plan, harnesses, len(objectives) + 1)
    models = models_by_harness or {}
    new: list[PlanNode] = []
    for i, obj in enumerate(objectives):
        nid = _unique_id(f"inv-c{wave}-{i}", existing)
        h = alloc[i]
        new.append(_investigator(nid, obj, hints[i % len(hints)], "high", h, models.get(h) if h else None))
    vid = _unique_id(f"verify-c{wave}", existing)
    vh, vm = _reverify_seat(critic_pairs, alloc, models)
    new.append(
        PlanNode(
            node_id=vid,
            node_type="verify",
            objective="Re-verify after continue wave",
            dependencies=[n.node_id for n in new],
            role="verifier",
            difficulty="hard",
            independence="high",
            output_contract="verification",
            harness=vh,
            model=vm,
        )
    )
    new.append(
        PlanNode(
            node_id=_unique_id(f"synth-c{wave}", existing),
            node_type="synthesize",
            objective=plan.objective,
            dependencies=[vid],
            role="synthesizer",
            difficulty="hard",
            independence="low",
            output_contract="synthesis",
        )
    )
    return Extension(nodes=new, reason=decision.reason)


def verify_round(
    plan: OrchestrationPlan,
    after: str,
    *,
    critic_pairs: list[tuple[str, str | None]] | None = None,
    reason: str = "",
) -> Extension:
    """Check an unverified answer: one verifier on the critic, then a fresh synthesizer.

    Used when the host stops on its first answer and nothing in the run was
    verified. The newest synthesizer is the run's answer.
    """
    existing = plan.reserved_ids()
    wave = 1 + sum(1 for n in plan.nodes if n.node_type == "verify")
    vh, vm = _reverify_seat(critic_pairs, [], {})
    vid = _unique_id(f"verify-v{wave}", existing)
    new = [
        PlanNode(
            node_id=vid,
            node_type="verify",
            objective="Independently check the answer and the findings behind it",
            dependencies=[after],
            role="verifier",
            difficulty="hard",
            independence="high",
            output_contract="verification",
            harness=vh,
            model=vm,
        ),
        PlanNode(
            node_id=_unique_id(f"synth-v{wave}", existing),
            node_type="synthesize",
            objective=plan.objective,
            dependencies=[vid],
            role="synthesizer",
            difficulty="hard",
            independence="low",
            output_contract="synthesis",
        ),
    ]
    return Extension(nodes=new, reason=reason or "verify round")


class AdaptiveRun:
    """``after_node`` hook: collect evidence, expand on ΔU, stop on OBJECTIVE_MET.

    Used by ``run_plan`` (bench, ``okstratr run``, the file queue) and by live
    desks through ``okstratr.live`` (Herdr, direct, Switchbay). It only sees
    ``NodeResult`` objects; live seats fill those from ``okstratr findings add``.

    - After each investigator: its findings go into this run's evidence store.
    - After a verifier: buy targeted investigators + a re-verify while
      ΔU > threshold (and within the expansion cap and node limit).
    - After a synthesizer: with no ``host`` profile, continue only on an
      explicit ``OBJECTIVE_MET: no`` that still clears ΔU. With a host
      profile, ``host_profile.decide_done`` first decides whether to respect
      the host's done, continue past it (open gaps, time-boxed runs), add a
      verify round, or stop on budget/deadline. Every such decision is in
      ``events`` and goes to ``on_decision``.
    """

    def __init__(
        self,
        plan: OrchestrationPlan,
        *,
        store: Any | None = None,
        harnesses: list[str] | None = None,
        models_by_harness: dict[str, str] | None = None,
        critic_pairs: list[tuple[str, str | None]] | None = None,
        host: Any | None = None,
        budget: Any | None = None,
        owner_loop: bool = False,
        on_decision: Callable[[dict[str, Any]], None] | None = None,
        base_tokens: float = 0.0,
    ) -> None:
        from . import evidence as ev

        self.store = store if store is not None else ev.RunEvidence(plan.run_id)
        self.host = host
        self.budget = budget
        self.owner_loop = bool(owner_loop)
        self.on_decision = on_decision
        self.base_tokens = float(base_tokens or 0.0)
        self.failing_checks = 0
        self.verify_rounds = 0
        self.host_decisions: list[dict[str, Any]] = []
        self.harnesses = list(harnesses or [])
        self.models_by_harness = dict(models_by_harness or {})
        self.critic_pairs = list(critic_pairs or [])
        self.expansions = 0
        self.continuations = 0
        self.findings_at_last_synth = 0
        self.claims_at_last_expansion: int | None = None
        self.claims_at_last_synth: int | None = None
        self.gaps_at_last_wave: int | None = None
        self.stalled = False
        self.stop_reason = ""
        self.objective_met: bool | None = None
        self.events: list[dict[str, Any]] = []
        self.failed_harnesses: list[str] = []
        self.failovers = 0

    def context_for(self, node: PlanNode) -> str:
        """Evidence a verifier or synthesizer should read (JSON text)."""
        return self.store.compact_for_prompt()

    def unique_claims(self) -> int:
        """Distinct claims so far; repeats of the same claim are not new work."""
        return len({" ".join(f.claim.lower().split()) for f in self.store.findings if f.claim.strip()})

    @staticmethod
    def _gap_count(v: dict[str, Any] | None, extra: str = "") -> int:
        v = v or {}
        unresolved = v.get("unresolved") or []
        n = len(unresolved) if isinstance(unresolved, list) else 0
        try:
            n += int(v.get("conflicts") or 0)
        except (TypeError, ValueError):
            pass
        return n + (1 if extra.strip() and n == 0 else 0)

    def _close_rate(self, gaps_now: int) -> float | None:
        """Share of the gaps open at the last wave that it closed (None before any wave)."""
        prev = self.gaps_at_last_wave
        if not prev:
            return None
        return max(0.0, (prev - gaps_now) / prev)

    def _consequence(self, plan: OrchestrationPlan) -> float:
        try:
            return float((plan.features or {}).get("consequence") or 0.1)
        except (TypeError, ValueError):
            return 0.1

    _PERSISTED = (
        "expansions", "continuations", "findings_at_last_synth", "claims_at_last_expansion",
        "claims_at_last_synth", "gaps_at_last_wave", "stalled", "stop_reason", "objective_met", "events",
        "failing_checks", "verify_rounds", "host_decisions", "owner_loop", "base_tokens",
        "failed_harnesses", "failovers",
    )

    def to_dict(self) -> dict[str, Any]:
        """Counters and decisions (the evidence store is saved on its own)."""
        d = {k: getattr(self, k) for k in self._PERSISTED}
        d["harnesses"] = list(self.harnesses)
        d["models_by_harness"] = dict(self.models_by_harness)
        d["critic_pairs"] = [list(p) for p in self.critic_pairs]
        d["host"] = self.host.to_dict() if self.host is not None else None
        d["budget"] = self.budget.to_dict() if self.budget is not None else None
        return d

    @classmethod
    def from_dict(
        cls, plan: OrchestrationPlan, raw: dict[str, Any], *, store: Any | None = None,
        on_decision: Callable[[dict[str, Any]], None] | None = None,
    ) -> AdaptiveRun:
        from . import host_profile as hp

        raw = raw if isinstance(raw, dict) else {}
        run = cls(
            plan,
            store=store,
            harnesses=list(raw.get("harnesses") or []),
            models_by_harness=dict(raw.get("models_by_harness") or {}),
            critic_pairs=[tuple(p) for p in raw.get("critic_pairs") or [] if isinstance(p, list) and len(p) == 2],
            host=hp.HostProfile.from_dict(raw["host"]) if raw.get("host") else None,
            budget=hp.Budget.from_dict(raw["budget"]) if raw.get("budget") else None,
            owner_loop=bool(raw.get("owner_loop")),
            on_decision=on_decision,
            base_tokens=float(raw.get("base_tokens") or 0.0),
        )
        for k in cls._PERSISTED:
            if k in raw and k not in ("owner_loop", "base_tokens"):
                setattr(run, k, raw[k])
        return run

    def _failover(
        self, plan: OrchestrationPlan, state: RunState, node: PlanNode, res: NodeResult,
    ) -> list[PlanNode] | Extension:
        """Re-seat a failed investigator once on a harness that has not failed.

        The plan was priced with this seat; losing it silently turns a
        diverse plan into a single one that still pays for the verifier. A
        retry is not retried, and nothing is re-seated when every harness has
        failed, the node limit is near, or a dependant already started.
        """
        if node.harness and node.harness not in self.failed_harnesses:
            self.failed_harnesses.append(node.harness)
        if node.node_type not in ("investigate", "execute") or "-retry" in node.node_id:
            return []
        healthy = [h for h in self.harnesses if h not in self.failed_harnesses]
        bounds = plan.bounds.clamp()
        if not healthy or len(plan.nodes) + 1 > bounds.max_nodes:
            return []
        used: dict[str, int] = {h: 0 for h in healthy}
        for n in plan.nodes:
            if n.harness in used:
                used[n.harness] += 1
        h = min(healthy, key=lambda x: (used[x], healthy.index(x)))
        nid = _unique_id(f"{node.node_id}-retry", plan.reserved_ids())
        retry = PlanNode(
            node_id=nid, node_type=node.node_type, objective=node.objective,
            dependencies=[d for d in node.dependencies if d in state.completed],
            role=node.role, difficulty=node.difficulty, access=node.access, independence=node.independence,
            output_contract=node.output_contract, method_hint=node.method_hint,
            retrieval_query=node.retrieval_query, harness=h, model=self.models_by_harness.get(h),
        )
        rewire = {
            n.node_id: list(n.dependencies) + [nid]
            for n in plan.nodes
            if node.node_id in n.dependencies and n.node_id not in state.results
        }
        self.failovers += 1
        reason = f"{node.node_id} failed on {node.harness or 'its harness'} ({res.error or 'error'}); re-seated on {h}"
        self.events.append({"after": node.node_id, "kind": "failover", "expand": True, "reason": reason})
        return Extension(nodes=[retry], rewire=rewire, reason=reason)

    def okstratr_strength(self, plan: OrchestrationPlan) -> int:
        """Strength of okstratr's own stop rule for this plan (host_profile.STRENGTHS)."""
        from . import host_profile as hp

        types = {n.node_type for n in plan.nodes}
        if "verify" in types:
            return hp.strength_rank("verified")
        if "execute" in types:
            return hp.strength_rank("tests")
        return hp.strength_rank("self_check")

    def _host_decision(
        self, plan: OrchestrationPlan, state: RunState, node: PlanNode,
        met: bool | None, gap: str, v: Any,
    ) -> Any:
        from . import host_profile as hp

        profile = self.host if self.host is not None else hp.HostProfile()
        budget = self.budget if self.budget is not None else hp.Budget()
        budget.spent_tokens = self.base_tokens + state.tokens()
        verified = any(
            n.node_type == "verify" and n.node_id in state.completed for n in plan.nodes
        )
        d = hp.decide_done(
            profile,
            okstratr_strength=self.okstratr_strength(plan),
            objective_met=met,
            gap=gap,
            failing_checks=self.failing_checks,
            verification=v.to_dict() if v else None,
            verified=verified,
            budget=budget,
            owner_loop=self.owner_loop,
            preference=plan.preference,
            consequence=self._consequence(plan),
        )
        event = {
            "after": node.node_id, "kind": "host_done", "action": d.action,
            "override": d.override, "reason": d.reason, "host": profile.to_dict(),
            "gaps": list(d.gaps), "tokens_spent": budget.spent_tokens,
        }
        self.events.append(event)
        self.host_decisions.append(event)
        if self.on_decision is not None:
            try:
                self.on_decision(event)
            except Exception:  # noqa: BLE001
                pass
        return d

    def __call__(self, plan: OrchestrationPlan, state: RunState, res: NodeResult) -> list[PlanNode] | Extension:
        from . import evidence as ev

        node = plan.node_map().get(res.node_id)
        if node is None:
            return []
        if not res.ok:
            return self._failover(plan, state, node, res)
        t = node.node_type
        if t in ("investigate", "execute", "reduce"):
            if t == "reduce":
                self.store.mark_replaced(node.dependencies)
            self.store.append_findings(ev.parse_findings(res.text, node_id=node.node_id))
            checks = (ev.parse_json_object(res.text) or {}).get("checks")
            if isinstance(checks, list):
                self.failing_checks += sum(
                    1 for c in checks if isinstance(c, dict) and not c.get("passed")
                )
            return []
        bounds = plan.bounds.clamp()
        remaining = bounds.max_nodes - len(plan.nodes)
        if t == "verify":
            rec = self.store.append_verification(ev.parse_verification(res.text, node_id=node.node_id))
            synth_waiting = any(
                n.node_type == "synthesize" and n.node_id not in state.results and node.node_id in n.dependencies
                for n in plan.nodes
            )
            if not synth_waiting:
                return []
            if self.claims_at_last_expansion is not None and self.unique_claims() <= self.claims_at_last_expansion:
                self.stalled = True
                self.events.append(
                    {"after": node.node_id, "kind": "expand", "expand": False,
                     "reason": "last expansion found nothing new"}
                )
                return []
            vd = rec.to_dict()
            gaps_now = self._gap_count(vd)
            exp = ou.choose_expansion(
                gap_close_rate=self._close_rate(gaps_now),
                preference=plan.preference,
                independence=str((plan.decision or {}).get("independence") or "medium"),
                allow_expand=plan.allow_expand,
                verification=rec.to_dict(),
                findings_n=len(self.store.candidates()),
                expansions_so_far=self.expansions,
                nodes_so_far=len(plan.nodes),
                remaining_nodes=remaining,
                consequence=self._consequence(plan),
                unique_sources=self.store.unique_source_count(),
                max_expansions=bounds.max_expansions,
                max_nodes=bounds.max_nodes,
            )
            self.events.append({"after": node.node_id, "kind": "expand", "expand": exp.expand, "reason": exp.reason})
            if not exp.expand:
                return []
            self.expansions += 1
            self.claims_at_last_expansion = self.unique_claims()
            self.gaps_at_last_wave = gaps_now
            return expansion_nodes(
                plan, exp, harnesses=self.harnesses, models_by_harness=self.models_by_harness,
                critic_pairs=self.critic_pairs,
                after=node.node_id,
            )
        if t == "synthesize":
            met, gap = ou.parse_objective_met(res.text)
            self.objective_met = met
            v = self.store.latest_verification()
            if self.host is not None or self.owner_loop:
                d = self._host_decision(plan, state, node, met, gap, v)
                if d.action in ("respect", "stop"):
                    self.stop_reason = d.reason
                    return []
                if d.action == "verify":
                    if remaining < 2:
                        self.stop_reason = "verify round wanted but node limit reached"
                        return []
                    self.verify_rounds += 1
                    return verify_round(plan, node.node_id, critic_pairs=self.critic_pairs, reason=d.reason)
                # continue: okstratr's own evidence says not done; ΔU below still bounds it.
                if met is not False:
                    met, gap = False, "; ".join(d.gaps) or gap or "objective not confirmed"
            if met is False and self.stalled:
                # More of the same already came back empty; another wave would too.
                self.stop_reason = "last expansion found nothing new"
                self.events.append({"after": node.node_id, "kind": "continue", "expand": False,
                                    "reason": self.stop_reason})
                return []
            n_findings = len(self.store.findings)
            claims = self.unique_claims()
            wave_new = claims if self.claims_at_last_synth is None else claims - self.claims_at_last_synth
            vd = v.to_dict() if v else None
            gaps_now = self._gap_count(vd, gap if met is False else "")
            cont = ou.should_continue(
                gap_close_rate=self._close_rate(gaps_now),
                preference=plan.preference,
                allow_expand=plan.allow_expand,
                objective_met=met,
                gap=gap,
                verification=v.to_dict() if v else None,
                findings_n=max(len(self.store.candidates()), n_findings),
                expansions_so_far=self.continuations,
                nodes_so_far=len(plan.nodes),
                remaining_nodes=remaining,
                consequence=self._consequence(plan),
                unique_sources=self.store.unique_source_count(),
                last_wave_new_findings=wave_new,
                concat=node.output_contract == "concat",
                max_continuations=bounds.max_expansions,
            )
            self.events.append({"after": node.node_id, "kind": "continue", "expand": cont.expand, "reason": cont.reason})
            if not cont.expand:
                self.stop_reason = cont.reason
                return []
            self.continuations += 1
            self.gaps_at_last_wave = gaps_now
            self.findings_at_last_synth = n_findings
            self.claims_at_last_synth = claims
            return continue_wave(
                plan, cont, harnesses=self.harnesses, models_by_harness=self.models_by_harness,
                critic_pairs=self.critic_pairs,
            )
        return []


def run_telemetry(state: RunState, run: AdaptiveRun | None = None, *, explored: bool = False) -> dict[str, Any]:
    """Outcome numbers for the learner (no transcripts, no prompts)."""
    plan = state.plan
    synths = [n for n in plan.nodes if n.node_type == "synthesize"]
    completed = bool(synths) and any(n.node_id in state.completed for n in synths)
    if not synths:
        completed = bool(state.results) and not state.failed
    tel: dict[str, Any] = {
        "completed": completed,
        "tokens": state.tokens(),
        "latency_s": state.critical_path_s(),
        "final_nodes": len(plan.nodes),
        "failed_nodes": len(state.failed),
        "explored": bool(explored),
    }
    if run is not None:
        store = run.store
        v = store.latest_verification()
        tel.update(
            candidate_findings_n=len(store.candidates()),
            findings_n=len(store.findings),
            unsupported_rejected=store.unsupported_count(),
            verification_conflicts=store.conflict_count(),
            verifier_confidence=(v.confidence if v else None),
            unique_sources=store.unique_source_count(),
            expansions=run.expansions,
            continuations=run.continuations,
            objective_met=run.objective_met,
        )
    return tel


def record_run(
    state: RunState,
    run: AdaptiveRun | None = None,
    *,
    desk_id: str | None = None,
) -> dict[str, Any]:
    """Feed one finished run back into this desk's recipe learner."""
    from . import bandit

    decision = state.plan.decision or {}
    feat = ou.TaskFeatures.from_dict(state.plan.features or decision.get("features") or {})
    arm = str(decision.get("arm_id") or "single")
    tel = run_telemetry(state, run, explored=bool(decision.get("explored")))
    try:
        from . import model_routing

        for model, failed, tokens in author_outcomes(state, run):
            model_routing.record_outcome(model, feat.kind(), failed=failed, tokens=tokens)
    except Exception:  # noqa: BLE001 — routing stats must never break the learner
        pass
    return bandit.record_recipe_outcome(arm, feat, tel, desk_id=desk_id)


_BAD_VERDICTS = ("contradicted", "insufficient", "inconsistent")


def author_outcomes(state: RunState, run: AdaptiveRun | None = None) -> list[tuple[str, bool, float]]:
    """(model, failed, tokens) for each author seat with a known model.

    A seat failed when it errored, or when the verifier rejected at least
    half of the claims it made that were classified.
    """
    out: list[tuple[str, bool, float]] = []
    findings = list(run.store.findings) if run is not None else []
    for n in state.plan.nodes:
        if n.node_type not in ("investigate", "execute") or not n.model:
            continue
        res = state.results.get(n.node_id)
        if res is None and n.node_id not in state.failed:
            continue
        failed = n.node_id in state.failed or (res is not None and not res.ok)
        mine = [f for f in findings if f.node_id == n.node_id and f.verdict != "candidate"]
        if mine and not failed:
            bad = sum(1 for f in mine if f.verdict in _BAD_VERDICTS)
            failed = bad * 2 >= len(mine)
        out.append((n.model, failed, float(res.tokens if res is not None else 0)))
    return out


def prompt_for(node: PlanNode, inputs: dict[str, NodeResult], context: str = "") -> str:
    """Plain worker prompt for a plan node (used by harness runners)."""
    parts = [node.objective.strip()]
    if node.method_hint:
        parts.append(f"Method: {node.method_hint}")
    if node.retrieval_query:
        parts.append(f"Start your lookup with: {node.retrieval_query}")
    if node.node_type == "investigate":
        parts.append('Reply with JSON: {"findings": [{"claim": ..., "evidence": [{"source": ...}], "confidence": 0-1}]}')
    elif node.node_type == "verify":
        parts.append(
            'Reply with JSON: {"classifications": [{"finding_id": ..., "verdict": '
            '"supported|contradicted|insufficient|inconsistent"}], "confidence": 0-1, "unresolved": []}'
        )
    elif node.node_type == "synthesize":
        parts.append("Use only supported findings.")
        parts.append(ou.OBJECTIVE_MET_INSTRUCTION)
    if context:
        parts.append("Evidence so far:\n" + context)
    for nid, r in inputs.items():
        if r.text:
            parts.append(f"From {nid}:\n{r.text[:4000]}")
    return "\n\n".join(p for p in parts if p)
