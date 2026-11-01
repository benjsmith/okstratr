"""Offline benchmark: utility-chosen orchestration vs. the old fixed template."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from okstratr import bandit
from okstratr import orchestration as orch
from okstratr import orchestration_bench as bench
from okstratr.limits import MAX_EXPANSIONS, MAX_NODES
from okstratr.orchestration import NodeResult, PlanNode


@pytest.fixture(autouse=True)
def _state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path))
    bandit.reset_cache()
    yield
    bandit.reset_cache()


@pytest.fixture(scope="module")
def rows() -> list[bench.Row]:
    return bench.run_all()


def _by(rows: list[bench.Row], approach: str) -> dict[str, bench.Row]:
    return {r.scenario: r for r in rows if r.approach == approach}


def test_ten_scenarios_both_approaches(rows: list[bench.Row]) -> None:
    assert len(bench.SCENARIOS) == 10
    assert len(_by(rows, "utility")) == 10 and len(_by(rows, "template")) == 10


def test_utility_never_keeps_unverified_claims(rows: list[bench.Row]) -> None:
    for r in _by(rows, "utility").values():
        if r.nodes > 1:
            assert r.unverified_surviving == 0, r


def test_runs_stay_within_hard_limits(rows: list[bench.Row]) -> None:
    for r in _by(rows, "utility").values():
        assert r.nodes <= MAX_NODES
        assert r.expansions <= 2 * MAX_EXPANSIONS


def test_trivial_tasks_use_one_node_and_fewer_tokens(rows: list[bench.Row]) -> None:
    util, tmpl = _by(rows, "utility"), _by(rows, "template")
    for name in ("trivial-note", "trivial-many-harnesses"):
        assert util[name].nodes == 1
        assert util[name].tokens < tmpl[name].tokens


def test_utility_beats_template_on_average(rows: list[bench.Row]) -> None:
    s = bench.summary(rows)
    assert s["utility"]["mean_utility"] >= s["template"]["mean_utility"]
    assert s["utility"]["unverified_surviving"] <= s["template"]["unverified_surviving"]


def test_benchmark_is_deterministic() -> None:
    a = [r.to_dict() for r in bench.run_all()]
    b = [r.to_dict() for r in bench.run_all()]
    assert a == b


def test_main_prints_table_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert bench.main([]) == 0
    assert "mean U" in capsys.readouterr().out
    assert bench.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["rows"]) == 20 and "utility" in data["summary"]


def test_expansion_waits_on_the_node_that_added_it() -> None:
    plan = orch.OrchestrationPlan(
        run_id="t", strategy="test", objective="x",
        nodes=[PlanNode("a", "investigate", "x"), PlanNode("s", "synthesize", "x", dependencies=["a"])],
    )

    def runner(node: PlanNode, inputs: dict[str, NodeResult]) -> NodeResult:
        return NodeResult(node.node_id, True, "ok", tokens=10, latency_s=10.0)

    def after(p: orch.OrchestrationPlan, state: orch.RunState, res: NodeResult):
        if res.node_id == "a":
            return [PlanNode("b", "investigate", "x")]
        return []

    state = orch.run_plan(plan, runner, after_node=after)
    assert state.added_after == {"b": "a"}
    assert state.critical_path_s() == pytest.approx(20.0)
    again = orch.RunState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert again.added_after == {"b": "a"}
    legacy = state.to_dict()
    legacy.pop("added_after")
    assert orch.RunState.from_dict(legacy).added_after == {}


def test_expansion_stops_when_it_finds_nothing_new() -> None:
    from okstratr import orchestration_utility as ou

    sc = next(s for s in bench.SCENARIOS if s.name == "research-maximum-hard")
    world = bench.FakeWorld(sc, "utility")
    feat = ou.extract_features(sc.objective, preference=sc.effort, provider_diversity=len(sc.harnesses))
    plan = orch.plan_from_decision(sc.objective, ou.choose_initial_policy(feat, effort=sc.effort),
                                   harnesses=list(sc.harnesses))
    hook = orch.AdaptiveRun(plan, harnesses=list(sc.harnesses))
    orch.run_plan(plan, world.run, after_node=hook)
    reasons = [e["reason"] for e in hook.events if not e["expand"]]
    assert "last expansion found nothing new" in reasons
    # Expansion investigators are spread over harnesses, not piled on one.
    seats = [n.harness for n in plan.nodes if n.node_type == "investigate" and n.node_id.startswith("inv-x")]
    assert len(set(seats)) == len(seats) or len(set(seats)) == len(sc.harnesses)
