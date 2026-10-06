"""Context is read-only: desk from rail card, workspace from host resolution."""

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
    # Isolate from ambient Switchbay-hosted box env.
    for key in (
        "OKSTRATR_HOSTED",
        "OKSTRATR_HOST",
        "OKSTRATR_WORKSPACE",
        "OKSTRATR_OKBAY_WORKSPACE",
        "OKSTRATR_PUBLIC_BASE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OKSTRATR_SWITCHBAY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("OKSTRATR_OKBAY_URL", "http://127.0.0.1:1")
    return state


def test_observer_html_has_no_context_inputs() -> None:
    html = (ROOT / "src" / "okstratr" / "observer" / "index.html").read_text(encoding="utf-8")
    assert 'id="context-label"' in html
    assert 'id="context-switcher"' in html
    assert 'id="desk-switcher"' not in html
    assert 'id="workspace-switcher"' not in html
    assert "<select" not in html.split('id="context-switcher"', 1)[1].split("</section>", 1)[0]


def test_observer_js_desk_via_card_not_switcher() -> None:
    js = (ROOT / "src" / "okstratr" / "observer" / "observer.js").read_text(encoding="utf-8")
    assert "function renderContextLabel" in js
    assert "function applyHostWorkspace" in js
    assert "function contextLine" in js
    assert "desk-switcher" not in js
    assert "workspace-switcher" not in js
    assert "renderDeskSwitcher" not in js
    # Desk selection still goes through focusDesk (rail card click).
    assert "function focusDesk" in js
    assert "data-id" in js or "focusDesk(" in js


def test_resolve_host_workspace_env(state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import okbay, workspace

    ws = tmp_path / "my-vault"
    ws.mkdir()
    monkeypatch.setenv("OKSTRATR_WORKSPACE", str(ws))
    workspace.set_cwd(tmp_path)
    row = okbay.resolve_host_workspace(timeout=0.05)
    assert row["ok"] is True
    assert row["resolution"] == "OKSTRATR_WORKSPACE"
    assert row["id"] == "my-vault"
    assert row["display"] == "my-vault"
    assert Path(row["path"]).name == "my-vault" or "my-vault" in str(row.get("path"))


def test_resolve_host_workspace_cwd_nearest(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr import okbay, workspace

    root = tmp_path / "vault-near"
    nested = root / "src"
    root.mkdir()
    nested.mkdir()
    cfg = tmp_path / "sy-workspaces.json"
    cfg.write_text(
        json.dumps({"paths": [str(root)], "active": str(root)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OKSTRATR_SWITCHBAY_WORKSPACES", str(cfg))
    workspace.set_cwd(nested)
    row = okbay.resolve_host_workspace(timeout=0.05)
    assert row["resolution"] == "cwd-nearest"
    assert row["id"] == "vault-near"
    assert row["display"] == "vault-near"


def test_resolve_host_workspace_switchbay_active(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr import okbay

    a = tmp_path / "alpha-ws"
    b = tmp_path / "beta-ws"
    a.mkdir()
    b.mkdir()
    cfg = tmp_path / "sy-workspaces.json"
    cfg.write_text(
        json.dumps({"paths": [str(a), str(b)], "active": str(b)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OKSTRATR_SWITCHBAY_WORKSPACES", str(cfg))
    monkeypatch.setenv("OKSTRATR_HOSTED", "switchbay")
    monkeypatch.setenv("OKSTRATR_HOST", "switchbay")
    # Stale spawn seed must lose to live active.
    monkeypatch.setenv("OKSTRATR_WORKSPACE", str(a))
    row = okbay.resolve_host_workspace(timeout=0.05)
    assert row["host"] == "switchbay"
    assert row["resolution"] == "switchbay-active"
    assert row["id"] == "beta-ws"
    assert row["display"] == "beta-ws"


def test_resolve_host_workspace_default_work(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr import okbay, workspace

    monkeypatch.setenv("OKSTRATR_SWITCHBAY_WORKSPACES", str(state_dir / "missing.json"))
    # Neutral cwd that is not under any registered workspace.
    empty = tmp_path / "empty-cwd"
    empty.mkdir()
    workspace.set_cwd(empty)
    row = okbay.resolve_host_workspace(timeout=0.05)
    assert row["resolution"] == "default-work"
    assert row["id"] == "work"
    assert row["display"] == "work"


def test_status_snapshot_includes_context_workspace(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr import okbay, status

    ws = tmp_path / "status-ws"
    ws.mkdir()
    monkeypatch.setenv("OKSTRATR_WORKSPACE", str(ws))
    snap = status.snapshot()
    cw = snap.get("context_workspace") or {}
    assert cw.get("id") == "status-ws"
    assert cw.get("display") == "status-ws"


def test_lifecycle_status_shows_workspace(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr import lifecycle

    ws = tmp_path / "cli-ws"
    ws.mkdir()
    monkeypatch.setenv("OKSTRATR_WORKSPACE", str(ws))
    payload = lifecycle.status_payload()
    assert payload.get("workspace") == "cli-ws"
    box = lifecycle.format_status_box(payload)
    assert "cli-ws" in box


def test_panel_qml_context_read_only() -> None:
    qml = (ROOT / "Panel.qml").read_text(encoding="utf-8")
    assert "contextLabel" in qml
    assert 'text: "Context"' in qml
    assert "workspacePicker" not in qml
    assert "chooseWorkspace(modelData)" not in qml
