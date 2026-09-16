"""Kernel hire/retire, Herdr labels, effort, docs. Dry-run defaults."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "okstratr-state"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(d))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    import okstratr.bandit as bandit
    import okstratr.blackboard as bb
    import okstratr.dag as dag
    import okstratr.desks as desks
    import okstratr.status as status
    import okstratr.web_egress as web

    bb._DEFAULT = None
    bb._DEFAULT_PATH = None
    dag._DEFAULT = None
    dag._DEFAULT_PATH = None
    desks._DEFAULT = None
    desks._DEFAULT_PATH = None
    status._loaded = False
    status._loaded_from = None
    status._seated_objective = ""
    status._state = "setup"
    bandit.reset_cache()
    web.reset_cache()
    return d


def test_desk_org_persists_model_hints_and_effort(state_dir: Path) -> None:
    from okstratr import desks, status

    r = desks.start("Ship coverage", kind="work", effort=0.6)
    desk = r["desk"]
    assert desk["roles"][0] == "cos"
    org = desk["org"]
    assert org["cos"] == "cos"
    assert org["effort"] == pytest.approx(0.6)
    granted_ids = [g["id"] for g in org["granted"]]
    assert granted_ids[0] == "cos"
    assert all("model_hint" in g for g in org["granted"])
    snap = status.write_status()
    assert snap["effort"] == pytest.approx(0.6)
    assert snap["effort_slider"]["stub"] is False
    assert snap["effort_slider"]["bandit"] is True
    assert "weights" in snap["effort_slider"]
    assert snap["herdr_labels"]["desk_id"] == desk["id"]
    assert snap["herdr_labels"]["thread_id"] == desk["thread_id"]
    assert snap["focus_desk_id"] == desk["id"]
    assert snap["state"] == "quiet"  # CoS-only start lands quiet
    assert snap["desk"]["kind"] == "work"
    assert snap["desk"]["state"] == "quiet"


def test_work_auto_breakdown_uses_switchbay_roles(state_dir: Path) -> None:
    from okstratr import dag, desks

    desks.start("Do the thing", kind="work")
    g = dag.default_dag(force_reload=True)
    assert set(["investigator", "synthesizer", "verifier"]).issubset(g.nodes)
    assert "cos-clarify" not in g.nodes
    assert g.nodes["investigator"].role == "investigator"
    assert g.nodes["synthesizer"].depends_on == ["investigator"]


def test_hire_cap_refuses_over_limit(state_dir: Path) -> None:
    from okstratr import desks, kernel

    desks.start("Tiny", kind="work", effort=0.2)
    # low effort: CoS + planner, cap 2
    r = desks.hire("investigator")
    assert r["ok"] is False
    assert r.get("guard") == "hire_cap"
    assert r["cap"] == kernel.HIRE_CAP_LOW


def test_hire_grants_under_cap(state_dir: Path) -> None:
    from okstratr import desks

    desks.start("Roomy", kind="deck", effort=0.5)
    r = desks.hire({"role": "researcher", "model_hint": "diverse"})
    assert r["ok"] is True
    assert r["role"] == "researcher"
    assert "researcher" in r["roles"]
    assert r["roles"][0] == "cos"


def test_curate_refuses_worker_without_commit_path(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import desks, kernel
    from okstratr.kernel import hire_plan

    monkeypatch.delenv("OKSTRATR_OKBAY_REVIEWS", raising=False)
    monkeypatch.delenv("OKSTRATR_CURATE_COMMIT", raising=False)
    monkeypatch.delenv("OKSTRATR_OKBAY_COMMIT_PATH", raising=False)
    plan = hire_plan("curate pages", kind="curate")
    assert "curator_worker" not in plan["roles"]
    assert plan["curate_worker_refused"] is True

    desks.start("Curate docs", kind="curate")
    r = desks.hire("curator_worker")
    assert r["ok"] is False
    assert r.get("guard") == "curate_commit_path"


def test_curate_hires_worker_when_commit_path_configured(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr.kernel import hire_plan

    monkeypatch.setenv("OKSTRATR_OKBAY_REVIEWS", "1")
    plan = hire_plan("curate pages", kind="curate")
    assert "curator_worker" in plan["roles"]
    assert "curator_judge" in plan["roles"]
    assert plan["curate_worker_refused"] is False


def test_retire_worker_archives_and_shrinks_dag(state_dir: Path) -> None:
    from okstratr import blackboard, dag, desks, kernel

    desks.start("Retire me", kind="work")
    g = dag.default_dag(force_reload=True)
    before = len(g.nodes)
    assert "investigator" in g.nodes

    r = kernel.retire_worker("investigator")
    assert r["ok"] is True
    assert r["retired"] == "investigator"
    g2 = dag.default_dag(force_reload=True)
    assert "investigator" not in g2.nodes
    assert len(g2.nodes) == before - 1
    hits = blackboard.search("retired investigator")
    assert hits
    assert hits[-1]["author"] == "kernel"

    bad = kernel.retire_worker("root")
    assert bad["ok"] is False


def test_herdr_agent_id_format(state_dir: Path) -> None:
    from okstratr import dag, desks, herdr

    start = desks.start("Label me", kind="work")
    desk_id = start["desk"]["id"]
    g = dag.default_dag(force_reload=True)
    node = g.nodes["investigator"]
    aid = herdr.make_agent_id(desk_id, "investigator", node.id)
    assert aid.startswith("o")
    assert len(aid) <= herdr.AGENT_ID_MAX <= 32
    assert herdr.HERDR_NAME_RE.match(aid)
    labels = herdr.labels_for_node(node)
    assert labels["desk_id"] == desk_id
    assert labels["thread_id"]
    assert labels["format"] == "o{desk8}{role6}{node6}"
    assert labels["agent_id"] == aid
    # Long desk/role/node must still fit Herdr 32-char grammar
    long_id = herdr.make_agent_id("d" * 80, "investigator-role-name", "node-" + ("x" * 40))
    assert len(long_id) <= 32
    assert herdr.HERDR_NAME_RE.match(long_id)

    out = herdr.run_ready(limit=1, dry_run=True)
    assert out["dry_run"] is True
    assert out["ran"] == ["investigator"]
    assert out["results"][0]["herdr_labels"]["desk_id"] == desk_id
    agent = out["results"][0]["agent_id"]
    assert agent.startswith("o")
    assert len(agent) <= 32
    assert "--pane" in " ".join(" ".join(c) for c in out["results"][0]["would_exec"])


def test_focus_desk_stub(state_dir: Path) -> None:
    from okstratr import desks, herdr, status

    a = desks.start("First", kind="work")
    desks.stop()
    b = desks.start("Second", kind="code")
    focused = herdr.focus_desk(a["desk"]["id"])
    assert focused["ok"] is True
    assert focused["stub"] is True
    assert focused["focus_desk_id"] == a["desk"]["id"]
    assert "close_warning" in focused
    snap = status.write_status()
    assert snap["focus_desk_id"] == a["desk"]["id"]
    assert snap["ui"]["text_input"] is True
    assert "kernel" in snap["ui"]["close_warning"].lower()
    # unused
    _ = b


def test_okbay_workspace_framing(monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import okbay

    monkeypatch.delenv("OKSTRATR_OKBAY_WORKSPACE", raising=False)
    ws = okbay.active_workspace()
    assert ws["default_work_coverage"] is True
    assert ws["id"] == "work"
    assert ws["ingest"] is False
    assert "demo" in (ws["notes"] or "").lower() or okbay.DEMO_WORKSPACE_ID == "biocure"
    assert "opt-in" not in (ws["notes"] or "").lower() or "not an opt-in" in (ws["notes"] or "").lower()

    monkeypatch.setenv("OKSTRATR_OKBAY_WORKSPACE", "biocure")
    demo = okbay.active_workspace()
    assert demo["demo"] is True
    assert demo["id"] == "biocure"
    assert demo["default_work_coverage"] is False

    split = okbay.split_workspace(["~/Work/TeamA"], name="teama")
    assert split["stub"] is True
    assert "~/Work/TeamA" in split["excluded_from_default_work"]


def test_docs_lock_product_and_guards() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    desk = (root / "docs" / "DESK-KERNEL.md").read_text(encoding="utf-8")
    arch = (root / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    blob = desk + "\n" + arch
    assert "okbay (knowledge) + okstratr (orchestrator)" in blob
    assert "all-`~/Work`" in blob or "all-~/Work" in blob
    assert "demo" in desk.lower()
    assert "opt-in" in desk.lower()  # the "not an opt-in" correction
    assert "retire_worker" in desk
    assert "curator_worker" in desk
    assert "o{desk8}{role6}{node6}" in blob
    assert "pane split" in desk.lower()
    assert "reuses" in desk.lower() or "empty" in desk.lower()
    assert "focus_desk_id" in blob
    assert "left-pane" in desk.lower() or "left pane" in desk.lower()
    assert "query input" in desk.lower()
    assert "no free text" not in desk.lower() or "herdr" in desk.lower()
