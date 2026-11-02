"""Utility-chosen shape for /work and /auto, with the template as fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from okstratr import orchestration as orch
from okstratr import orchestration_utility as ou

RESEARCH = "Compare the evidence on remote work across sources; which claims disagree and why?"


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(d))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    for k in ("OKSTRATR_HARNESS_PREFER", "OKSTRATR_MODEL_BY_HARNESS", "OKSTRATR_HERDR_KIND"):
        monkeypatch.delenv(k, raising=False)
    from okstratr.harness import config as hcfg

    h = hcfg.default_config()
    h.enabled = ["grok"]
    h.preference = ["grok"]
    hcfg.save(h)
    import okstratr.bandit as bandit
    import okstratr.blackboard as bb
    import okstratr.dag as dag
    import okstratr.desks as desks

    bb._DEFAULT = None
    bb._DEFAULT_PATH = None
    dag._DEFAULT = None
    dag._DEFAULT_PATH = None
    desks._DEFAULT = None
    desks._DEFAULT_PATH = None
    bandit.reset_cache()
    return d


def _decision(text: str, effort: float, harnesses: int = 1) -> ou.PolicyDecision:
    feat = ou.extract_features(text, preference=effort, provider_diversity=harnesses)
    return ou.choose_initial_policy(feat, effort=effort)


def test_trivial_prompt_is_single_node_at_every_effort() -> None:
    for e in (0.0, 0.3, 0.6, 1.0):
        plan = orch.plan_from_decision("Summarise this note", _decision("Summarise this note", e))
        assert len(plan.nodes) == 1
        assert orch.validate_plan(plan) == []


def test_research_plan_verifies_before_synthesis() -> None:
    d = _decision(RESEARCH, 0.6, harnesses=2)
    plan = orch.plan_from_decision(RESEARCH, d, harnesses=["grok", "claude"], models_by_harness={"grok": "g1"})
    assert orch.validate_plan(plan) == []
    by = {n.node_id: n for n in plan.nodes}
    invs = [n for n in plan.nodes if n.node_type == "investigate"]
    assert len(invs) >= 2
    assert by["verify"].dependencies == [n.node_id for n in invs]
    assert by["synth"].dependencies == ["verify"]
    # diverse recipe spreads harnesses; each seat has its own method and query
    assert {n.harness for n in invs} == {"grok", "claude"}
    assert by["inv-0"].model == "g1"
    assert len({n.method_hint for n in invs}) == len(invs)
    assert all(n.retrieval_query and len(n.retrieval_query) <= 240 for n in invs)


def test_reducers_for_wide_fanout() -> None:
    d = ou.decision_for_arm("swarm_8", ou.extract_features(RESEARCH, preference=1.0))
    d.include_reduce = True
    plan = orch.plan_from_decision(RESEARCH, d)
    assert orch.validate_plan(plan) == []
    reds = [n for n in plan.nodes if n.node_type == "reduce"]
    assert len(reds) == 4
    verify = next(n for n in plan.nodes if n.node_type == "verify")
    assert sorted(verify.dependencies) == sorted(r.node_id for r in reds)


def test_decompose_lists_into_slices() -> None:
    text = "Answer these:\n1. What changed in the 2024 release?\n2. Which users are affected by it?"
    tasks = ou.decompose_tasks(text, 2, ou.extract_features(text))
    assert "Focus independently on this subproblem only" in tasks[0]["description"]
    assert "2024 release" in tasks[0]["description"].split("subproblem only:")[1]
    assert "users are affected" in tasks[1]["description"].split("subproblem only:")[1]
    assert ou.method_hints_for(1, "high") == [""]
    assert ou.method_hints_for(3, "low") == ["", "", ""]


def test_break_down_uses_utility_and_records_decision(state_dir: Path) -> None:
    from okstratr import cos, dag, evidence

    dag.seat_root(RESEARCH)
    out = cos.break_down(RESEARCH, kind="auto", effort=0.6)
    assert out["decision"]["recipe"].startswith("ivs_")
    assert out["decision"]["candidates"]
    rid = out["run_id"]
    assert (evidence.run_dir(rid) / "plan.json").exists()
    assert evidence.run_evidence_path(rid).exists()
    g = dag.default_dag(force_reload=True)
    inv = [n for n in g.nodes.values() if n.id.startswith("investigator")]
    assert all(n.run_id == rid and n.node_type == "investigate" and n.method_hint for n in inv)
    # re-running keeps the same run and does not duplicate nodes
    again = cos.break_down(RESEARCH, kind="auto", effort=0.6)
    assert again["run_id"] == rid
    assert again["idempotent"] is True


def test_break_down_reshapes_cleanly(state_dir: Path) -> None:
    """Lowering effort drops stale pending seats from the wider shape."""
    from okstratr import cos, dag

    dag.seat_root(RESEARCH)
    cos.break_down(RESEARCH, kind="auto", effort=0.6)
    cos.break_down(RESEARCH, kind="auto", effort=0.1)
    g = dag.default_dag(force_reload=True)
    assert [n for n in g.nodes if n != "root"] == ["investigator"]
    assert not g.nodes["investigator"].depends_on or g.nodes["investigator"].depends_on == ["root"]


@pytest.mark.parametrize("kind", ["auto", "work"])
def test_break_down_falls_back_to_template(state_dir: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    from okstratr import cos, dag

    def boom(*a, **k):
        raise RuntimeError("planner broke")

    monkeypatch.setattr(cos, "plan_for", boom)
    monkeypatch.setattr(cos, "work_plan_for", boom)
    dag.seat_root("Anything")
    out = cos.break_down("Anything", kind=kind)
    assert out["ok"] is True
    assert out["decision"] is None
    g = dag.default_dag(force_reload=True)
    assert {"investigator", "synthesizer", "verifier"}.issubset(g.nodes)


def test_node_prompt_carries_method_and_query() -> None:
    from okstratr import dag, herdr

    n = dag.Node(id="investigator-1", title="Investigate", objective="Look", method_hint="corroboration: x",
                 retrieval_query="remote work")
    p = herdr._node_prompt(n)
    assert "Method: corroboration: x" in p and "remote work" in p
    assert herdr._node_prompt(dag.Node(id="a", title="A", objective="B")) == "A — B"
