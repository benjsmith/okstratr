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


def test_panel_reopens_after_compositor_close() -> None:
    """Closing the window from Hyprland must not leave opened stuck true."""
    text = (ROOT / "Panel.qml").read_text(encoding="utf-8")
    vis = text[text.index("onVisibleChanged"):]
    vis = vis[: vis.index("}\n    }") + 1]
    assert "root.opened = false" in vis
    assert "root.close()" not in vis  # the close dialog can't show without a window
    opener = text[text.index("function open(payloadJson)"):]
    opener = opener[: opener.index("\n  }\n")]
    assert "!win.visible" in opener


def test_panel_asks_hyprland_to_maximize_on_map() -> None:
    """Omarchy suppresses client maximize requests, so the panel would tile
    behind floating desk windows. It must ask Hyprland to maximize it."""
    qml = (Path(__file__).resolve().parents[1] / "Panel.qml").read_text(encoding="utf-8")
    fn = qml.split("function maximizeInHyprland()", 1)[1].split("\n  }\n", 1)[0]
    assert "HYPRLAND_INSTANCE_SIGNATURE" in fn
    assert 'title:^Okstratr$' in fn
    assert 'mode = "maximized"' in fn
    assert 'action = "set"' in fn  # idempotent, safe to retry
    vis = qml.split("onVisibleChanged: {", 1)[1].split("\n    }\n", 1)[0]
    assert "maximizeTimer.restart()" in vis
    timer = qml.split("id: maximizeTimer", 1)[1].split("\n    }\n", 1)[0]
    assert "root.maximizeInHyprland()" in timer
    assert "stop()" in timer
