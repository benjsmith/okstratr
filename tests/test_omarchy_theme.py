"""okstratr follows the applied Omarchy theme like okbay's Atlas.

Lines, borders and agent-space edges use the theme's muted colour; edges
carrying work use its light foreground; accent stays for focus and selected
states; agent roles take the theme's named colours.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OBS = ROOT / "src" / "okstratr" / "observer"

SWITCHBAY = """
mode = "dark"
accent = "#6be8b3"
muted = "#343942"
background = "#0f1115"
dark_background = "#0c0e12"
darker_background = "#08090c"
lighter_background = "#161a21"
foreground = "#e6e8eb"
dark_foreground = "#5a6068"
light_foreground = "#9aa0a8"
red = "#cc503e"
yellow = "#edad08"
green = "#0f8554"
cyan = "#38a6a5"
blue = "#1d6996"
magenta = "#94346e"
bright_magenta = "#9656a2"
"""


@pytest.fixture()
def omarchy_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    theme_dir = tmp_path / ".local" / "state" / "omarchy" / "current" / "theme"
    theme_dir.mkdir(parents=True)
    (theme_dir / "colors.toml").write_text(SWITCHBAY, encoding="utf-8")
    (theme_dir.parent / "theme.name").write_text("switchbay\n", encoding="utf-8")
    return tmp_path


def test_resolve_maps_like_atlas(omarchy_home: Path):
    from okstratr import theme

    t = theme.resolve()
    assert t["name"] == "switchbay"
    ui = t["ui"]
    assert ui["border"] == ui["divider"] == ui["edge"] == "#343942"
    assert ui["edge_active"] == "#9aa0a8"
    assert ui["accent"] == "#6be8b3"
    # The accent never becomes a line or edge colour.
    assert "#6be8b3" not in (ui["border"], ui["divider"], ui["edge"], ui["edge_active"])
    assert ui["panel"] == "#0f1115" and ui["bg"] == "#0c0e12" and ui["fg"] == "#e6e8eb"
    assert t["roles"]["cos"] == "#38a6a5"
    assert t["roles"]["synthesizer"] == "#0f8554"
    assert t["roles"]["verifier"] == "#edad08"
    assert t["roles"]["blackboard"] == "#9656a2"


def test_resolve_falls_back_without_theme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    from okstratr import theme

    t = theme.resolve()
    assert t["source"] == ""
    assert t["ui"]["border"] == "#292e42"
    assert t["ui"]["accent"] == "#7aa2f7"


def test_ansi_only_theme(tmp_path: Path):
    from okstratr import theme

    p = tmp_path / "colors.toml"
    p.write_text('background = "#111111"\nforeground = "#eeeeee"\ncolor4 = "#3366cc"\ncolor8 = "#444444"\ncolor2 = "#22aa44"\n')
    t = theme.resolve(p)
    assert t["ui"]["accent"] == "#3366cc"
    assert t["ui"]["border"] == "#444444"
    assert t["roles"]["synthesizer"] == "#22aa44"


def test_api_theme_route(omarchy_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    from okstratr import server

    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        conn = HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
        conn.request("GET", "/api/theme")
        resp = conn.getresponse()
        body = json.loads(resp.read())
    finally:
        httpd.shutdown()
    assert resp.status == 200
    assert body["ok"] is True
    assert body["ui"]["edge"] == "#343942"
    assert body["roles"]["cos"] == "#38a6a5"


def _node(script: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return json.loads(subprocess.check_output(["node", "-e", script], text=True))


def test_agent_space_edges_follow_edge_vars():
    helper = OBS / "agent_space_theme.js"
    out = _node(f"""
const t = require({json.dumps(str(helper))});
const vars = {{"--fg": "#e6e8eb", "--border": "#343942", "--accent": "#6be8b3",
  "--edge": "#343942", "--edge-active": "#9aa0a8", "--role-cos": "#38a6a5", "--recessed": "#08090c"}};
const c = t.agentSpaceThemeColors({{ getPropertyValue: n => vars[n] || "" }});
process.stdout.write(JSON.stringify(c));
""")
    assert out["idleEdge"] == "rgba(52, 57, 66, 0.95)"
    assert out["flowingEdge"] == "rgba(154, 160, 168, 0.8)"
    assert out["particle"] == "rgba(154, 160, 168, 0.95)"
    assert out["activeRing"] == "rgba(154, 160, 168, 0.7)"
    assert out["cosGlow"] == "rgba(56, 166, 165, 0.12)"
    assert out["nodeStroke"] == "#08090c"
    assert all("107, 232, 179" not in str(v) for v in out.values())


def test_model_role_colours_use_theme():
    model = ROOT / "Model.js"
    out = _node(f"""
const src = require("fs").readFileSync({json.dumps(str(model))}, "utf8").replace(/^\\.(pragma|import).*$/gm, "");
const m = {{}}; new Function("exports", src + "\\nexports.f = nodeColorForRole;")(m);
process.stdout.write(JSON.stringify({{
  themed: m.f("synthesizer", {{ synthesizer: "#0f8554", default: "#9aa0a8" }}),
  curator: m.f("curator-a", {{ planner: "#5a6068" }}),
  plain: m.f("synthesizer"),
}}));
""")
    assert out == {"themed": "#0f8554", "curator": "#5a6068", "plain": "#4ade80"}


def test_no_hardcoded_green_or_teal_in_agent_space_paint():
    js = (OBS / "observer.js").read_text(encoding="utf-8")
    paint = js[js.index("function paintAgentSpace()"):js.index("function ensureAnimLoop()")]
    for literal in ("158, 206, 106", "45, 212, 191", "#99f6e4"):
        assert literal not in paint.split("const theme =", 1)[1].split("};", 1)[1], literal
    assert "applyOmarchyTheme" in js and "/api/theme" in js
    apply_fn = js[js.index("function applyOmarchyTheme"):js.index("function loadOmarchyTheme")]
    assert "currentHosted()" in apply_fn


def test_qml_panel_lines_are_muted_not_accent():
    qml = (ROOT / "Panel.qml").read_text(encoding="utf-8")
    assert "popups.border" not in qml
    assert "/api/theme" in qml
    assert "root.themeEdge.r" in qml
    for literal in ("#662dd4bf", "#222dd4bf", "#99f6e4", "#3344aa88"):
        assert literal not in qml, literal
    assert "nodeColorForRole(node.role || node.kind, root.themeRoles)" in qml
    rail = (ROOT / "DeskRail.qml").read_text(encoding="utf-8")
    assert "#3344aa" not in rail
