"""Phase 4: DeskSession SSOT — status_channel + status.json compat mirror."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def iso_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    import okstratr.blackboard as bb
    import okstratr.dag as dag
    import okstratr.status as status

    for mod in (bb, dag):
        if hasattr(mod, "_DEFAULT"):
            mod._DEFAULT = None
        if hasattr(mod, "_DEFAULT_PATH"):
            mod._DEFAULT_PATH = None
    if hasattr(status, "_loaded"):
        status._loaded = False
    if hasattr(status, "_loaded_from"):
        status._loaded_from = None
    if hasattr(status, "_seated_objective"):
        status._seated_objective = ""
    return state


def test_status_channel_primary_http_no_dual_source(iso_env: Path) -> None:
    from okstratr import desks, status

    desks.start("p4 channel", kind="work", drive_herdr=False)
    snap = status.snapshot()
    ch = snap.get("status_channel") or {}
    assert ch.get("primary") == "GET /api/status"
    assert ch.get("dual_source") is False
    assert ch.get("mirror") is True
    assert "compat_file" in ch
    notes = str(ch.get("notes") or "")
    assert "P4" in notes


def test_status_json_mirror_matches_desk_session(iso_env: Path) -> None:
    from okstratr import desks, status

    desks.start("p4 mirror match", kind="work", drive_herdr=False)
    snap = status.write_status()
    path = status.status_path()
    assert path.is_file()
    mirror = json.loads(path.read_text(encoding="utf-8"))
    assert "desk_session" in snap and "desk_session" in mirror
    assert snap["desk_session"]["schema"] == mirror["desk_session"]["schema"]
    assert snap["desk_session"].get("desks") == mirror["desk_session"].get("desks")
    assert snap.get("desks") == mirror.get("desks")
    assert snap.get("status_channel", {}).get("dual_source") is False


def test_desk_session_notes_p4(iso_env: Path) -> None:
    from okstratr.desk_session import build

    notes = build().notes
    assert "P4" in notes
