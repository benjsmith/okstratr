"""Verifier on the strongest allowed model; authors by learned routing, strong when unknown."""

from __future__ import annotations

from pathlib import Path

import pytest

from okstratr import model_policy as mp
from okstratr import orchestration as orch
from okstratr import orchestration_utility as ou
from okstratr.harness import config as hcfg

RESEARCH = "Compare the evidence on remote work across sources; which claims disagree and why?"
OPEN = {"allowed": [], "denied": []}


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    for k in ("OKSTRATR_WORKSPACE", "OKSTRATR_OKBAY_WORKSPACE", "OKSTRATR_HARNESS_PREFER",
              "OKSTRATR_MODEL_BY_HARNESS", "OKSTRATR_MODEL"):
        monkeypatch.delenv(k, raising=False)
    from okstratr import bandit

    bandit.reset_cache()
    return state


def test_model_strength_matches_switchbay_heuristic() -> None:
    assert mp.model_strength("") == 0.35
    assert mp.model_strength("claude-haiku") < mp.model_strength("claude-sonnet-4") < mp.model_strength("claude-opus-4")
    assert mp.model_strength("anthropic/claude-opus-4") == mp.model_strength("claude-opus-4")
    assert mp.model_strength("llama3-8b") < 0.3  # small local model counts as cheap
    assert mp.model_strength("qwen-32b") > mp.model_strength("qwen-14b")
    assert mp.model_strength("gpt-4o-mini") < 0.3


def test_critic_is_strongest_regardless_of_effort() -> None:
    pairs = [("claude", "claude-haiku"), ("claude", "claude-sonnet-4"), ("claude", "claude-opus-4")]
    assert mp.pick_critic(pairs) == ("claude", "claude-opus-4")
    for e in (0.0, 0.5, 1.0):
        out = mp.assign_models(["claude"], e, cfg=hcfg.default_config(), policy=OPEN)
        assert mp.pick_critic(out["pairs"]) == ("claude", "claude-opus-4")


def test_critic_tie_prefers_harness_authors_did_not_use() -> None:
    pairs = [("grok", "grok-4.6"), ("claude", "claude-opus-4")]
    assert mp.pick_critic(pairs) == ("grok", "grok-4.6")
    assert mp.pick_critic(pairs, avoid_harnesses={"grok"}) == ("claude", "claude-opus-4")


def test_unknown_task_class_defaults_authors_to_strong_model() -> None:
    cfg = hcfg.default_config()
    for e in (0.1, 0.5, 0.9):
        a = mp.assign_models(["claude"], e, cfg=cfg, policy=OPEN)["authors"]["claude"]
        # Strongest author pair; the very strongest stays with the critic.
        assert a == "claude-sonnet-4"


def test_learned_cheap_model_wins_author_seat_at_low_effort() -> None:
    from okstratr import model_routing as mr

    stats: dict[str, mr.ModelStats] = {}
    for _ in range(12):
        mr.record_outcome("claude-haiku", "code", failed=False, tokens=2000, stats=stats)
        mr.record_outcome("claude-sonnet-4", "code", failed=False, tokens=2000, stats=stats)
    cfg = hcfg.default_config()
    low = mp.assign_models(["claude"], 0.1, cfg=cfg, policy=OPEN, task_class="code", stats=stats)
    assert low["authors"]["claude"] == "claude-haiku"
    # Unknown class still goes strong even with code data.
    other = mp.assign_models(["claude"], 0.1, cfg=cfg, policy=OPEN, task_class="research", stats=stats)
    assert other["authors"]["claude"] == "claude-sonnet-4"


def test_pinned_model_wins_for_authors_when_allowed() -> None:
    cfg = hcfg.default_config()
    out = mp.assign_models(["claude"], 0.1, cfg=cfg, policy=OPEN, pinned={"claude": "claude-opus-4"})
    assert out["authors"]["claude"] == "claude-opus-4"
    denied = {"allowed": [], "denied": ["claude/claude-opus-4"]}
    out = mp.assign_models(["claude"], 0.1, cfg=cfg, policy=denied, pinned={"claude": "claude-opus-4"})
    assert out["authors"]["claude"] != "claude-opus-4"


def test_denied_models_are_never_picked() -> None:
    cfg = hcfg.default_config()
    pol = {"allowed": [], "denied": ["claude/claude-opus-4", "grok/*"]}
    out = mp.assign_models(["grok", "claude"], 1.0, cfg=cfg, policy=pol)
    assert out["harnesses"] == ["claude"]
    assert ("claude", "claude-opus-4") not in out["pairs"]
    assert mp.pick_critic(out["pairs"]) == ("claude", "claude-sonnet-4")


def test_plan_verifier_on_critic_and_investigators_on_band() -> None:
    feat = ou.extract_features(RESEARCH, preference=0.2, provider_diversity=1, task_type="work")
    d = ou.choose_initial_policy(feat, effort=0.2)
    d.include_verify = True
    d.n_investigators = max(2, d.n_investigators)
    out = mp.assign_models(["claude"], 0.2, cfg=hcfg.default_config(), policy=OPEN)
    plan = orch.plan_from_decision(
        RESEARCH, d, harnesses=["claude"], models_by_harness=out["authors"], critic_pairs=out["pairs"]
    )
    verify = next(n for n in plan.nodes if n.node_type == "verify")
    invs = [n for n in plan.nodes if n.node_type == "investigate"]
    assert (verify.harness, verify.model) == ("claude", "claude-opus-4")
    assert all(n.model == "claude-sonnet-4" for n in invs)


def test_reverify_and_continue_waves_use_critic() -> None:
    feat = ou.extract_features(RESEARCH, preference=0.9, provider_diversity=1, task_type="work")
    d = ou.choose_initial_policy(feat, effort=0.9)
    d.include_verify = True
    out = mp.assign_models(["claude"], 0.9, cfg=hcfg.default_config(), policy=OPEN)
    plan = orch.plan_from_decision(
        RESEARCH, d, harnesses=["claude"], models_by_harness=out["authors"], critic_pairs=out["pairs"]
    )
    exp = ou.ExpansionDecision(expand=True, n_extra=1, objectives=["x"], reason="t")
    ext = orch.expansion_nodes(plan, exp, harnesses=["claude"], models_by_harness=out["authors"],
                               critic_pairs=out["pairs"])
    v = [n for n in ext.nodes if n.node_type == "verify"][0]
    assert v.model == "claude-opus-4"
    cont = orch.continue_wave(plan, exp, harnesses=["claude"], models_by_harness=out["authors"],
                              critic_pairs=out["pairs"])
    v = [n for n in cont.nodes if n.node_type == "verify"][0]
    assert v.model == "claude-opus-4"


def test_plan_for_respects_workspace_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import cos

    hcfg.save(hcfg.default_config())
    monkeypatch.setenv("OKSTRATR_WORKSPACE", "ws-z")
    mp.set_lists("ws-z", denied=["claude/claude-opus-4", "grok/grok-4.6"])
    _, plan = cos.plan_for(RESEARCH, effort=0.9, harnesses=["grok", "claude"], task_type="work")
    picked = {(n.harness, n.model) for n in plan.nodes if n.harness}
    assert ("claude", "claude-opus-4") not in picked
    assert ("grok", "grok-4.6") not in picked
    assert picked
