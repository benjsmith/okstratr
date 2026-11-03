"""Expansion while ΔU > threshold, the OBJECTIVE_MET stop rule, and reducers."""

from __future__ import annotations

import json

from okstratr import orchestration as orch
from okstratr import orchestration_utility as ou
from okstratr.orchestration import NodeResult, PlanNode

RESEARCH = "Compare the evidence on remote work across sources; which claims disagree and why?"

GAP = {"conflicts": 2, "unsupported": 2, "confidence": 0.2, "unresolved": ["which study is newer"]}
MILD = {"conflicts": 0, "unsupported": 0, "confidence": 0.6, "unresolved": ["one date"]}
CLEAN = {"conflicts": 0, "unsupported": 0, "confidence": 0.9, "unresolved": []}


def _exp(pref: float, v: dict, so_far: int = 0, **kw) -> ou.ExpansionDecision:
    return ou.choose_expansion(
        preference=pref, independence="high", allow_expand=True, verification=v,
        findings_n=4, expansions_so_far=so_far, nodes_so_far=4, remaining_nodes=20, **kw,
    )


def test_expand_only_when_gap_and_quality_weighted() -> None:
    assert _exp(1.0, GAP).expand is True
    assert _exp(1.0, CLEAN).expand is False
    assert "threshold" in _exp(1.0, CLEAN).reason
    # a small gap is worth a second look at Maximum, not at Economy
    assert _exp(1.0, MILD).expand is True
    assert _exp(0.0, MILD).expand is False


def test_expansion_decays_and_is_capped() -> None:
    du_reasons = [_exp(1.0, GAP, so_far=k) for k in range(5)]
    assert du_reasons[3].expand is False and "cap" in du_reasons[3].reason
    assert _exp(1.0, GAP, max_expansions=0).reason == "expansion cap reached"
    assert ou.choose_expansion(
        preference=1.0, independence="high", allow_expand=True, verification=GAP, findings_n=4,
        expansions_so_far=0, nodes_so_far=23, remaining_nodes=1,
    ).reason == "node budget exhausted"
    assert ou.choose_expansion(
        preference=1.0, independence="high", allow_expand=False, verification=GAP, findings_n=4,
        expansions_so_far=0, nodes_so_far=4, remaining_nodes=20,
    ).expand is False


def test_objective_met_parsing() -> None:
    assert ou.parse_objective_met("x\nOBJECTIVE_MET: yes") == (True, "")
    assert ou.parse_objective_met("OBJECTIVE_MET: yes\nOBJECTIVE_MET: no — dates missing") == (False, "dates missing")
    assert ou.parse_objective_met("no token here") == (None, "")
    assert ou.strip_objective_met("Answer.\nOBJECTIVE_MET: yes") == "Answer."


def test_stop_rule() -> None:
    base = dict(preference=1.0, allow_expand=True, verification=GAP, findings_n=4, nodes_so_far=4, remaining_nodes=20)
    assert ou.should_continue(objective_met=True, **base).reason == "OBJECTIVE_MET: yes"
    assert ou.should_continue(objective_met=None, **base).reason == "no stop token; auto-stop"
    assert ou.should_continue(objective_met=False, last_wave_new_findings=0, **base).expand is False
    assert ou.should_continue(objective_met=False, concat=True, **base).expand is False
    assert ou.should_continue(objective_met=False, gap="dates", **base).expand is True
    # a gap reported by the synthesizer overrides a confident verifier
    clean = dict(base, verification=dict(CLEAN, confidence=0.95))
    assert ou.should_continue(objective_met=False, gap="dates", **clean).expand is True
    assert ou.should_continue(objective_met=False, **clean).expand is False


# ── end to end on the scheduler with a fake harness ────────────────


def _fake_runner(verify_gap: bool, synth_tail: str):
    def run(node: PlanNode, inputs: dict[str, NodeResult]) -> NodeResult:
        if node.node_type in ("investigate", "reduce"):
            body = {"findings": [{"claim": f"claim from {node.node_id}", "evidence": [{"source": node.node_id}],
                                  "confidence": 0.6}]}
            return NodeResult(node.node_id, True, json.dumps(body), tokens=400, latency_s=1.0)
        if node.node_type == "verify":
            first = node.node_id == "verify"
            v = GAP if (verify_gap and first) else CLEAN
            return NodeResult(node.node_id, True, json.dumps(v), tokens=300, latency_s=1.0)
        return NodeResult(node.node_id, True, f"Answer.\n{synth_tail}", tokens=300, latency_s=1.0)
    return run


def _plan(pref: float) -> orch.OrchestrationPlan:
    feat = ou.extract_features(RESEARCH, preference=pref, provider_diversity=2)
    d = ou.choose_initial_policy(feat, effort=pref)
    return orch.plan_from_decision(RESEARCH, d, harnesses=["grok", "claude"])


def test_verify_gap_triggers_one_targeted_expansion() -> None:
    plan = _plan(1.0)
    hook = orch.AdaptiveRun(plan, harnesses=["grok", "claude"])
    st = orch.run_plan(plan, _fake_runner(True, "OBJECTIVE_MET: yes"), after_node=hook)
    ids = [n.node_id for n in st.plan.nodes]
    assert any(i.startswith("inv-x") for i in ids) and "verify-x1" in ids
    synth = st.plan.node_map()["synth"]
    assert synth.dependencies == ["verify-x1"]
    assert st.completed == set(ids)
    assert hook.expansions == 1  # second verify is clean → stop
    assert hook.stop_reason == "OBJECTIVE_MET: yes"
    assert len(hook.store.findings) > 0


def test_no_expansion_when_clean_or_disallowed() -> None:
    plan = _plan(1.0)
    n0 = len(plan.nodes)
    st = orch.run_plan(plan, _fake_runner(False, "OBJECTIVE_MET: yes"), after_node=orch.AdaptiveRun(plan))
    assert len(st.plan.nodes) == n0
    plan = _plan(1.0)
    plan.allow_expand = False
    st = orch.run_plan(plan, _fake_runner(True, "OBJECTIVE_MET: no — more"), after_node=orch.AdaptiveRun(plan))
    assert len(st.plan.nodes) == len(_plan(1.0).nodes)


def test_objective_not_met_runs_bounded_continue_waves() -> None:
    plan = _plan(1.0)
    hook = orch.AdaptiveRun(plan)
    st = orch.run_plan(plan, _fake_runner(True, "OBJECTIVE_MET: no — dates still missing"), after_node=hook)
    synths = [n for n in st.plan.nodes if n.node_type == "synthesize"]
    from okstratr import limits

    assert 2 <= len(synths) <= 1 + limits.MAX_EXPANSIONS
    assert len(st.plan.nodes) <= 24
    assert orch.dag_depth(st.plan.nodes) <= 8
    assert st.final() is not None and st.final().node_id == synths[-1].node_id
    assert hook.stop_reason


def test_missing_token_stops_after_first_synth() -> None:
    plan = _plan(1.0)
    hook = orch.AdaptiveRun(plan)
    st = orch.run_plan(plan, _fake_runner(False, "(no token)"), after_node=hook)
    assert sum(1 for n in st.plan.nodes if n.node_type == "synthesize") == 1
    assert hook.stop_reason == "no stop token; auto-stop"


def test_extension_is_atomic() -> None:
    plan = _plan(1.0)
    bad = orch.Extension(nodes=[PlanNode("x", "investigate", "o")], rewire={"synth": ["missing"]})
    before = [list(n.dependencies) for n in plan.nodes]
    assert orch._apply_extension(plan, bad, plan.bounds.clamp(), set()) is False
    assert [list(n.dependencies) for n in plan.nodes] == before
    assert "x" not in plan.node_map()
    # never rewire a node that already started
    ok = orch.Extension(nodes=[PlanNode("y", "investigate", "o")], rewire={"synth": ["y"]})
    assert orch._apply_extension(plan, ok, plan.bounds.clamp(), {"synth"}) is False


def test_reducers_run_and_replace_inputs() -> None:
    feat = ou.extract_features(RESEARCH, preference=1.0)
    d = ou.decision_for_arm("swarm_8", feat)
    d.include_reduce = True
    plan = orch.plan_from_decision(RESEARCH, d)
    hook = orch.AdaptiveRun(plan)
    st = orch.run_plan(plan, _fake_runner(False, "OBJECTIVE_MET: yes"), after_node=hook)
    assert {f"red-{i}" for i in range(4)} <= st.completed
    assert "inv-0" in hook.store.replaced_nodes


def test_prompt_for_synth_asks_for_stop_line() -> None:
    plan = _plan(1.0)
    synth = plan.node_map()["synth"]
    p = orch.prompt_for(synth, {"verify": NodeResult("verify", True, "ok")}, context="{}")
    assert "OBJECTIVE_MET" in p and "From verify" in p
    inv = plan.node_map()["inv-0"]
    assert "Method:" in orch.prompt_for(inv, {})
