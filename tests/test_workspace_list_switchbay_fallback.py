"""okbay.list_workspaces falls back to Switchbay registered vaults when okbay is down."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(tmp_path / "cfg"))
    return state


def test_list_workspaces_uses_switchbay_file_when_okbay_down(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr import okbay, workspace

    ws_a = tmp_path / "vault-alpha"
    ws_b = tmp_path / "vault-beta"
    ws_a.mkdir()
    ws_b.mkdir()
    cfg = tmp_path / "sy-workspaces.json"
    cfg.write_text(
        json.dumps({"paths": [str(ws_a), str(ws_b)], "active": str(ws_b)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OKSTRATR_SWITCHBAY_WORKSPACES", str(cfg))
    monkeypatch.setenv("OKSTRATR_SWITCHBAY_URL", "http://127.0.0.1:1")  # force HTTP miss
    monkeypatch.setenv("OKSTRATR_OKBAY_URL", "http://127.0.0.1:1")

    workspace.set_cwd(tmp_path)
    pack = okbay.list_workspaces(timeout=0.05)
    assert pack["reachable"] is False
    assert pack["local_fallback"] is True
    ids = [str(w.get("id")) for w in pack["workspaces"]]
    assert "vault-alpha" in ids
    assert "vault-beta" in ids
    assert "local" in ids
    labels = [str(w.get("label") or "") for w in pack["workspaces"]]
    assert any("local (serve cwd)" in lab for lab in labels)
    assert any("vault-alpha" in lab and str(ws_a) in lab for lab in labels)


def test_observer_html_agents_ux_affordances() -> None:
    html = (ROOT / "src" / "okstratr" / "observer" / "index.html").read_text(encoding="utf-8")
    assert 'id="agents-guidance"' in html
    assert "Files written" in html
    assert "Lines written" in html
    assert "local (serve cwd)" in html
    assert 'id="desk-prompt"' in html
    dash = html.split("Desk dashboard", 1)[1].split("Context", 1)[0]
    assert "Links" not in dash
