"""Agent-space canvas theme colors: readable labels in light and dark."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "src" / "okstratr" / "observer" / "agent_space_theme.js"


def _resolve(vars: dict[str, str]) -> dict:
    script = f"""
const t = require({json.dumps(str(HELPER))});
function mock(vars) {{
  return {{ getPropertyValue(name) {{ return vars[name] || ""; }} }};
}}
const theme = t.agentSpaceThemeColors(mock({json.dumps(vars)}));
process.stdout.write(JSON.stringify(theme));
"""
    out = subprocess.check_output(["node", "-e", script], text=True)
    return json.loads(out)


def test_light_theme_label_and_idle_edge_readable():
    # Switchbay light remap on .sy-proxied-skill-html (mint accent).
    theme = _resolve(
        {
            "--fg": "#1a1d22",
            "--text": "#1a1d22",
            "--border": "#dfe2e7",
            "--accent": "#2f9874",
        }
    )
    assert theme["label"] == "#1a1d22"
    assert theme["idleEdge"] == "rgba(223, 226, 231, 0.95)"
    assert theme["flowingEdge"] == "rgba(47, 152, 116, 0.8)"


def test_dark_theme_keeps_readable_fg():
    theme = _resolve(
        {
            "--fg": "#c0caf5",
            "--text": "#e6e8eb",
            "--border": "#232830",
            "--accent": "#6be8b3",
        }
    )
    assert theme["label"] == "#c0caf5"
    assert theme["idleEdge"] == "rgba(35, 40, 48, 0.95)"
    assert theme["flowingEdge"] == "rgba(107, 232, 179, 0.8)"


def test_observer_js_no_longer_hardcodes_label_fill():
    src = (ROOT / "src" / "okstratr" / "observer" / "observer.js").read_text()
    assert 'ctx.fillStyle = "#c0caf5"' not in src
    assert "OkstratrAgentSpaceTheme" in src
    html = (ROOT / "src" / "okstratr" / "observer" / "index.html").read_text()
    assert "agent_space_theme.js" in html


def test_standing_placeholder_badge_uses_warn_not_muted():
    """Empty desk rows label "standing" with idle amber (--warn), not gray --muted."""
    css = (ROOT / "src" / "okstratr" / "observer" / "observer.css").read_text()
    js = (ROOT / "src" / "okstratr" / "observer" / "observer.js").read_text()
    assert "desk-obj--standing" in js
    assert "standingBadge" in js
    idx = css.index(".desk-obj.desk-obj--standing")
    rule = css[idx:css.index("}", idx)]
    assert "var(--warn)" in rule
    assert "var(--muted)" not in rule
    assert "var(--text)" not in rule
    base = css.index(".desk-obj {")
    base_rule = css[base:css.index("}", base)]
    assert "var(--muted)" in base_rule
