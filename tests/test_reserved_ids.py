"""Retired node ids are reserved and never handed out again."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from okstratr import dag
from okstratr import orchestration as orch


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    dag._DEFAULT = None
    dag._DEFAULT_PATH = None
    return state


def test_alloc_skips_live_and_retired(tmp_path: Path) -> None:
    g = dag.Dag(path=tmp_path / "d.json")
    g.add("a", "A", save=False)
    g.add("b", "B", save=False)
    assert g.archive("b", save=False)
    assert g.archived_ids == ["b"]
    assert g.alloc_node_id("a") == "a-2"
    assert g.alloc_node_id("b") == "b-2"
    assert g.alloc_node_id("c") == "c"
    assert g.alloc_node_id("c", taken={"c"}) == "c-2"


def test_dag_json_round_trip_and_backward_compatible(tmp_path: Path) -> None:
    p = tmp_path / "d.json"
    g = dag.Dag(path=p)
    g.add("root", "R")
    raw = json.loads(p.read_text())
    assert "archived_ids" not in raw  # unchanged format when unused
    g.add("w", "W", depends_on=["root"])
    g.archive("w")
    raw = json.loads(p.read_text())
    assert raw["archived_ids"] == ["w"]
    assert dag.Dag.open(p).archived_ids == ["w"]
    # An old dag.json (no archived_ids, or a bare list) still loads.
    p.write_text(json.dumps({"version": 1, "nodes": [{"id": "root", "title": "R"}]}))
    assert dag.Dag.open(p).archived_ids == []
    p.write_text(json.dumps([{"id": "root", "title": "R"}]))
    assert list(dag.Dag.open(p).nodes) == ["root"]


def test_reset_clears_reserved_ids(tmp_path: Path) -> None:
    g = dag.Dag(path=tmp_path / "d.json")
    g.add("w", "W")
    g.archive("w")
    g.seat_root("new", reset=True)
    assert g.archived_ids == []
    g.add("w", "W")
    g.archive("w")
    g.reset()
    assert g.archived_ids == []


def test_retire_worker_reserves_id_and_breakdown_avoids_it() -> None:
    from okstratr import cos, desks, kernel

    desks.start("Write the project plan with milestones", kind="work")
    assert kernel.retire_worker("context")["ok"]
    g = dag.default_dag(force_reload=True)
    assert "context" in g.archived_ids
    out = cos.break_down("Write the project plan with milestones", kind="work")
    assert "context" not in out["nodes"]
    assert "context-2" in out["nodes"]
    g = dag.default_dag(force_reload=True)
    assert g.nodes["plan"].depends_on == ["context-2"]


def test_plan_reserves_retired_ids_and_round_trips() -> None:
    plan = orch.plan_projects("Do the thing", harnesses=["claude", "codex"])
    assert "archived_ids" not in plan.to_dict()
    assert not plan.retire("context")  # something depends on it
    assert plan.retire("review")
    assert plan.archived_ids == ["review"]
    assert plan.alloc_node_id("review") == "review-2"
    again = orch.OrchestrationPlan.from_dict(plan.to_dict())
    assert again.archived_ids == ["review"]
    bad = orch.OrchestrationPlan.from_dict(plan.to_dict())
    bad.nodes.append(orch.PlanNode(node_id="review", node_type="verify", objective="x",
                                   dependencies=["write"]))
    assert "node_id reuses a retired id" in orch.validate_plan(bad)


def test_expansion_never_reuses_retired_ids() -> None:
    plan = orch.OrchestrationPlan.from_dict({
        "run_id": "r", "strategy": "x", "allow_expand": True,
        "nodes": [{"node_id": "inv-1", "node_type": "investigate", "objective": "o"}],
        "archived_ids": ["inv-x1", "verify-x1"],
    })
    ids = plan.reserved_ids()
    assert {"inv-1", "inv-x1", "verify-x1"} <= ids
    assert plan.alloc_node_id("verify-x1") == "verify-x1-2"


def test_expansion_and_next_wave_skip_retired_ids() -> None:
    from okstratr import orchestration_utility as ou

    q = "Compare the evidence on remote work across sources; which claims disagree and why?"
    feat = ou.extract_features(q, preference=0.9, provider_diversity=1, task_type="work")
    d = ou.choose_initial_policy(feat, effort=0.9)
    d.include_verify = True
    plan = orch.plan_from_decision(q, d, harnesses=["claude"])
    exp = ou.ExpansionDecision(expand=True, n_extra=1, objectives=["x"], reason="t")
    first = orch.expansion_nodes(plan, exp, harnesses=["claude"])
    first_ids = [n.node_id for n in first.nodes]
    plan.archived_ids.extend(first_ids)  # as if those nodes were dropped
    again = orch.expansion_nodes(plan, exp, harnesses=["claude"])
    assert not set(first_ids) & {n.node_id for n in again.nodes}
    wave1 = [n.node_id for n in orch.continue_wave(plan, exp, harnesses=["claude"]).nodes]
    plan.archived_ids.extend(wave1)
    wave2 = [n.node_id for n in orch.continue_wave(plan, exp, harnesses=["claude"]).nodes]
    assert not set(wave1) & set(wave2)
