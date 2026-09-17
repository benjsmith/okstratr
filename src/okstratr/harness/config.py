"""Load/save ~/.config/okstratr/harnesses.toml (allowlist + model pools)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import registry
from .types import HarnessId, ModelSpec


@dataclass
class HarnessConfig:
    """User harness allowlist + preference + model pools."""

    enabled: list[HarnessId] = field(default_factory=lambda: ["grok"])
    preference: list[HarnessId] = field(default_factory=list)
    # harness_id -> list of model ids (or ModelSpec dicts)
    models: dict[str, list[str]] = field(default_factory=dict)
    # optional per-role overrides: role -> harness_id
    role_harness: dict[str, HarnessId] = field(default_factory=dict)
    # default model settings (Switchbay-inspired effort hooks later)
    defaults: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    def is_enabled(self, harness_id: HarnessId) -> bool:
        return (harness_id or "").strip().lower() in {
            e.strip().lower() for e in self.enabled
        }

    def preference_order(self) -> list[HarnessId]:
        pref = [p.strip().lower() for p in (self.preference or []) if p.strip()]
        if not pref:
            pref = list(registry.DEFAULT_PREFERENCE)
        # enabled first in preference order, then any remaining enabled
        enabled = {e.strip().lower() for e in self.enabled}
        ordered: list[str] = []
        for p in pref:
            if p in enabled and p not in ordered:
                ordered.append(p)
        for e in self.enabled:
            el = e.strip().lower()
            if el and el not in ordered:
                ordered.append(el)
        return ordered

    def models_for(self, harness_id: HarnessId) -> list[ModelSpec]:
        hid = (harness_id or "").strip().lower()
        raw = self.models.get(hid) or self.models.get(harness_id) or []
        out: list[ModelSpec] = []
        for item in raw:
            if isinstance(item, str):
                out.append(ModelSpec(id=item))
            elif isinstance(item, dict) and item.get("id"):
                out.append(
                    ModelSpec(
                        id=str(item["id"]),
                        label=str(item.get("label") or ""),
                        settings=dict(item.get("settings") or {}),
                    )
                )
        if not out:
            h = registry.get(hid)
            if h and h.default_models:
                out = [ModelSpec(id=m) for m in h.default_models]
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": list(self.enabled),
            "preference": list(self.preference),
            "models": {k: list(v) for k, v in self.models.items()},
            "role_harness": dict(self.role_harness),
            "defaults": dict(self.defaults),
            "path": str(self.path) if self.path else None,
        }


def config_dir() -> Path:
    raw = (os.environ.get("OKSTRATR_CONFIG_DIR") or "").strip()
    if raw:
        p = Path(raw).expanduser()
    else:
        # Prefer XDG config; fall back under state dir when unset in weird envs
        xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
        if xdg:
            p = Path(xdg).expanduser() / "okstratr"
        else:
            p = Path.home() / ".config" / "okstratr"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    override = (os.environ.get("OKSTRATR_HARNESSES_TOML") or "").strip()
    if override:
        return Path(override).expanduser()
    return config_dir() / "harnesses.toml"


def default_config() -> HarnessConfig:
    return HarnessConfig(
        enabled=["grok"],
        preference=list(registry.DEFAULT_PREFERENCE),
        models={
            "grok": ["grok-4"],
            "claude": ["claude-sonnet-4"],
            "codex": ["gpt-5"],
        },
        defaults={"adapter": "herdr"},
    )


def _parse_toml(data: dict[str, Any]) -> HarnessConfig:
    enabled = data.get("enabled")
    if isinstance(enabled, str):
        enabled = [x.strip() for x in enabled.split(",") if x.strip()]
    if not isinstance(enabled, list) or not enabled:
        enabled = ["grok"]
    preference = data.get("preference") or []
    if isinstance(preference, str):
        preference = [x.strip() for x in preference.split(",") if x.strip()]
    models_raw = data.get("models") or {}
    models: dict[str, list[str]] = {}
    if isinstance(models_raw, dict):
        for k, v in models_raw.items():
            if isinstance(v, list):
                models[str(k)] = [str(x) for x in v]
            elif isinstance(v, str):
                models[str(k)] = [x.strip() for x in v.split(",") if x.strip()]
    role_harness = {}
    rh = data.get("role_harness") or {}
    if isinstance(rh, dict):
        role_harness = {str(k): str(v) for k, v in rh.items()}
    defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
    return HarnessConfig(
        enabled=[str(e).strip().lower() for e in enabled if str(e).strip()],
        preference=[str(p).strip().lower() for p in preference if str(p).strip()],
        models=models,
        role_harness=role_harness,
        defaults=dict(defaults or {}),
    )


def load(path: Path | None = None) -> HarnessConfig:
    p = path or config_path()
    if not p.is_file():
        cfg = default_config()
        cfg.path = p
        return cfg
    with p.open("rb") as f:
        data = tomllib.load(f)
    # Support [harnesses] table or flat root
    if "harnesses" in data and isinstance(data["harnesses"], dict):
        body = data["harnesses"]
    else:
        body = data
    cfg = _parse_toml(body)
    cfg.path = p
    return cfg


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _dump_toml(cfg: HarnessConfig) -> str:
    lines: list[str] = [
        "# okstratr harness allowlist — Switchbay-inspired, no LiteLLM",
        "# See docs/ADR-001-cli-tui-harness.md",
        "",
        "[harnesses]",
        "enabled = [" + ", ".join(f'"{_toml_escape(e)}"' for e in cfg.enabled) + "]",
    ]
    if cfg.preference:
        lines.append(
            "preference = ["
            + ", ".join(f'"{_toml_escape(e)}"' for e in cfg.preference)
            + "]"
        )
    lines.append("")
    lines.append("[harnesses.models]")
    for hid, mods in (cfg.models or {}).items():
        arr = ", ".join(f'"{_toml_escape(m)}"' for m in mods)
        lines.append(f'{hid} = [{arr}]')
    if cfg.role_harness:
        lines.append("")
        lines.append("[harnesses.role_harness]")
        for role, hid in cfg.role_harness.items():
            lines.append(f'{role} = "{_toml_escape(hid)}"')
    if cfg.defaults:
        lines.append("")
        lines.append("[harnesses.defaults]")
        for k, v in cfg.defaults.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}")
            else:
                lines.append(f'{k} = "{_toml_escape(str(v))}"')
    lines.append("")
    return "\n".join(lines)


def save(cfg: HarnessConfig, path: Path | None = None) -> Path:
    p = path or cfg.path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_dump_toml(cfg), encoding="utf-8")
    cfg.path = p
    return p


def enable(harness_id: HarnessId, *, path: Path | None = None) -> HarnessConfig:
    hid = harness_id.strip().lower()
    if registry.get(hid) is None:
        raise ValueError(f"unknown harness: {harness_id}")
    cfg = load(path)
    if hid not in cfg.enabled:
        cfg.enabled.append(hid)
    save(cfg, path or cfg.path)
    return cfg


def disable(harness_id: HarnessId, *, path: Path | None = None) -> HarnessConfig:
    hid = harness_id.strip().lower()
    cfg = load(path)
    cfg.enabled = [e for e in cfg.enabled if e != hid]
    if not cfg.enabled:
        # Never leave empty allowlist — fall back to grok for safety
        cfg.enabled = ["grok"]
    save(cfg, path or cfg.path)
    return cfg


def set_value(key: str, value: str, *, path: Path | None = None) -> HarnessConfig:
    """Simple `config set` — keys: enabled, preference, defaults.adapter, models.<id>."""
    cfg = load(path)
    k = key.strip().lower()
    if k == "enabled":
        cfg.enabled = [x.strip().lower() for x in value.split(",") if x.strip()]
        if not cfg.enabled:
            cfg.enabled = ["grok"]
    elif k == "preference":
        cfg.preference = [x.strip().lower() for x in value.split(",") if x.strip()]
    elif k.startswith("models."):
        hid = k.split(".", 1)[1]
        cfg.models[hid] = [x.strip() for x in value.split(",") if x.strip()]
    elif k.startswith("defaults."):
        dk = k.split(".", 1)[1]
        cfg.defaults[dk] = value
    elif k.startswith("role_harness.") or k.startswith("role."):
        role = k.split(".", 1)[1]
        cfg.role_harness[role] = value.strip().lower()
    else:
        raise ValueError(
            f"unknown config key: {key} "
            "(use enabled|preference|models.<id>|defaults.<k>|role_harness.<role>)"
        )
    save(cfg, path or cfg.path)
    return cfg
