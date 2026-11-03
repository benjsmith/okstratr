"""Candidate set (template shape always considered), code tasks, and cheap-model routing."""
from __future__ import annotations

from pathlib import Path

import pytest

from okstratr import model_routing as mr
from okstratr import orchestration_utility as ou

RESEARCH = "Compare the evidence on remote work across sources; which claims disagree and why?"
CODE = "Fix the failing unit test in the parser module and make the test suite pass"


@pytest.fixture(autouse=True)
def _state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path))


def _ids(feat: ou.TaskFeatures) -> list[str]:
    return [c.policy_id for c in ou.generate_candidates(feat)]


def test_parallel_diverse_k_present_with_two_or_more_harnesses() -> None:
    for k in (2, 3, 5):
        feat = ou.extract_features(RESEARCH, preference=0.6, provider_diversity=k)
        ids = _ids(feat)
        assert "parallel_diverse_k" in ids
        assert len(ids) <= ou.MAX_CANDIDATES == 7
        c = next(c for c in ou.generate_candidates(feat) if c.policy_id == "parallel_diverse_k")
        assert c.n_investigators == min(k, ou.DIVERSE_K_CAP)


def test_parallel_diverse_k_absent_for_one_harness_or_simple_task() -> None:
    assert "parallel_diverse_k" not in _ids(ou.extract_features(RESEARCH, preference=0.6, provider_diversity=1))
    assert "parallel_diverse_k" not in _ids(ou.extract_features("Rename the config file", preference=0.6,
                                                                 provider_diversity=3))


def test_decision_says_why_the_template_shape_lost() -> None:
    feat = ou.extract_features(CODE, preference=0.5, provider_diversity=2)
    d = ou.choose_initial_policy(feat, effort=0.5)
    assert d.arm_id != "parallel_diverse_k"
    assert "parallel_diverse_k lost to" in d.reason or "parallel_diverse_k ties" in d.reason


def test_explain_loss_tie_and_loss() -> None:
    feat = ou.extract_features(RESEARCH, preference=0.6, provider_diversity=2)
    a = ou.make_candidate("ivs_diverse_2", feat)
    k = ou.make_candidate("parallel_diverse_k", feat)
    assert "ties" in ou.explain_loss(a, k, 0.6)
    single = ou.make_candidate("single", feat)
    msg = ou.explain_loss(a, single, 0.6)
    assert msg.startswith("single lost to ivs_diverse_2 by ") and "ΔQ" in msg
    assert ou.explain_loss(a, a, 0.6) == ""


def test_code_task_is_not_simple_and_considers_tools_verify() -> None:
    feat = ou.extract_features(CODE, preference=0.5, provider_diversity=2)
    assert not ou.is_simple(feat)
    assert "tools_verify" in _ids(feat)
    assert ou.choose_initial_policy(feat, effort=0.5).arm_id == "tools_verify"


def test_unknown_model_defaults_to_strong() -> None:
    pick, table = mr.choose(["claude-haiku", "claude-sonnet-4"], "code", 0.1, stats={})
    assert pick == "claude-sonnet-4"
    assert not next(e for e in table if e.model == "claude-haiku").eligible


def test_learned_cheap_model_wins_when_it_rarely_fails() -> None:
    stats: dict[str, mr.ModelStats] = {}
    for _ in range(10):
        mr.record_outcome("claude-haiku", "code", failed=False, tokens=2000, stats=stats)
    pick, _ = mr.choose(["claude-haiku", "claude-sonnet-4"], "code", 0.2, stats=stats)
    assert pick == "claude-haiku"


def test_cheap_model_loses_when_it_fails_and_spins() -> None:
    stats: dict[str, mr.ModelStats] = {}
    for i in range(10):
        mr.record_outcome("claude-haiku", "research", failed=i % 3 != 0, tokens=5000 if i % 3 else 2000,
                          stats=stats)
    pick, table = mr.choose(["claude-haiku", "claude-sonnet-4"], "research", 0.2, stats=stats)
    assert pick == "claude-sonnet-4"
    cheap = next(e for e in table if e.model == "claude-haiku")
    assert cheap.eligible and cheap.p_fail > 0.4


def test_rework_cost_grows_with_failure_rate() -> None:
    lo = mr.estimate("claude-haiku", "claude-sonnet-4", "code", 0.5,
                     stats={mr._key("claude-haiku", "code"): mr.ModelStats(n=10, fails=0)})
    hi = mr.estimate("claude-haiku", "claude-sonnet-4", "code", 0.5,
                     stats={mr._key("claude-haiku", "code"): mr.ModelStats(n=10, fails=8)})
    assert hi.cnorm > lo.cnorm and hi.q < lo.q


def test_outcomes_persist_in_state_dir() -> None:
    mr.record_outcome("claude-haiku", "code", failed=True, tokens=3000)
    mr.record_outcome("claude-haiku", "code", failed=False, tokens=2000)
    st = mr.load()[mr._key("claude-haiku", "code")]
    assert (st.n, st.fails) == (2, 1)


def test_author_outcome_fails_on_error_or_rejected_claims() -> None:
    from types import SimpleNamespace

    from okstratr import orchestration as orch
    from okstratr.evidence import Finding

    nodes = [
        orch.PlanNode("a", "investigate", "x", model="m-ok"),
        orch.PlanNode("b", "investigate", "x", model="m-err"),
        orch.PlanNode("c", "investigate", "x", model="m-bad"),
        orch.PlanNode("v", "verify", "x", model="m-ver"),
        orch.PlanNode("d", "investigate", "x", model="m-unrun"),
    ]
    state = orch.RunState(plan=orch.OrchestrationPlan("r", "t", nodes))
    state.results = {
        "a": orch.NodeResult("a", tokens=10),
        "b": orch.NodeResult("b", ok=False, tokens=4),
        "c": orch.NodeResult("c", tokens=7),
        "v": orch.NodeResult("v"),
    }
    findings = [
        Finding("a1", node_id="a", verdict="supported"),
        Finding("a2", node_id="a", verdict="contradicted"),
        Finding("a3", node_id="a", verdict="supported"),
        Finding("c1", node_id="c", verdict="contradicted"),
        Finding("c2", node_id="c", verdict="supported"),
    ]
    run = SimpleNamespace(store=SimpleNamespace(findings=findings))
    got = {m: (f, t) for m, f, t in orch.author_outcomes(state, run)}
    assert got == {"m-ok": (False, 10.0), "m-err": (True, 4.0), "m-bad": (True, 7.0)}


def test_plural_code_words_mark_a_code_task() -> None:
    feat = ou.extract_features("Make the ledger handle the new format. Keep the existing tests passing.",
                               preference=0.5, provider_diversity=2)
    assert feat.code


def test_cited_corpus_questions_are_research() -> None:
    feat = ou.extract_features("Answer using only the files in corpus/ and cite the files you used.",
                               preference=0.5, provider_diversity=1)
    assert feat.research
