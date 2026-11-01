"""Recipe learning per desk and task type, stored in bandit.json."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from okstratr import bandit
from okstratr import orchestration as orch
from okstratr import orchestration_utility as ou
from okstratr.orchestration import NodeResult, PlanNode

RESEARCH = "Compare the evidence on remote work across sources; which claims disagree and why?"


@pytest.fixture(autouse=True)
def _state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(d))
    bandit.reset_cache()
    yield d
    bandit.reset_cache()


def _feat(effort: float = 0.6, task_type: str = "work", text: str = RESEARCH) -> ou.TaskFeatures:
    return ou.extract_features(text, preference=effort, provider_diversity=2, task_type=task_type)


class _NeverExplore:
    def random(self) -> float:
        return 1.0

    def choice(self, seq):  # pragma: no cover - never reached
        return seq[0]


class _AlwaysExplore:
    def random(self) -> float:
        return 0.0

    def choice(self, seq):
        return seq[0]


def _record(arm: str, feat: ou.TaskFeatures, *, desk: str | None, quality_bump: bool, times: int = 3) -> None:
    tel = {"completed": True, "tokens": 2000, "latency_s": 20.0, "final_nodes": 3,
           "verifier_confidence": 0.9 if quality_bump else 0.0}
    if not quality_bump:
        tel["unsupported_rejected"] = 3
        tel["candidate_findings_n"] = 3
    for _ in range(times):
        bandit.record_recipe_outcome(arm, feat, tel, desk_id=desk)


def test_legacy_bandit_file_loads_and_keeps_hire_arms(_state: Path) -> None:
    legacy = {
        "version": 1,
        "global": {"arms": {"n4_div0_core": {"pulls": 3, "reward_sum": 2.0}}, "total_pulls": 3},
        "desks": {"d1": {"arms": {"n2_div0_minimal": {"pulls": 1, "reward_sum": 1.0}}, "total_pulls": 1}},
    }
    (_state / "bandit.json").write_text(json.dumps(legacy), encoding="utf-8")
    snap = bandit.snapshot(0.5, desk_id="d1")
    assert snap["recipes"] == []
    assert {a["id"]: a["pulls"] for a in snap["arms"]}["n2_div0_minimal"] == 1
    assert bandit.select_arm(0.5)["arm_id"]
    bandit.record_recipe_outcome("ivs_diverse_2", _feat(), {"completed": True}, desk_id="d1")
    bandit.reset_cache()
    raw = json.loads((_state / "bandit.json").read_text(encoding="utf-8"))
    assert raw["global"]["arms"]["n4_div0_core"]["pulls"] == 3
    assert raw["desks"]["d1"]["arms"]["n2_div0_minimal"]["reward_sum"] == 1.0
    assert raw["recipes"]["d1"]


def test_malformed_recipe_section_is_ignored(_state: Path) -> None:
    (_state / "bandit.json").write_text(json.dumps({
        "global": {}, "recipes": {"d1": {"k": {"arms": {"single": "bad", "x": {"n": "nope"}}}}, "d2": 7},
    }), encoding="utf-8")
    store = bandit._load(force=True)
    assert store["recipes"] == {"d1": {"k": {"arms": {}}}}
    d = bandit.choose_recipe(_feat(), desk_id="d1", effort=0.6, rng=_NeverExplore())
    assert d.arm_id == ou.choose_initial_policy(_feat(), effort=0.6).arm_id


def test_learning_stays_inside_one_desk() -> None:
    feat = _feat()
    prior = ou.choose_initial_policy(feat, effort=0.6).arm_id
    alt = next(a for a in ou.NEIGHBORS[prior])
    _record(alt, feat, desk="desk-a", quality_bump=True)
    _record(prior, feat, desk="desk-a", quality_bump=False)
    a = bandit.choose_recipe(feat, desk_id="desk-a", effort=0.6, rng=_NeverExplore())
    b = bandit.choose_recipe(feat, desk_id="desk-b", effort=0.6, rng=_NeverExplore())
    g = bandit.choose_recipe(feat, desk_id=None, effort=0.6, rng=_NeverExplore())
    assert a.arm_id == alt and a.reason.startswith("learned")
    assert b.arm_id == prior and g.arm_id == prior
    assert bandit.recipe_arms(feat, desk_id="desk-b") == {}


def test_task_type_is_part_of_the_key() -> None:
    work, auto = _feat(task_type="work"), _feat(task_type="auto")
    assert ou.recipe_key(work) != ou.recipe_key(auto)
    _record("single_verify", work, desk="d", quality_bump=True)
    assert bandit.recipe_arms(work, desk_id="d")
    assert bandit.recipe_arms(auto, desk_id="d") == {}


def test_learning_never_lifts_the_hire_cap_ceiling() -> None:
    feat = _feat(effort=0.2)
    _record("swarm_8", feat, desk="d", quality_bump=True, times=5)
    d = bandit.choose_recipe(feat, desk_id="d", effort=0.2, rng=_NeverExplore())
    assert ou.recipe_workers(d.arm_id) <= bandit.hire_cap(0.2)


def test_needs_two_runs_before_exploiting() -> None:
    feat = _feat()
    prior = ou.choose_initial_policy(feat, effort=0.6).arm_id
    alt = ou.NEIGHBORS[prior][0]
    _record(alt, feat, desk="d", quality_bump=True, times=1)
    assert bandit.choose_recipe(feat, desk_id="d", effort=0.6, rng=_NeverExplore()).arm_id == prior


def test_exploration_is_neighbours_only_and_can_be_off() -> None:
    feat = _feat()
    chosen = ou.choose_initial_policy(feat, effort=0.6).arm_id
    d = bandit.choose_recipe(feat, desk_id="d", effort=0.6, rng=_AlwaysExplore())
    assert d.explored and d.arm_id in ou.NEIGHBORS[chosen]
    d = bandit.choose_recipe(feat, desk_id="d", effort=0.6, rng=_AlwaysExplore(), explore=False)
    assert not d.explored and d.arm_id == chosen
    easy = _feat(text="Rename this file")
    d = bandit.choose_recipe(easy, desk_id="d", effort=0.6, rng=_AlwaysExplore())
    assert d.arm_id == "single" and not d.explored


def test_exploration_rate_bounds() -> None:
    rates = []
    for s in (0.0, 0.5, 1.0):
        f = _feat(effort=s)
        rates.append(ou.exploration_rate(f))
        high = ou.TaskFeatures(**{**f.to_dict(), "consequence": 0.9})
        assert ou.exploration_rate(high) < ou.exploration_rate(f)
    assert all(0.01 <= r <= 0.12 for r in rates)
    many = {"a": {"n": 25}}
    assert ou.exploration_rate(_feat(1.0), many) < ou.exploration_rate(_feat(1.0))


def test_quality_proxy_is_not_node_count() -> None:
    base = {"completed": True, "verifier_confidence": 0.8, "candidate_findings_n": 4}
    q = ou.quality_proxy(base)
    assert ou.quality_proxy({**base, "unsupported_rejected": 3}) < q
    assert ou.quality_proxy({**base, "final_nodes": 9, "unique_sources": 2}) < q
    assert ou.quality_proxy({**base, "cancelled": True}) == 0.0
    assert ou.quality_proxy({}) < ou.quality_proxy({"completed": True})


def test_reset_only_touches_one_desk() -> None:
    feat = _feat()
    _record("single", feat, desk="a", quality_bump=True)
    _record("single", feat, desk="b", quality_bump=True)
    out = bandit.reset_recipes("a")
    assert out["removed_keys"] == 1
    assert bandit.recipe_arms(feat, desk_id="a") == {}
    assert bandit.recipe_arms(feat, desk_id="b")["single"]["n"] == 3


def test_record_run_rewards_realized_utility() -> None:
    feat = _feat(effort=0.6)
    decision = ou.choose_initial_policy(feat, effort=0.6)
    plan = orch.plan_from_decision(RESEARCH, decision, harnesses=["grok", "claude"])

    def run(node: PlanNode, inputs: dict[str, NodeResult]) -> NodeResult:
        if node.node_type in ("investigate", "reduce"):
            body = {"findings": [{"claim": f"c {node.node_id}", "evidence": [{"source": node.node_id}],
                                  "confidence": 0.7}]}
            return NodeResult(node.node_id, True, json.dumps(body), tokens=500, latency_s=2.0)
        if node.node_type == "verify":
            v = {"classifications": [], "confidence": 0.9, "unresolved": []}
            return NodeResult(node.node_id, True, json.dumps(v), tokens=300, latency_s=1.0)
        return NodeResult(node.node_id, True, "Answer\nOBJECTIVE_MET: yes", tokens=300, latency_s=1.0)

    hook = orch.AdaptiveRun(plan, harnesses=["grok", "claude"])
    st = orch.run_plan(plan, run, after_node=hook)
    tel = orch.run_telemetry(st, hook)
    assert tel["completed"] and tel["tokens"] == st.tokens()
    out = orch.record_run(st, hook, desk_id="d")
    expected = ou.realized_utility(
        quality=ou.quality_proxy(tel), cost_tokens=tel["tokens"], latency_s=tel["latency_s"], preference=0.6,
    )
    assert out["arm_id"] == decision.arm_id
    assert out["reward"] == pytest.approx(expected)
    stats = bandit.recipe_arms(ou.TaskFeatures.from_dict(plan.features), desk_id="d")[decision.arm_id]
    assert stats["n"] == 1


def test_desk_plan_uses_learned_recipe_without_exploring(monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import cos

    feat = ou.extract_features(RESEARCH, preference=0.6, provider_diversity=2, task_type="work")
    prior = ou.choose_initial_policy(feat, effort=0.6).arm_id
    alt = ou.NEIGHBORS[prior][0]
    _record(alt, feat, desk="desk-x", quality_bump=True)
    _record(prior, feat, desk="desk-x", quality_bump=False)
    monkeypatch.setattr(random, "random", lambda: 0.0)
    d, plan = cos.plan_for(RESEARCH, effort=0.6, harnesses=["grok", "claude"], desk_id="desk-x", task_type="work")
    assert d.arm_id == alt and not d.explored
    assert orch.validate_plan(plan) == []
