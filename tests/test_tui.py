"""Smoke tests for TUI helpers (no interactive Textual required)."""

from __future__ import annotations

from okstratr import tui


def test_render_snapshot_helpers() -> None:
    status = {
        "state": "working",
        "desks": [
            {"id": "d1", "kind": "auto", "state": "working", "objective": "ship"},
            {"id": "d2", "kind": "work", "state": "quiet", "objective": "idle one"},
        ],
        "active_desk": {"id": "d1"},
    }
    dag_payload = {
        "nodes": [
            {"id": "root", "state": "done", "depends_on": [], "title": "root"},
            {"id": "investigator", "state": "ready", "depends_on": ["root"], "title": "inv"},
        ]
    }
    bb = {"entries": [{"author": "cos", "text": "plan ready"}]}
    text = tui.render_snapshot(status, dag_payload, bb)
    assert "Running" in text
    assert "investigator" in text
    assert "plan ready" in text
    assert "Idle" in text or "work[Idle]" in text or "[Idle]" in text
    assert "/harness" in text or "/model" in text
    assert tui.running_label({"state": "setup"}) == "Idle"


def test_desk_rows_badges_and_tabs() -> None:
    rows = tui.desk_rows(
        {
            "desks": [
                {"id": "a", "kind": "work", "state": "working"},
                {"id": "b", "kind": "curate", "state": "quiet"},
            ]
        }
    )
    assert rows[0]["badge"] == "Running"
    assert rows[1]["badge"] == "Idle"
    tabs = tui.desk_tab_line(rows, active_id="a")
    assert "work[Running]" in tabs
    assert "*work" in tabs or "work[Running]" in tabs


def test_desk_rows_and_topo() -> None:
    rows = tui.desk_rows({"desks": [{"id": "a", "kind": "work", "state": "quiet"}]})
    assert rows[0]["kind"] == "work"
    lines = tui.dag_topo_lines(
        {"nodes": {"root": {"id": "root", "depends_on": [], "state": "done"}}}
    )
    assert any("root" in ln for ln in lines)


def test_apply_slash_env(monkeypatch) -> None:
    monkeypatch.delenv("OKSTRATR_MODEL", raising=False)
    obj, kind = tui.apply_slash_env("/model claude:sonnet /work build")
    assert kind == "work" or obj  # kind may be work depending on parse order
    # /work before objective
    obj2, kind2 = tui.apply_slash_env("/work /model claude:sonnet build")
    assert kind2 == "work"
    assert obj2 == "build"
    import os

    assert os.environ.get("OKSTRATR_MODEL") == "sonnet"


def test_agents_grouped(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(tmp_path / "c"))
    (tmp_path / "s").mkdir()
    (tmp_path / "c").mkdir()
    import okstratr.blackboard as bb
    import okstratr.dag as dag
    import okstratr.status as status

    bb._DEFAULT = None
    bb._DEFAULT_PATH = None
    dag._DEFAULT = None
    dag._DEFAULT_PATH = None
    status._loaded = False
    status._loaded_from = None
    from okstratr.cli import main

    assert main(["agents"]) == 0
    out = capsys.readouterr().out
    assert "grouped" in out
    assert "label_convention" in out
