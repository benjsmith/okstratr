"""Colours from the applied Omarchy theme for the okstratr panel and observer.

Reads the same ``colors.toml`` as Omarchy's shell and okbay's Atlas
(``~/.local/state/omarchy/current/theme/colors.toml``) and maps it the same
way Atlas does: lines and borders use the theme's ``muted`` colour, text uses
``foreground`` / ``dark_foreground``, and ``accent`` is kept for focus and
selected states. Agent-space edges stay neutral: idle edges use ``muted`` and
edges carrying work use ``light_foreground``. Agent roles take the theme's
named colours, as Atlas page types do.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Used when no Omarchy theme is installed (or a key is missing).
FALLBACK: dict[str, str] = {
    "mode": "dark",
    "accent": "#7aa2f7",
    "selection": "#283457",
    "muted": "#292e42",
    "background": "#1a1b26",
    "dark_background": "#13141c",
    "darker_background": "#0f1017",
    "lighter_background": "#24283b",
    "foreground": "#c0caf5",
    "dark_foreground": "#565f89",
    "light_foreground": "#a9b1d6",
    "bright_foreground": "#e6e8f0",
    "red": "#f7768e",
    "yellow": "#e0af68",
    "orange": "#ff9e64",
    "green": "#9ece6a",
    "cyan": "#7dcfff",
    "blue": "#7aa2f7",
    "magenta": "#bb9af7",
    "brown": "#a0826d",
    "bright_red": "#ff7a93",
    "bright_yellow": "#ffc777",
    "bright_green": "#b9f27c",
    "bright_cyan": "#b4f9f8",
    "bright_blue": "#89b4fa",
    "bright_magenta": "#c099ff",
}

# Agent role -> colours.toml key (same idea as okbay's page-type palette).
ROLE_TO_NAMED: dict[str, str] = {
    "cos": "cyan",
    "root": "cyan",
    "blackboard": "bright_magenta",
    "investigator": "blue",
    "researcher": "blue",
    "verifier": "yellow",
    "synthesizer": "green",
    "planner": "dark_foreground",
    "curator": "dark_foreground",
    "default": "light_foreground",
}

# ANSI fallbacks some themes use instead of named keys.
_ANSI = {
    "red": "color1", "green": "color2", "yellow": "color3", "blue": "color4",
    "magenta": "color5", "cyan": "color6", "muted": "color8",
    "bright_red": "color9", "bright_green": "color10", "bright_yellow": "color11",
    "bright_blue": "color12", "bright_magenta": "color13", "bright_cyan": "color14",
}


def _home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def colors_toml_path() -> Path | None:
    raw = os.environ.get("XDG_STATE_HOME")
    state = (Path(raw) if raw else _home() / ".local" / "state") / "omarchy" / "current"
    for p in (
        state / "theme" / "colors.toml",
        state / "next-theme" / "colors.toml",
        _home() / ".config" / "omarchy" / "current" / "theme" / "colors.toml",
    ):
        if p.is_file():
            return p
    return None


def theme_name() -> str:
    raw = os.environ.get("XDG_STATE_HOME")
    state = (Path(raw) if raw else _home() / ".local" / "state") / "omarchy" / "current"
    for p in (state / "theme.name", _home() / ".config" / "omarchy" / "current" / "theme.name"):
        try:
            name = p.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if name:
            return name
    return ""


def parse_colors(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("[") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.split(" #", 1)[0].strip().strip('"').strip("'")
        key = key.strip()
        if key and val:
            out[key] = val
    return out


def resolve(path: Path | None = None) -> dict[str, Any]:
    """Return the panel/observer theme as JSON-ready data."""
    path = path if path is not None else colors_toml_path()
    raw: dict[str, str] = {}
    if path is not None:
        try:
            raw = parse_colors(path.read_text(encoding="utf-8"))
        except OSError:
            raw = {}
    colors = dict(FALLBACK)
    for key in FALLBACK:
        if raw.get(key):
            colors[key] = raw[key]
        elif _ANSI.get(key) and raw.get(_ANSI[key]):
            colors[key] = raw[_ANSI[key]]
    if not raw.get("accent") and raw.get("color4"):
        colors["accent"] = raw["color4"]

    roles = {role: colors.get(named) or FALLBACK[named] for role, named in ROLE_TO_NAMED.items()}
    ui = {
        "bg": colors["dark_background"],
        "panel": colors["background"],
        "recessed": colors["darker_background"],
        "chip": colors["lighter_background"],
        "border": colors["muted"],
        "divider": colors["muted"],
        "text": colors["light_foreground"],
        "fg": colors["foreground"],
        "muted": colors["dark_foreground"],
        "accent": colors["accent"],
        "focus_border": colors["accent"],
        "ok": colors["green"],
        "warn": colors["yellow"],
        "bad": colors["red"],
        "purple": colors["magenta"],
        "edge": colors["muted"],
        "edge_active": colors["light_foreground"],
    }
    return {
        "ok": True,
        "name": theme_name() or ("omarchy" if path else "fallback"),
        "source": str(path) if path else "",
        "mode": raw.get("mode", colors["mode"]),
        "colors": colors,
        "ui": ui,
        "roles": roles,
    }
