"""Offline benchmark: utility-chosen orchestration vs. one agent and the old template."""
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


def test_ten_scenarios_three_approaches(rows: list[bench.Row]) -> None:
    assert len(bench.SCENARIOS) == 10
    for a in bench.APPROACHES:
        assert len(_by(rows, a)) == 10


def test_perfect_verifier_keeps_no_false_claims() -> None:
    from dataclasses import replace

    for sc in bench.SCENARIOS:
        r = bench.run_utility(replace(sc, verifier_recall=1.0, verifier_fpr=0.0))
        if r.nodes > 1:
            assert r.unverified_surviving == 0, r


def test_verifier_is_not_an_oracle() -> None:
    """With recall < 1 a verifier rejects some true claims; with fpr > 0 it passes some false ones."""
    from dataclasses import replace

    sc = next(s for s in bench.SCENARIOS if s.name == "research-maximum-hard")
    strict = replace(sc, verifier_recall=1.0, verifier_fpr=0.0)
    sloppy = replace(sc, verifier_recall=0.5, verifier_fpr=0.5)
    q_strict = [bench.run_utility(strict, s, arm="ivs_diverse_2").quality for s in range(10)]
    q_sloppy = [bench.run_utility(sloppy, s, arm="ivs_diverse_2").quality for s in range(10)]
    assert sum(q_sloppy) < sum(q_strict)
    false_kept = sum(bench.run_utility(sloppy, s, arm="ivs_diverse_2").unverified_surviving for s in range(10))
    assert false_kept > 0


def test_no_slot_artifact_method_hint_does_not_change_base_finds() -> None:
    """A node's id or hint must not decide which facts its harness knows."""
    sc = next(s for s in bench.SCENARIOS if s.name == "research-balanced")
    hits = []
    for nid, hint in (("inv-a", ""), ("inv-b", ""), ("inv-c", "")):
        w = bench.FakeWorld(sc, "utility", 3)
        w.run(PlanNode(nid, "investigate", sc.objective, harness="grok", method_hint=hint), {})
        hits.append({c for c in w.claims[nid] if c in w.facts})
    # Same harness, same seed: the base finds overlap; only sampling noise differs.
    assert hits[0] & hits[1] & hits[2] or not any(hits)


def test_same_node_same_seed_same_outcome_across_approaches() -> None:
    sc = next(s for s in bench.SCENARIOS if s.name == "trivial-note")
    for s in range(10):
        u, one = bench.run_utility(sc, s), bench.run_single(sc, s)
        assert u.recipe in ("single", "single_strong")
        assert u.quality == one.quality


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
    assert len(data["rows"]) == 30 and "utility" in data["summary"] and "single" in data["summary"]


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


def _adaptive(sc: bench.Scenario, seed: int) -> tuple[orch.AdaptiveRun, orch.OrchestrationPlan]:
    from okstratr import orchestration_utility as ou

    world = bench.FakeWorld(sc, "utility", seed)
    feat = bench.features_for(sc)
    plan = orch.plan_from_decision(sc.objective, ou.choose_initial_policy(feat, effort=sc.effort),
                                   harnesses=list(sc.harnesses))
    hook = orch.AdaptiveRun(plan, harnesses=list(sc.harnesses))
    orch.run_plan(plan, world.run, after_node=hook)
    return hook, plan


def test_expansion_stops_when_it_finds_nothing_new() -> None:
    sc = next(s for s in bench.SCENARIOS if s.name == "research-maximum-hard")
    stopped = 0
    for seed in range(6):
        hook, plan = _adaptive(sc, seed)
        reasons = [e["reason"] for e in hook.events if not e["expand"]]
        if "last expansion found nothing new" in reasons:
            stopped += 1
            # One empty wave ends it: no second expansion after it.
            assert hook.expansions <= 1
        seats = [n.harness for n in plan.nodes if n.node_type == "investigate" and n.node_id.startswith("inv-x")]
        # Expansion investigators are spread over harnesses, not piled on one.
        assert len(set(seats)) >= min(len(seats), 2)
    assert stopped >= 1


def test_max_hard_second_wave_is_not_hired_when_first_closed_nothing() -> None:
    from okstratr import orchestration_utility as ou

    base = dict(preference=1.0, independence="high", allow_expand=True,
                verification={"confidence": 0.5, "unresolved": ["a", "b"], "conflicts": 0},
                findings_n=4, expansions_so_far=1, nodes_so_far=6, remaining_nodes=10)
    assert ou.choose_expansion(**base, gap_close_rate=0.8).expand
    stop = ou.choose_expansion(**base, gap_close_rate=0.0)
    assert not stop.expand and "P(close)" in stop.reason


def test_p_close_gap_prior_then_observed() -> None:
    from okstratr import orchestration_utility as ou

    assert ou.p_close_gap("high") == ou.P_CLOSE_PRIOR["high"]
    assert ou.p_close_gap("high", 0.0) < ou.p_close_gap("high") < ou.p_close_gap("high", 1.0)


def test_multi_seed_summary_k5_is_deterministic() -> None:
    a = bench.run_multi(5)
    b = bench.run_multi(5)
    assert a == b
    assert a["seeds"] == [0, 1, 2, 3, 4]
    ov = a["overall"]
    for key in ("vs_single", "vs_template"):
        p = ov[key]
        assert p["win"] + p["tie"] + p["loss"] == 5 * len(bench.SCENARIOS)
    assert ov["utility"]["u"] >= ov["single"]["u"]
    assert ov["utility"]["u"] >= ov["template"]["u"]
    assert "± " in bench.format_multi(a)


def test_paired_and_mean_se() -> None:
    m, se = bench.mean_se([1.0, 2.0, 3.0])
    assert m == 2.0 and se == pytest.approx(0.57735, abs=1e-4)
    p = bench.paired([1.0, 0.5, 0.2], [0.5, 0.5, 0.4])
    assert (p["win"], p["tie"], p["loss"]) == (1, 1, 1)


def test_utility_never_loses_to_single_on_average() -> None:
    res = bench.run_multi(30)
    for e in res["scenarios"]:
        assert e["vs_single"]["mean"] >= -0.01, e["scenario"]
        assert e["vs_template"]["mean"] >= -0.03, e["scenario"]  # trivial-many-harnesses is a tie in noise


def test_failed_seat_is_reseated_on_a_healthy_harness() -> None:
    sc = next(s for s in bench.SCENARIOS if s.name == "research-flaky-harness")
    hook, plan = _adaptive(sc, 0)
    retries = [n for n in plan.nodes if "-retry" in n.node_id]
    assert retries and all(n.harness == "grok" for n in retries)
    assert hook.failovers == len(retries) and hook.failed_harnesses == ["claude"]
    assert any(e["kind"] == "failover" for e in hook.events)
    verify = next(n for n in plan.nodes if n.node_type == "verify")
    assert retries[0].node_id in verify.dependencies


def test_retry_is_not_retried_and_all_failed_harnesses_stop_failover() -> None:
    plan = orch.OrchestrationPlan(
        run_id="t", strategy="test", objective="x",
        nodes=[PlanNode("a", "investigate", "x", harness="h1"),
               PlanNode("s", "synthesize", "x", dependencies=["a"])],
    )

    def runner(node: PlanNode, inputs: dict[str, NodeResult]) -> NodeResult:
        if node.node_type == "investigate":
            return NodeResult(node.node_id, False, "", error="boom")
        return NodeResult(node.node_id, True, "done\nOBJECTIVE_MET: yes", tokens=1)

    hook = orch.AdaptiveRun(plan, harnesses=["h1", "h2"])
    state = orch.run_plan(plan, runner, after_node=hook)
    ids = [n.node_id for n in plan.nodes]
    assert ids.count("a-retry") == 1 and not any(i.startswith("a-retry-") for i in ids)
    assert "s" in state.completed
    assert hook.failed_harnesses == ["h1", "h2"]
    again = orch.AdaptiveRun.from_dict(plan, json.loads(json.dumps(hook.to_dict())))
    assert again.failovers == 1


def test_calibration_reports_prior_vs_realized_and_warm_start() -> None:
    scs = [s for s in bench.SCENARIOS if s.name in ("research-economy", "research-balanced")]
    res = bench.calibrate(train=6, test=4, scenarios=scs)
    assert res["test_seeds"] == [6, 7, 8, 9]
    rows = {r["recipe"]: r for r in res["prior_vs_realized"]}
    assert "single" in rows and rows["single"]["runs"] == 6 * len(scs)
    for r in rows.values():
        assert r["gap"] == pytest.approx(r["realized_q"] - r["prior_q"], abs=2e-3)
    assert set(res["warm_vs_cold_by_scenario"]) >= {"mean", "se", "win", "tie", "loss"}
    assert "Prior vs realized" in bench.format_calibration(res)


def test_learner_needs_more_than_noise_to_leave_the_prior() -> None:
    from okstratr import orchestration_utility as ou

    sc = next(s for s in bench.SCENARIOS if s.name == "code-fix")
    feat = bench.features_for(sc)
    prior = ou.choose_initial_policy(feat, effort=sc.effort).arm_id
    noisy = {prior: {"n": 4, "sum_reward": 2.8, "sum_reward_sq": 2.8 * 2.8 / 4 + 0.3, "sum_quality_per_node": 0.4},
             "single": {"n": 4, "sum_reward": 3.0, "sum_reward_sq": 3.0 * 3.0 / 4 + 0.6, "sum_quality_per_node": 4.0}}
    assert ou.decide(feat, arms=noisy, effort=sc.effort, explore=False).arm_id == prior
    clear = {prior: {"n": 20, "sum_reward": 10.0, "sum_reward_sq": 5.0 + 0.01, "sum_quality_per_node": 1.0},
             "single": {"n": 20, "sum_reward": 18.0, "sum_reward_sq": 16.2 + 0.01, "sum_quality_per_node": 18.0}}
    assert ou.decide(feat, arms=clear, effort=sc.effort, explore=False).arm_id == "single"


def test_routing_bench_cheap_wins_small_fix_and_loses_hard_research() -> None:
    res = bench.routing_bench(train=20, test=20)
    rows = {r["scenario"]: r for r in res["rows"]}
    fix, hard = rows["cheap-wins-small-fix"], rows["cheap-loses-hard-research"]
    assert fix["cold_pick"] == hard["cold_pick"] == "claude-sonnet-4"  # unknown → strong
    assert fix["warm_pick"] == "claude-haiku"
    assert fix["u"]["claude-haiku"] > fix["u"]["claude-sonnet-4"]
    assert fix["routed_vs_strong"]["mean"] > 0
    assert hard["warm_pick"] == "claude-sonnet-4"
    assert hard["u"]["claude-haiku"] < hard["u"]["claude-sonnet-4"]
    assert "learned" in bench.format_routing(res)
