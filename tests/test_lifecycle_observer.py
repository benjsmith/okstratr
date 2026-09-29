"""Lifecycle status shape + /okstratr slash parse (no real Herdr)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "okstratr-state"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(d))
    return d


def test_status_payload_shape(state_dir: Path) -> None:
    from okstratr import lifecycle

    p = lifecycle.status_payload()
    assert "services" in p
    assert "serve" in p["services"]
    assert "observer" in p["services"]
    assert p["services"]["serve"]["port"] == 8767
    assert "url" in p["services"]["observer"]
    assert "/observer/" in p["services"]["observer"]["url"] or "8768" in p["services"]["observer"]["url"]
    assert "board_duration_chip" in p
    assert "web_egress" in p
    assert "cwd" in p
    assert "backend" in p
    assert "harnesses" in p
    assert "desks" in p
    assert "by_kind" in p["desks"]
    assert "by_state" in p["desks"]
    assert "time" in p
    assert "tokens" in p
    assert p["tokens"]["tokens"] == 0
    assert p["tokens"]["n_a"] is True
    assert "files" in p
    assert "files" in p["files"]
    assert "lines" in p["files"]
    assert "consent_prompt" in p
    assert "observer panel" in p["consent_prompt"]


def test_format_status_box_contains_services(state_dir: Path) -> None:
    from okstratr import lifecycle

    box = lifecycle.format_status_box()
    assert "okstratr status" in box
    assert "serve" in box
    assert "observer" in box
    assert "tok" in box


def test_ensure_running_need_consent_when_down(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import lifecycle

    monkeypatch.setattr(lifecycle, "is_serve_running", lambda: False)
    out = lifecycle.ensure_running(prompt=True, yes=False)
    assert out["running"] is False
    assert out["need_consent"] is True
    assert "Start it on :8767" in out["message"]


def test_doctor_includes_assets(state_dir: Path) -> None:
    from okstratr import lifecycle

    d = lifecycle.doctor()
    assert d["observer_index_exists"] is True
    assert "observer" in d["observer_assets"]


@pytest.mark.parametrize(
    "line,cmd",
    [
        ("/okstratr start", "start"),
        ("/okstratr restart", "restart"),
        ("/okstratr shutdown", "shutdown"),
        ("/okstratr status", "status"),
        ("/okstratr stop", "shutdown"),
        ("/OKSTRATR STATUS", "status"),
        ("/oks start", "start"),
    ],
)
def test_parse_okstratr_slash(line: str, cmd: str) -> None:
    from okstratr.harness.slash import SLASH_HELP, parse_slash_directives

    d = parse_slash_directives(line)
    assert d.okstratr_cmd == cmd
    assert d.objective == ""
    assert "/okstratr" in SLASH_HELP


def test_parse_okstratr_does_not_steal_objective() -> None:
    from okstratr.harness.slash import parse_slash_directives

    d = parse_slash_directives("/okstratr nope do stuff")
    assert d.okstratr_cmd is None
    assert "nope" in d.objective or d.objective.startswith("/okstratr")


def test_observer_assets_exist() -> None:
    from okstratr.lifecycle import observer_asset_dir

    root = observer_asset_dir()
    assert (root / "index.html").is_file()
    assert (root / "observer.js").is_file()
    assert (root / "observer.css").is_file()
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "observer panel" in html.lower()
    assert "butter" not in html.lower()


def test_observer_js_has_desk_action_hooks() -> None:
    """Light contract: observer JS wires Panel/DeskRail desk POSTs."""
    from okstratr.lifecycle import observer_asset_dir

    root = observer_asset_dir()
    js = (root / "observer.js").read_text(encoding="utf-8")
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "Standing desks" in html or "standing desks" in html.lower()
    assert 'id="desk-rail"' in html or "desk-rail" in html
    assert 'id="dag-graph"' in html
    for path in (
        "/api/desk/focus",
        "/api/desk/start",
        "/api/desk/stop",
        "/api/desk/dismiss",
        "/api/desk/delete",
        "/api/blackboard/clear",
    ):
        assert path in js, path
    assert "drive_herdr" in js
    assert "butter" not in js.lower()


def test_observer_has_agent_space_no_query_input() -> None:
    """Observer is desks + AGENT SPACE canvas; no chat/objective text input."""
    from okstratr.lifecycle import observer_asset_dir

    root = observer_asset_dir()
    html = (root / "index.html").read_text(encoding="utf-8")
    js = (root / "observer.js").read_text(encoding="utf-8")
    css = (root / "observer.css").read_text(encoding="utf-8")

    # No query / start-from-query form
    assert "query-input" not in html
    assert "btn-start" not in html
    # Modal edit textarea allowed; no persistent objective/query bar
    assert 'id="objective"' not in html
    assert 'id="edit-objective"' in html or "<textarea" in html.lower()
    assert "query-input" not in js
    assert "parseDeskQuery" not in js

    # AGENT SPACE canvas + token-flow markers
    assert "AGENT SPACE" in html or "agent-space" in html
    assert "agent-space-canvas" in html
    assert "agent-space" in js.lower() or "AGENT SPACE" in js
    assert "token-flow" in js
    assert "requestAnimationFrame" in js
    assert "synthesizeDagGraph" in js or "dagGraph" in js
    assert "agent-space-canvas" in css or ".agent-space" in css
