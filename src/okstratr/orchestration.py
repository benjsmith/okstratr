"""Typed orchestration plans and a small dependency-aware scheduler.

A plan is a DAG of typed nodes (investigate, verify, synthesize, reduce,
execute). Plans are validated against hard limits before they run; an
invalid plan is repaired, then simplified, and finally replaced by a
single-node plan so a run always has something valid to execute.

The scheduler is runner-agnostic: it calls ``runner(node, inputs)`` for each
ready node and never talks to a model itself.
"""

from __future__ import annotations

import json
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

    def to_dict(self) -> dict[str, Any]:
        return {
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
        )

    def node_map(self) -> dict[str, PlanNode]:
        return {n.node_id: n for n in self.nodes}

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
AfterNode = Callable[[OrchestrationPlan, "RunState", NodeResult], list[PlanNode]]


@dataclass
class RunState:
    plan: OrchestrationPlan
    results: dict[str, NodeResult] = field(default_factory=dict)
    expansions: int = 0
    stopped: str = ""
    started_at: float = 0.0

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
        return ou.critical_path_latency(self.plan.nodes, lambda n: lat.get(n.node_id, 0.0))

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
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RunState:
        res = raw.get("results") if isinstance(raw.get("results"), dict) else {}
        return cls(
            plan=OrchestrationPlan.from_dict(raw.get("plan") or {}),
            results={k: NodeResult.from_dict(v) for k, v in res.items() if isinstance(v, dict)},
            expansions=int(raw.get("expansions") or 0),
            stopped=str(raw.get("stopped") or ""),
        )


def save_checkpoint(path: Path, state: RunState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
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
    """Run a validated plan to completion within its bounds.

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
            _append_nodes(plan, extra, bounds)
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


# ── plan from a utility decision ───────────────────────────────────


def plan_from_decision(
    objective: str,
    decision: ou.PolicyDecision,
    *,
    tasks: list[dict[str, Any]] | None = None,
    harnesses: list[str] | None = None,
    models_by_harness: dict[str, str] | None = None,
    run_id: str | None = None,
) -> OrchestrationPlan:
    """Build the DAG for a chosen recipe.

    Shape: investigators (and an executor) in parallel → optional reducers
    → optional verifier → synthesizer. The verifier always runs before the
    synthesizer, so the synthesizer only sees checked findings.
    Diverse recipes spread investigators across the given harnesses.
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
        spare = [h for h in harns if h not in used]
        vh = spare[0] if spare else (harns[-1] if harns else None)
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
                model=models.get(vh) if vh else None,
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


def add_reducers(nodes: list[PlanNode], investigators: list[PlanNode]) -> list[str]:
    """Pairwise reducers between a wide fan-out and the verifier."""
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
