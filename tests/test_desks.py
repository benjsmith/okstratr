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
    assert "investigator" in g.nodes  # Switchbay work template


def test_desk_stop_keeps_dag(state_dir: Path) -> None:
    from okstratr import desks, dag

    desks.start("Keep my DAG", kind="code")
    g1 = dag.default_dag(force_reload=True)
    node_ids = set(g1.nodes)
    assert "code-investigate" in node_ids

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
    assert "code-investigate" in ids
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


def test_kernel_kind_heuristic(state_dir: Path) -> None:
    from okstratr.kernel import choose_kind, hire_plan

    # Improvement #1 (classify objective → suggest kind) is intentionally deferred.
    assert choose_kind("curate the wiki pages") == "auto"
    assert choose_kind("fix the bug in the PR") == "auto"
    assert choose_kind("build a pitch deck") == "auto"
    assert choose_kind("ship the release", kind="work") == "work"
    plan = hire_plan("anything", kind="curate")
    assert plan["roles"][0] == "cos"
    assert "curator_judge" in plan["roles"]
    assert "curator_worker" not in plan["roles"]  # no commit path


def test_default_desks_present_in_status(state_dir: Path) -> None:
    from okstratr import desks, status

    desk_status = desks.status_snapshot()
    assert [row["kind"] for row in desk_status["standing"]] == [
        "work", "curate", "code", "deck", "auto"
    ]
    assert all(row["state"] == "idle" for row in desk_status["standing"])
    assert all(row["placeholder"] is True for row in desk_status["standing"])

    full_status = status.snapshot()
    assert [row["kind"] for row in full_status["desk"]["standing"]] == [
        "work", "curate", "code", "deck", "auto"
    ]
    assert full_status["ui"]["text_input"] is True


def test_start_from_query(state_dir: Path) -> None:
    from okstratr import desks

    query = "Prepare the partner launch brief"
    result = desks.start(query, kind="work")
    assert result["ok"] is True
    assert result["desk"]["objective"] == query
    assert result["desk"]["kind"] == "work"
    assert result["desk"]["state"] == "working"

    rows = desks.status_snapshot()["standing"]
    work = next(row for row in rows if row["kind"] == "work")
    assert work["objective"] == query
    assert work["state"] == "working"
    assert work["placeholder"] is False


def test_workspace_bind_field(state_dir: Path) -> None:
    from okstratr import desks, okbay, status

    result = desks.start(
        "Start Biocure work",
        kind="work",
        okbay_workspace_id="biocure",
    )
    assert result["desk"]["okbay_workspace_id"] == "biocure"
    assert okbay.get_selected_workspace_id() == "biocure"
    assert status.snapshot()["desk"]["okbay_workspace_id"] == "biocure"


def test_roles_config_load_save(state_dir: Path) -> None:
    from okstratr import roles

    initial = roles.load_role_config()
    assert [r["id"] for r in initial["roles"]] == [
        "cos", "investigator", "synthesizer", "verifier", "curator", "researcher"
    ]
    saved = roles.save_role_config({
        "roles": [
            {"id": "investigator", "enabled": False, "hire_cap": 2,
             "model_hint": "fast", "notes": "triage only"},
            {"id": "cos", "enabled": False, "model_hint": "best"},
        ]
    })
    investigator = next(r for r in saved["roles"] if r["id"] == "investigator")
    assert investigator["enabled"] is False
    assert investigator["hire_cap"] == 2
    assert investigator["model_hint"] == "fast"
    cos = next(r for r in saved["roles"] if r["id"] == "cos")
    assert cos["enabled"] is True  # always

    loaded = roles.load_role_config()
    assert loaded == saved
    assert (state_dir / "config" / "roles.json").is_file()
