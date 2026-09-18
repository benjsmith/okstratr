"""Slash + API smoke for /bb clear / /clear (blackboard only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "okstratr-state"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(d))
    import okstratr.blackboard as bb
    import okstratr.status as status

    bb._DEFAULT = None
    bb._DEFAULT_PATH = None
    getattr(bb, "_DEFAULT_MTIME", None)
    bb._DEFAULT_MTIME = None  # type: ignore[attr-defined]
    status._loaded = False
    status._loaded_from = None
    status._seated_objective = ""
    status._state = "setup"
    return d


@pytest.mark.parametrize(
    "line",
    [
        "/bb clear",
        "/blackboard clear",
        "/clear",
        "/BB CLEAR",
        "/clear   ",
    ],
)
def test_parse_clear_blackboard(line: str) -> None:
    from okstratr.harness.slash import SLASH_HELP, parse_slash_directives

    d = parse_slash_directives(line)
    assert d.clear_blackboard is True
    assert d.objective == ""
    assert "clear" in SLASH_HELP.lower()
    assert "blackboard only" in SLASH_HELP.lower()


def test_parse_bb_clear_does_not_steal_other_slashes() -> None:
    from okstratr.harness.slash import parse_slash_directives

    d = parse_slash_directives("/work /bb clear")
    assert d.clear_blackboard is True
    assert d.kind == "work"
    assert d.objective == ""

    d2 = parse_slash_directives("/bb nope")
    assert d2.clear_blackboard is False
    assert "/bb" in d2.objective or d2.objective.startswith("/bb")


def test_slash_help_documents_bare_clear_is_bb_only() -> None:
    from okstratr.harness.slash import SLASH_HELP

    assert "/clear" in SLASH_HELP
    assert "blackboard only" in SLASH_HELP


def test_apply_slash_side_effects_local_fallback(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import blackboard
    from okstratr.harness.slash import parse_slash_directives
    from okstratr.harness.slash_actions import apply_slash_side_effects

    blackboard.post("VISIBLE_SECRET_NOTE", kind="note")
    assert blackboard.summary()["count"] == 1

    # Force API miss → local clear
    monkeypatch.setenv("OKSTRATR_API", "http://127.0.0.1:1")
    d = parse_slash_directives("/bb clear")
    toast = apply_slash_side_effects(d)
    assert toast == "blackboard cleared"
    assert blackboard.head(10) == []
    assert blackboard.summary()["count"] == 0
