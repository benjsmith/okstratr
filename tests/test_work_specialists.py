"""/work hires specialists in sequence: gather context → write → review."""

from __future__ import annotations

from pathlib import Path

import pytest

from okstratr import model_policy as mp
from okstratr import orchestration as orch


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
    from okstratr import bandit, dag

    bandit.reset_cache()
    dag._DEFAULT = None
    dag._DEFAULT_PATH = None
    return state


@pytest.mark.parametrize(
    ("objective", "expected"),
    [
        ("Do the thing", ["context", "write", "review"]),
        ("Write the project plan with milestones", ["context", "plan", "review"]),
        ("Tell the team: status update for the launch", ["context", "comms", "review"]),
        ("Catch me up on the migration", ["context"]),
        ("Review the plan for drift", ["review"]),
    ],
)
def test_specialists_follow_the_brief(objective: str, expected: list[str]) -> None:
    assert orch.project_specialists(objective) == expected


def test_plan_runs_specialists_in_sequence() -> None:
    plan = orch.plan_projects("Write the project plan with milestones",
                              harnesses=["claude", "codex"],
                              models_by_harness={"claude": "sonnet", "codex": "gpt-5"})
    assert plan.strategy == "projects"
    assert plan.allow_expand is False
    ids = [n.node_id for n in plan.nodes]
    assert ids == ["context", "plan", "review"]
    by = {n.node_id: n for n in plan.nodes}
    assert by["context"].dependencies == []
    assert by["plan"].dependencies == ["context"]
    assert by["review"].dependencies == ["plan"]
    assert by["review"].node_type == "verify"
    assert by["review"].independence == "high"
    assert orch.ensure_valid(plan) is plan


def test_review_gets_strongest_model_and_authors_default_strong() -> None:
    from okstratr import cos
    from okstratr.harness import config as hcfg

    cfg = hcfg.default_config()
    cfg.enabled = ["pi", "codex"]
    cfg.models = {"pi": ["gpt-4.1-mini", "claude-sonnet-4", "grok-4"], "codex": ["gpt-5"]}
    hcfg.save(cfg)

    low = cos.work_plan_for("Do the thing", effort=0.1)
    high = cos.work_plan_for("Do the thing", effort=0.9)
    lo = {n.node_id: n for n in low.nodes}
    hi = {n.node_id: n for n in high.nodes}
    pairs = mp.candidate_pairs(["pi", "codex"], None, cfg=cfg)
    top = max(mp.model_strength(m) for _h, m in pairs)
    assert mp.model_strength(lo["review"].model) == top
    assert mp.model_strength(hi["review"].model) == top
    # No routing data yet: authors get the strongest model at any effort (cheap only once learned).
    assert lo["write"].model == hi["write"].model
    # review on a different harness from the authors when one is available
    assert lo["review"].harness != lo["write"].harness


def test_denied_models_are_not_picked() -> None:
    from okstratr import cos

    first = {n.node_id: n for n in cos.work_plan_for("Do the thing", effort=0.1).nodes}
    mp.add(None, f"{first["review"].harness}/{first["review"].model}", deny=True)
    again = {n.node_id: n for n in cos.work_plan_for("Do the thing", effort=0.1).nodes}
    assert (again["review"].harness, again["review"].model) != (first["review"].harness, first["review"].model)


def test_break_down_work_uses_specialists_and_saves_run(env: Path) -> None:
    from okstratr import cos, dag, evidence

    dag.seat_root("Write the project plan with milestones")
    out = cos.break_down("Write the project plan with milestones", kind="work", effort=0.5)
    assert out["ok"]
    assert out["nodes"] == ["context", "plan", "review"]
    g = dag.default_dag(force_reload=True)
    assert g.nodes["plan"].depends_on == ["context"]
    assert g.nodes["review"].role == "verifier"
    assert g.nodes["context"].title == "Gather context"
    assert out["run_id"]
    assert (evidence.run_dir(out["run_id"]) / "plan.json").exists()
    note = out["plan"]
    assert note


def test_work_falls_back_to_template_when_planning_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import cos, dag

    monkeypatch.setattr(orch, "plan_projects", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    dag.seat_root("Do the thing")
    out = cos.break_down("Do the thing", kind="work")
    assert out["ok"]
    assert "verifier" in out["nodes"] and "synthesizer" in out["nodes"]


def test_auto_still_uses_the_utility() -> None:
    from okstratr import cos

    decision, plan = cos.plan_for("Compare the evidence on remote work across sources; which claims disagree and why?",
                                  effort=0.6)
    assert plan.strategy != "projects"
    assert decision.arm_id
