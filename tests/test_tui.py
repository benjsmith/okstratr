"""Smoke tests for TUI helpers (no interactive Textual required)."""

from __future__ import annotations

from okstratr import tui


def test_render_snapshot_helpers() -> None:
    status = {
        "state": "working",
        "desks": [
            {"id": "d1", "kind": "auto", "state": "working", "objective": "ship"},
        ],
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
    assert tui.running_label({"state": "setup"}) == "Idle"


def test_desk_rows_and_topo() -> None:
    rows = tui.desk_rows({"desks": [{"id": "a", "kind": "work", "state": "quiet"}]})
    assert rows[0]["kind"] == "work"
    lines = tui.dag_topo_lines(
        {"nodes": {"root": {"id": "root", "depends_on": [], "state": "done"}}}
    )
    assert any("root" in ln for ln in lines)
