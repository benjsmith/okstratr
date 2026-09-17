"""P4 Panel/Model helper contract (static checks — QML not executed)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_model_js_status_channel_helpers() -> None:
    text = (ROOT / "Model.js").read_text(encoding="utf-8")
    for name in (
        "statusChannel",
        "statusPrimaryIsHttp",
        "pollStatusHttp",
        "resolveApiUrl",
        "standingDesks",
        "harnessRows",
    ):
        assert f"function {name}" in text, name


def test_panel_http_live_guards() -> None:
    text = (ROOT / "Panel.qml").read_text(encoding="utf-8")
    assert "httpLive" in text
    assert "ConfigHarnessEditor" in text
    assert "setHarnessModel" in text
    assert "/api/harness/set" in text
    assert "refreshLive" in text


def test_bar_and_service_prefer_http() -> None:
    bar = (ROOT / "BarWidget.qml").read_text(encoding="utf-8")
    svc = (ROOT / "Service.qml").read_text(encoding="utf-8")
    assert "pollStatusHttp" in bar and "pollHttp" in bar
    assert "httpLive" in bar
    assert "pollStatusHttp" in svc and "httpLive" in svc


def test_config_harness_editor_exists() -> None:
    path = ROOT / "ConfigHarnessEditor.qml"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "modelCommit" in text
    assert "default_model" in text
