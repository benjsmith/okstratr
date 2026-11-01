"""Typed plan nodes, validation, hard limits and the scheduler."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from okstratr import limits
from okstratr import orchestration as orch
from okstratr.dag import Dag, Node
from okstratr.orchestration import NodeResult, OrchestrationPlan, PlanNode


def _plan(nodes: list[PlanNode], **kw) -> OrchestrationPlan:
    return OrchestrationPlan(run_id="run-t", strategy="t", nodes=nodes, objective="obj", **kw)


def _inv(i: int, deps: list[str] | None = None) -> PlanNode:
    return PlanNode(node_id=f"inv-{i}", node_type="investigate", objective=f"o{i}", dependencies=deps or [])


def ok_runner(node: PlanNode, inputs: dict[str, NodeResult]) -> NodeResult:
    return NodeResult(node_id=node.node_id, text=f"{node.node_id}<-{sorted(inputs)}", tokens=10, latency_s=1.0)


# ── limits ─────────────────────────────────────────────────────────


def test_bounds_clamp_never_exceeds_hard_limits() -> None:
    b = limits.Bounds(
        max_nodes=999, max_depth=99, max_concurrency=99, max_expansions=99,
        worker_timeout_sec=1e9, wall_clock_sec=1e9,
    ).clamp()
    assert b.max_nodes == limits.MAX_NODES == 24
    assert b.max_depth == limits.MAX_DEPTH == 8
    assert b.max_concurrency == limits.MAX_CONCURRENCY == 8
    assert b.max_expansions == limits.MAX_EXPANSIONS == 3
    assert b.worker_timeout_sec == limits.WORKER_TIMEOUT_SEC
    assert b.wall_clock_sec == limits.WALL_CLOCK_SEC
    junk = limits.Bounds.from_dict({"max_nodes": "x", "max_depth": -5})
    assert junk.max_nodes == 24 and junk.max_depth == 1


# ── validation ─────────────────────────────────────────────────────


def test_validate_catches_structural_errors() -> None:
    p = _plan([
        _inv(0, ["inv-1"]),
        _inv(1, ["inv-0"]),
        PlanNode(node_id="x", node_type="bogus", objective="", dependencies=["ghost"]),
        PlanNode(node_id="v", node_type="verify", objective="v", access="write"),
    ])
    errs = " | ".join(orch.validate_plan(p))
    assert "cycle" in errs
    assert "unknown node_type" in errs
    assert "missing dependency" in errs
    assert "empty objective" in errs
    assert "only execute nodes may write" in errs


def test_validate_enforces_node_and_depth_limits() -> None:
    wide = _plan([_inv(i) for i in range(30)])
    assert any("node count" in e for e in orch.validate_plan(wide))
    chain = [_inv(0)] + [_inv(i, [f"inv-{i-1}"]) for i in range(1, 10)]
    assert any("depth" in e for e in orch.validate_plan(_plan(chain)))


def test_repair_fixes_local_problems() -> None:
    p = _plan([
        PlanNode(node_id="a", node_type="nope", objective=""),
        PlanNode(node_id="a", node_type="verify", objective="v", dependencies=["a", "ghost"], access="write"),
    ])
    p = orch.repair_plan(p)
    assert [n.node_id for n in p.nodes] == ["a", "a-2"]
    assert p.nodes[0].node_type == "investigate"
    assert p.nodes[0].objective == "obj"
    assert p.nodes[1].dependencies == ["a"]
    assert p.nodes[1].access == "read"
    assert p.nodes[1].role == "verifier"
    assert orch.validate_plan(p) == []


def test_ensure_valid_falls_back_on_cycles() -> None:
    p = _plan([_inv(0, ["inv-1"]), _inv(1, ["inv-0"])])
    fixed = orch.ensure_valid(p)
    assert orch.validate_plan(fixed) == []
    assert fixed.strategy == "fixed_fanout"
    assert fixed.decision["fallback"] == "fixed_fanout"
    one = orch.ensure_valid(_plan([_inv(0, ["inv-0"])] + [_inv(i) for i in range(1, 30)]))
    assert orch.validate_plan(one) == []
    assert len(one.nodes) <= limits.MAX_NODES


def test_plan_roundtrip_and_ready_nodes() -> None:
    p = orch.plan_fixed_fanout("obj", [{"description": "a"}, {"description": "b"}], run_id="r1")
    q = OrchestrationPlan.from_dict(json.loads(json.dumps(p.to_dict())))
    assert q.to_dict() == p.to_dict()
    assert {n.node_id for n in orch.ready_nodes(q, set(), set())} == {"w0", "w1"}
    assert [n.node_id for n in orch.ready_nodes(q, {"w0"}, {"w1"})] == ["merge"]
    s = orch.plan_single("hi", run_id="r2")
    assert [n.node_id for n in s.nodes] == ["main"] and orch.validate_plan(s) == []


# ── scheduler ──────────────────────────────────────────────────────


def test_scheduler_runs_in_dependency_order_and_in_parallel() -> None:
    barrier = threading.Barrier(3, timeout=5)

    def runner(node: PlanNode, inputs: dict[str, NodeResult]) -> NodeResult:
        if node.node_type == "investigate":
            barrier.wait()  # all three investigators must be in flight together
        return ok_runner(node, inputs)

    p = _plan([_inv(0), _inv(1), _inv(2),
               PlanNode(node_id="synth", node_type="synthesize", objective="s",
                        dependencies=["inv-0", "inv-1", "inv-2"])])
    st = orch.run_plan(p, runner)
    assert st.completed == {"inv-0", "inv-1", "inv-2", "synth"}
    assert st.results["synth"].text == "synth<-['inv-0', 'inv-1', 'inv-2']"
    assert st.tokens() == 40
    assert st.critical_path_s() == 2.0
    assert st.final() is st.results["synth"]


def test_scheduler_failed_dependency_is_terminal() -> None:
    def runner(node: PlanNode, inputs: dict[str, NodeResult]) -> NodeResult:
        if node.node_id == "inv-1":
            raise RuntimeError("boom")
        return ok_runner(node, inputs)

    p = _plan([_inv(0), _inv(1),
               PlanNode(node_id="synth", node_type="synthesize", objective="s",
                        dependencies=["inv-0", "inv-1"])])
    st = orch.run_plan(p, runner)
    assert st.failed == {"inv-1"}
    assert "boom" in st.results["inv-1"].error
    assert st.results["synth"].text == "synth<-['inv-0']"


def test_scheduler_worker_timeout() -> None:
    release = threading.Event()

    def runner(node: PlanNode, inputs: dict[str, NodeResult]) -> NodeResult:
        if node.node_id == "inv-1":
            release.wait(10)
        return ok_runner(node, inputs)

    p = _plan([_inv(0), _inv(1)], bounds=limits.Bounds(worker_timeout_sec=1.0))
    t0 = time.monotonic()
    st = orch.run_plan(p, runner)
    release.set()
    assert time.monotonic() - t0 < 5
    assert st.results["inv-1"].error == "timeout"
    assert "inv-0" in st.completed


def test_scheduler_checkpoint_and_resume(tmp_path: Path) -> None:
    ck = tmp_path / "ck.json"
    calls: list[str] = []

    def runner(node: PlanNode, inputs: dict[str, NodeResult]) -> NodeResult:
        calls.append(node.node_id)
        return ok_runner(node, inputs)

    p = _plan([_inv(0), _inv(1),
               PlanNode(node_id="synth", node_type="synthesize", objective="s",
                        dependencies=["inv-0", "inv-1"])])
    # Simulate an interrupted run: only inv-0 finished.
    partial = orch.RunState(plan=p, results={"inv-0": NodeResult(node_id="inv-0", text="x")})
    orch.save_checkpoint(ck, partial)
    resumed = orch.load_checkpoint(ck)
    assert resumed is not None
    st = orch.run_plan(resumed.plan, runner, resume=resumed, checkpoint=ck)
    assert sorted(calls) == ["inv-1", "synth"]
    assert st.completed == {"inv-0", "inv-1", "synth"}
    assert orch.load_checkpoint(ck).completed == st.completed  # type: ignore[union-attr]
    assert orch.load_checkpoint(tmp_path / "missing.json") is None


def test_after_node_expansion_respects_node_limit() -> None:
    def grow(plan: OrchestrationPlan, st: orch.RunState, res: NodeResult) -> list[PlanNode]:
        k = len(plan.nodes)
        return [_inv(k), _inv(k + 1)]

    p = _plan([_inv(0)])
    st = orch.run_plan(p, ok_runner, after_node=grow)
    assert len(st.plan.nodes) == limits.MAX_NODES
    assert st.completed == {n.node_id for n in st.plan.nodes}


# ── dag.json compatibility ─────────────────────────────────────────


def test_legacy_dag_json_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "dag.json"
    legacy = {
        "version": 1,
        "nodes": [
            {"id": "root", "title": "Obj", "kind": "root", "state": "done"},
            {"id": "investigator", "title": "Investigate", "depends_on": ["root"],
             "role": "investigator", "meta": {"harness": "Claude"}},
        ],
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    d = Dag.open(path)
    inv = d.nodes["investigator"]
    assert inv.prefer_harness == "claude"
    assert inv.node_type is None and inv.run_id is None and inv.method_hint == ""
    d.save()
    saved = json.loads(path.read_text(encoding="utf-8"))["nodes"]
    # Unused plan fields are not written, so old readers see the old shape.
    for item in saved:
        assert "node_type" not in item and "run_id" not in item


def test_dag_node_plan_fields_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "dag.json"
    d = Dag(path)
    d.add("inv-0", "Investigate", node_type="investigate", run_id="run-1",
          method_hint="primary sources", retrieval_query="scaling laws", independence="high")
    again = Dag.open(path).nodes["inv-0"]
    assert (again.node_type, again.run_id, again.method_hint, again.retrieval_query, again.independence) == (
        "investigate", "run-1", "primary sources", "scaling laws", "high"
    )
    assert Node.from_dict(again.to_dict()) == again
