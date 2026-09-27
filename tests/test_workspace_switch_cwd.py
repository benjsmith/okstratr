"""Workspace switcher must set operating cwd + activate okbay."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "okstratr-state"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(d))
    return d


def test_apply_workspace_selection_sets_cwd(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr import okbay, workspace

    ws = tmp_path / "Workspaces" / "demo-ws"
    ws.mkdir(parents=True)

    def fake_list(**kwargs):
        return {
            "ok": True,
            "reachable": True,
            "workspaces": [
                {"id": "demo", "name": "demo", "path": str(ws)},
            ],
            "selected": "demo",
            "active": "demo",
        }

    activate_calls: list[str] = []

    def fake_activate(wid: str, **kwargs):
        activate_calls.append(wid)
        return {"ok": True, "name": wid, "workspace": str(ws)}

    monkeypatch.setattr(okbay, "list_workspaces", fake_list)
    monkeypatch.setattr(okbay, "activate_remote_workspace", fake_activate)

    out = okbay.apply_workspace_selection("demo")
    assert out["ok"] is True
    assert Path(out["operating_cwd"]) == ws.resolve()
    assert workspace.get_cwd() == str(ws.resolve())
    assert activate_calls == ["demo"]
    assert okbay.get_selected_workspace_id() == "demo"


def test_apply_workspace_selection_explicit_path(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr import okbay, workspace

    ws = tmp_path / "explicit"
    ws.mkdir()
    monkeypatch.setattr(
        okbay,
        "activate_remote_workspace",
        lambda *a, **k: {"ok": True, "skipped": True},
    )
    monkeypatch.setattr(
        okbay,
        "list_workspaces",
        lambda **k: {"workspaces": [], "reachable": False},
    )
    out = okbay.apply_workspace_selection("custom", path=str(ws))
    assert out["ok"] is True
    assert Path(out["operating_cwd"]) == ws.resolve()
    assert workspace.get_cwd() == str(ws.resolve())
