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
    assert desk["state"] == "quiet"  # CoS-only start lands quiet (not active herdr run)
    assert r.get("landed_quiet") is True
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

    # Free-text classification is not shipped; slash overrides are.
    assert choose_kind("curate the wiki pages") == "auto"
    assert choose_kind("fix the bug in the PR") == "auto"
    assert choose_kind("build a pitch deck") == "auto"
    assert choose_kind("ship the release", kind="work") == "work"
    assert choose_kind("/curate tidy it", kind="work") == "curate"
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
    # Empty never-started rows: placeholder, no Idle/"idle" state label
    assert all(row["placeholder"] is True for row in desk_status["standing"])
    assert all(not row.get("state") for row in desk_status["standing"])
    assert all(row["state"] != "idle" for row in desk_status["standing"])

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
    assert result["desk"]["state"] == "quiet"

    rows = desks.status_snapshot()["standing"]
    work = next(row for row in rows if row["kind"] == "work")
    assert work["objective"] == query
    assert work["state"] == "quiet"
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

def test_slash_override_and_auto_default(tmp_path, monkeypatch):
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path))
    from okstratr.kernel import choose_kind, parse_objective_slash
    from okstratr import desks

    assert parse_objective_slash("/curate tidy biocure") == ("curate", "tidy biocure")
    assert parse_objective_slash("just do it") == (None, "just do it")
    assert choose_kind("no slash here") == "auto"
    assert choose_kind("/deck make slides", kind="work") == "deck"
    assert choose_kind("x", kind="code") == "code"

    result = desks.start("/deck Make a Q3 briefing", kind="work")
    assert result["desk"]["kind"] == "deck"
    assert result["desk"]["objective"] == "Make a Q3 briefing"

    result2 = desks.start("Neutral objective only")  # no kind → auto
    assert result2["desk"]["kind"] == "auto"
    assert result2["desk"]["objective"] == "Neutral objective only"


def test_start_cos_only_lands_quiet(state_dir: Path) -> None:
    from okstratr import desks, dag

    r = desks.start("Make slides", kind="deck")
    assert r["ok"] is True
    assert r["desk"]["state"] == "quiet"
    assert r.get("landed_quiet") is True
    g = dag.default_dag(force_reload=True)
    # Plan exists with ready/pending work — still quiet until herdr drives seats
    assert any(n.state in ("ready", "pending") for n in g.nodes.values())


def test_start_drive_herdr_stays_working_until_finished(state_dir: Path) -> None:
    from okstratr import desks, dag, herdr

    r = desks.start("Drive seats", kind="work", drive_herdr=True)
    assert r["desk"]["state"] == "working"
    assert r.get("landed_quiet") is False
    assert r.get("drive_herdr") is True

    # While ready nodes remain, maybe_quiet must not quiet
    noop = desks.maybe_quiet_if_finished()
    assert noop["action"] == "noop"
    assert desks.default_registry(force_reload=True).active().state == "working"

    # Finish all non-root seats via dry-run herdr; last run_one (or run_ready)
    # auto-quiets when the DAG is fully terminal.
    out = herdr.run_ready(limit=20, dry_run=True)
    reg = desks.default_registry(force_reload=True)
    desk = reg.desks[r["desk"]["id"]]
    assert desk.state == "quiet"
    # Last seat's run_one may quiet before run_ready's end-hook (noop desk_quiet).
    q = out.get("desk_quieted") or {}
    assert q.get("action") in ("auto_quiet", "noop")
    g = dag.default_dag(force_reload=True)
    assert desks.dag_is_fully_terminal(g)


def test_maybe_quiet_when_all_nodes_terminal(state_dir: Path) -> None:
    from okstratr import desks, dag

    r = desks.start("Finish me", kind="auto", drive_herdr=True)
    desk_id = r["desk"]["id"]
    assert r["desk"]["state"] == "working"

    g = dag.default_dag(force_reload=True)
    for nid in list(g.nodes):
        g.mark_done(nid, notes="forced terminal", save=False)
    g.save()

    quieted = desks.maybe_quiet_if_finished(desk_id)
    assert quieted["action"] == "auto_quiet"
    assert quieted["desk"]["state"] == "quiet"
    assert quieted.get("dag_kept") is True

    # Idempotent: already quiet → noop
    again = desks.maybe_quiet_if_finished(desk_id)
    assert again["action"] == "noop"


def test_maybe_quiet_noop_while_ready_or_running(state_dir: Path) -> None:
    from okstratr import desks, dag

    r = desks.start("Still work left", kind="work", drive_herdr=True)
    desk_id = r["desk"]["id"]
    g = dag.default_dag(force_reload=True)
    # Ensure at least one ready/pending child remains (CoS leaves ready investigator)
    assert any(n.state in ("ready", "pending", "running") for n in g.nodes.values() if n.id != "root")

    noop = desks.maybe_quiet_if_finished(desk_id)
    assert noop["action"] == "noop"
    assert noop["reason"] == "dag_not_terminal"
    assert desks.default_registry(force_reload=True).desks[desk_id].state == "working"


def test_dag_is_fully_terminal_helper(state_dir: Path) -> None:
    from okstratr import desks, dag

    g = dag.default_dag(force_reload=True)
    assert desks.dag_is_fully_terminal(g) is True  # empty

    g.seat_root("x", reset=True, save=True)
    assert desks.dag_is_fully_terminal(g) is False  # root pending/ready

    g.mark_done("root", notes="done", save=True)
    assert desks.dag_is_fully_terminal(g) is True

    g.add("child", "Child", depends_on=["root"], state="ready", save=True)
    assert desks.dag_is_fully_terminal(g) is False
    g.mark_failed("child", notes="nope", save=True)
    assert desks.dag_is_fully_terminal(g) is True


def test_standing_prefers_dismissed_over_empty(state_dir: Path) -> None:
    """After dismiss, standing row keeps dismissed desk (not empty Idle placeholder)."""
    from okstratr import desks

    start = desks.start("Keep me visible", kind="work")
    desk_id = start["desk"]["id"]
    desks.dismiss(desk_id)

    rows = desks.status_snapshot()["standing"]
    work = next(row for row in rows if row["kind"] == "work")
    assert work["id"] == desk_id
    assert work["state"] == "dismissed"
    assert work["placeholder"] is False
    assert work["objective"] == "Keep me visible"

    # Other kinds still empty (no Idle state)
    curate = next(row for row in rows if row["kind"] == "curate")
    assert curate["placeholder"] is True
    assert not curate.get("state")


def test_standing_prefers_quiet_over_dismissed(state_dir: Path) -> None:
    from okstratr import desks

    first = desks.start("Old work", kind="code")
    desks.dismiss(first["desk"]["id"])
    second = desks.start("Live quiet", kind="code")
    assert second["desk"]["state"] == "quiet"

    rows = desks.status_snapshot()["standing"]
    code = next(row for row in rows if row["kind"] == "code")
    assert code["id"] == second["desk"]["id"]
    assert code["state"] == "quiet"
    assert code["placeholder"] is False


def test_desk_delete_purge(state_dir: Path) -> None:
    from okstratr import desks
    from okstratr.paths import state_dir as sd

    start = desks.start("Purge me", kind="deck")
    desk_id = start["desk"]["id"]
    desk_dir = sd() / "desks" / desk_id
    assert desk_dir.is_dir()

    # Cannot delete while quiet/working
    blocked = desks.delete(desk_id)
    assert blocked["ok"] is False
    assert "dismiss" in blocked["error"].lower() or "force" in blocked["error"].lower()

    desks.dismiss(desk_id)
    # Still visible as dismissed
    deck = next(r for r in desks.status_snapshot()["standing"] if r["kind"] == "deck")
    assert deck["state"] == "dismissed"

    purged = desks.delete(desk_id)
    assert purged["ok"] is True
    assert purged["action"] == "delete"
    assert purged["desk_id"] == desk_id
    assert purged.get("cleaned_dir") is True

    reg = desks.default_registry(force_reload=True)
    assert desk_id not in reg.desks
    assert not desk_dir.exists()

    # Kind row is empty startable again (no Idle label)
    deck2 = next(r for r in desks.status_snapshot()["standing"] if r["kind"] == "deck")
    assert deck2["placeholder"] is True
    assert not deck2.get("state")


def test_desk_delete_force_and_cli(state_dir: Path, capsys: pytest.CaptureFixture) -> None:
    from okstratr.cli import main
    from okstratr import desks

    start = desks.start("Force purge", kind="auto")
    desk_id = start["desk"]["id"]
    # force allows purge without dismiss
    assert main(["desk", "delete", desk_id, "--force"]) == 0
    out = capsys.readouterr().out
    assert desk_id in out
    reg = desks.default_registry(force_reload=True)
    assert desk_id not in reg.desks


def test_http_start_drive_herdr_runs_ready(state_dir: Path) -> None:
    """POST /api/desk/start with drive_herdr=True runs herdr.run_ready (dry-run)."""
    from okstratr.server import Handler
    from http.server import ThreadingHTTPServer
    import threading
    import urllib.request

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        req = urllib.request.Request(
            base + "/api/desk/start",
            data=json.dumps(
                {
                    "objective": "Drive from HTTP start",
                    "kind": "auto",
                    "drive_herdr": True,
                    "herdr_limit": 6,
                    "dry_run": True,
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read().decode())
        assert "herdr_run" in body
        hr = body["herdr_run"]
        assert hr.get("dry_run") is True
        assert hr.get("ran"), "expected at least one ready seat to run"
        desk = body.get("desk") or {}
        # Start result shape preserved (desk.desk.id)
        assert (desk.get("desk") or {}).get("id")
        assert desk.get("drive_herdr") is True
        # After bounded dry-run of the full Switchbay chain, DAG is often terminal → Idle
        state = (desk.get("desk") or {}).get("state")
        assert state in ("quiet", "working")
    finally:
        httpd.shutdown()


def test_http_start_without_drive_herdr_lands_quiet(state_dir: Path) -> None:
    """API default (no drive_herdr) still lands quiet after CoS — plan-only."""
    from okstratr.server import Handler
    from http.server import ThreadingHTTPServer
    import threading
    import urllib.request
    from okstratr import desks, dag

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        req = urllib.request.Request(
            base + "/api/desk/start",
            data=json.dumps(
                {"objective": "Plan only please", "kind": "work"}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read().decode())
        assert "herdr_run" not in body
        desk = body.get("desk") or {}
        assert desk.get("drive_herdr") is False
        assert desk.get("landed_quiet") is True
        assert (desk.get("desk") or {}).get("state") == "quiet"
        g = dag.default_dag(force_reload=True)
        assert any(n.state in ("ready", "pending") for n in g.nodes.values())
        reg = desks.default_registry(force_reload=True)
        assert reg.active().state == "quiet"
    finally:
        httpd.shutdown()


def test_start_empty_objective_keeps_quiet_desk_objective(state_dir: Path) -> None:
    """Stop then Start with empty objective must not wipe the standing desk objective."""
    from okstratr import desks, status

    first = desks.start("Keep this objective", kind="work")
    desk_id = first["desk"]["id"]
    assert first["desk"]["objective"] == "Keep this objective"
    desks.stop(desk_id)
    reg = desks.default_registry(force_reload=True)
    assert reg.desks[desk_id].state == "quiet"
    assert reg.desks[desk_id].objective == "Keep this objective"

    # Empty query resume of quiet work desk
    resumed = desks.start("", kind="work", drive_herdr=False)
    assert resumed["action"] == "resume"
    assert resumed["desk"]["id"] == desk_id
    assert resumed["desk"]["objective"] == "Keep this objective"
    # Global status objective must not be blanked
    assert status.get_objective() == "Keep this objective"


def test_http_start_all_seats_failed_quiets_and_surfaces_error(state_dir: Path, monkeypatch) -> None:
    """When every Herdr seat fails, desk must Idle and response includes herdr_error."""
    from okstratr.server import Handler
    from http.server import ThreadingHTTPServer
    import json
    import threading
    import urllib.request
    from okstratr import herdr, desks

    def boom(**kwargs):
        return {
            "ok": False,
            "dry_run": True,
            "results": [
                {"ok": False, "error": "missing required --pane", "node_id": "investigator", "state": "failed"}
            ],
            "ran": ["investigator"],
        }

    monkeypatch.setattr(herdr, "run_ready", boom)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/desk/start",
            data=json.dumps({
                "objective": "Drug report",
                "kind": "work",
                "drive_herdr": True,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read().decode())
        assert body.get("herdr_error")
        assert "missing required --pane" in body["herdr_error"]
        assert "Idle" in (body.get("message") or "") or "quiet" in (body.get("message") or "").lower()
        desk = (body.get("desk") or {}).get("desk") or body.get("desk") or {}
        # After stop, state should be quiet
        reg = desks.default_registry(force_reload=True)
        active = reg.active()
        assert active is not None
        assert active.state == "quiet"
    finally:
        httpd.shutdown()



def test_focus_quiet_desk_syncs_objective_and_dag(state_dir: Path) -> None:
    """Focusing a quiet desk must set status objective + sync global DAG root."""
    from okstratr import desks, herdr, status, dag

    a = desks.start("Quiet Alpha", kind="work")
    desks.stop()
    b = desks.start("Working Beta", kind="code")
    assert status.get_objective() == "Working Beta"

    focused = herdr.focus_desk(a["desk"]["id"])
    assert focused["ok"] is True
    assert focused.get("objective") == "Quiet Alpha"
    assert status.get_objective() == "Quiet Alpha"
    snap = status.write_status()
    assert snap["focus_desk_id"] == a["desk"]["id"]
    assert snap["objective"] == "Quiet Alpha"
    g = dag.default_dag(force_reload=True)
    root = g.nodes.get("root")
    title = getattr(root, "title", None) or getattr(root, "objective", None)
    assert title == "Quiet Alpha"
    _ = b


def test_dedupe_kind_collapses_quiet_twins(state_dir: Path) -> None:
    """Two quiet autos → dedupe/start leaves a single live desk of that kind."""
    from okstratr import desks

    # Bypass start() dedupe by injecting a second quiet twin into the registry.
    desks.start("Auto one", kind="auto", reset=True)
    desks.stop()
    reg = desks.default_registry(force_reload=True)
    first = next(d for d in reg.desks.values() if d.kind == "auto" and d.state == "quiet")
    twin = desks.Desk(
        id="desk-twin-auto",
        kind="auto",
        objective="Auto twin",
        state="quiet",
        roles=list(first.roles),
        created_at=first.created_at - 10,
        updated_at=first.updated_at - 10,
        thread_id="thread-desk-twin-auto",
        dag_relpath=f"desks/desk-twin-auto/dag.json",
    )
    reg.desks[twin.id] = twin
    reg.save()

    live_before = [d for d in reg.standing() if d.kind == "auto"]
    assert len(live_before) == 2

    out = desks.dedupe_kind("auto")
    assert out["ok"] is True
    assert len(out["dismissed"]) == 1
    reg = desks.default_registry(force_reload=True)
    live_after = [d for d in reg.standing() if d.kind == "auto"]
    assert len(live_after) == 1
    assert live_after[0].id == first.id  # newest/preferred kept

    # start without reset resumes that one live desk (no second twin)
    r = desks.start("Auto three", kind="auto")
    assert r["action"] == "resume"
    assert r["desk"]["id"] == first.id
    reg = desks.default_registry(force_reload=True)
    assert len([d for d in reg.standing() if d.kind == "auto"]) == 1


def test_start_resumes_preferred_live_not_twin(state_dir: Path) -> None:
    from okstratr import desks

    r1 = desks.start("First work", kind="work")
    desks.stop()
    r2 = desks.start("Second work", kind="work")  # should resume, not twin
    assert r2["action"] == "resume"
    assert r2["desk"]["id"] == r1["desk"]["id"]
    assert r2["desk"]["objective"] == "Second work"
    reg = desks.default_registry(force_reload=True)
    assert len([d for d in reg.standing() if d.kind == "work"]) == 1
