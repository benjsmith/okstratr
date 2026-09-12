"""Desk lifecycle: start/stop keeps DAG; dismiss clears standing desk."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "okstratr-state"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(d))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    import okstratr.blackboard as bb
    import okstratr.dag as dag
    import okstratr.desks as desks
    import okstratr.status as status

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
    return d


def test_desk_start_hires_cos(state_dir: Path) -> None:
    from okstratr import desks, dag

    r = desks.start("Ship the desk brain", kind="work")
    assert r["ok"] is True
    desk = r["desk"]
    assert desk["state"] == "working"
    assert desk["roles"][0] == "cos"
    assert "cos" in desk["roles"]
    g = dag.default_dag(force_reload=True)
    assert "root" in g.nodes
    assert "cos-clarify" in g.nodes  # CoS breakdown ran


def test_desk_stop_keeps_dag(state_dir: Path) -> None:
    from okstratr import desks, dag

    desks.start("Keep my DAG", kind="code")
    g1 = dag.default_dag(force_reload=True)
    node_ids = set(g1.nodes)
    assert "cos-clarify" in node_ids

    stopped = desks.stop()
    assert stopped["ok"] is True
    assert stopped["dag_kept"] is True
    assert stopped["desk"]["state"] == "quiet"

    # Live DAG file still present for the desk
    reg = desks.default_registry(force_reload=True)
    desk = reg.desks[stopped["desk"]["id"]]
    assert desk.state == "quiet"
    live = reg.dag_path_for(desk)
    assert live.is_file()
    payload = json.loads(live.read_text())
    ids = {n["id"] for n in payload["nodes"]}
    assert "cos-clarify" in ids
    assert ids >= node_ids or "root" in ids


def test_desk_dismiss_clears_standing(state_dir: Path) -> None:
    from okstratr import desks, dag, status

    start = desks.start("Tear me down", kind="auto")
    desk_id = start["desk"]["id"]
    dismissed = desks.dismiss()
    assert dismissed["ok"] is True
    assert dismissed["desk"]["state"] == "dismissed"
    assert dismissed["desk"]["roles"] == []
    assert dismissed["archived_dag"] is not None

    reg = desks.default_registry(force_reload=True)
    assert reg.active_id is None
    standing = reg.standing()
    assert all(d.id != desk_id for d in standing)
    assert reg.desks[desk_id].state == "dismissed"

    g = dag.default_dag(force_reload=True)
    assert len(g.nodes) == 0
    assert status.get_objective() == ""


def test_desk_schedule_attach(state_dir: Path) -> None:
    from okstratr import desks

    desks.start("Scheduled work", kind="work")
    r = desks.schedule(["1h30m"])
    assert r["ok"] is True
    assert r["schedule"]["every_seconds"] == pytest.approx(5400)

    snap = desks.status_snapshot()
    assert snap["active"]["schedule"]["every_seconds"] == pytest.approx(5400)


def test_cli_desk_and_deprecated_seat(state_dir: Path, capsys: pytest.CaptureFixture) -> None:
    from okstratr.cli import main
    from okstratr import desks

    assert main(["desk", "start", "work", "Do", "the", "thing"]) == 0
    snap = desks.status_snapshot()
    assert snap["active"]["kind"] == "work"
    assert "Do the thing" in snap["active"]["objective"]

    assert main(["desk", "stop"]) == 0
    assert desks.status_snapshot()["active"]["state"] == "quiet"

    # Deprecated seat alias
    assert main(["seat", "Alias objective"]) == 0
    err = capsys.readouterr().err
    assert "deprecated" in err.lower()
    assert desks.status_snapshot()["active"]["kind"] == "auto"


def test_kernel_kind_heuristic() -> None:
    from okstratr.kernel import choose_kind, hire_plan

    assert choose_kind("curate the wiki pages") == "curate"
    assert choose_kind("fix the bug in the PR") == "code"
    assert choose_kind("build a pitch deck") == "deck"
    assert choose_kind("ship the release", kind="work") == "work"
    plan = hire_plan("anything", kind="curate")
    assert plan["roles"][0] == "cos"
    assert "curator_judge" in plan["roles"]
