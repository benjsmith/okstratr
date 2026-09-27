"""open_workspace_agent resolves registered workspace dirs; refuses okbay repo."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "okstratr-state"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(d))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    return d


def test_looks_like_okbay_code_repo(tmp_path: Path) -> None:
    from okstratr.herdr import _looks_like_okbay_code_repo

    repo = tmp_path / "okbay"
    repo.mkdir()
    (repo / "Cargo.toml").write_text("[package]\nname='okbay'\n")
    (repo / "contrib").mkdir()
    (repo / "crates").mkdir()
    assert _looks_like_okbay_code_repo(repo) is True

    ws = tmp_path / "Workspaces" / "biocure-membership-7074bbec6"
    ws.mkdir(parents=True)
    (ws / "wiki").mkdir()
    assert _looks_like_okbay_code_repo(ws) is False


def test_resolve_workspace_agent_cwd_prefers_explicit_and_rejects_repo(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr import herdr

    repo = tmp_path / "okbay"
    repo.mkdir()
    (repo / "Cargo.toml").write_text("x\n")
    (repo / "contrib").mkdir()
    (repo / "Panel.qml").write_text("x\n")

    ws = tmp_path / "Workspaces" / "biocure-membership-7074bbec6"
    ws.mkdir(parents=True)
    (ws / "wiki").mkdir()

    # Explicit cwd wins
    out = herdr.resolve_workspace_agent_cwd(cwd=str(ws))
    assert out["ok"] is True
    assert Path(out["cwd"]) == ws.resolve()

    # Repo rejected even when given explicitly — falls through to tips (may fail)
    out2 = herdr.resolve_workspace_agent_cwd(cwd=str(repo))
    # If only candidate was repo, ok False; never returns repo path
    if out2.get("ok"):
        assert Path(out2["cwd"]) != repo.resolve()
        assert herdr._looks_like_okbay_code_repo(out2["cwd"]) is False
    else:
        assert out2.get("ok") is False


def test_resolve_uses_mocked_workspace_list(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr import herdr, okbay

    ws = tmp_path / "Workspaces" / "other-ws"
    ws.mkdir(parents=True)
    (ws / "vault").mkdir()

    def fake_list(**kwargs):
        return {
            "ok": True,
            "reachable": True,
            "workspaces": [
                {"id": "biocure", "name": "biocure", "path": str(ws)},
                {"id": "okbay", "name": "okbay", "path": str(tmp_path / "okbay")},
            ],
            "active": "biocure",
            "selected": "biocure",
        }

    monkeypatch.setattr(okbay, "list_workspaces", fake_list)
    out = herdr.resolve_workspace_agent_cwd(workspace_id="biocure")
    assert out["ok"] is True
    assert Path(out["cwd"]) == ws.resolve()
