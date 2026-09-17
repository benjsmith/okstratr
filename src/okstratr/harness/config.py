"""Load/save ~/.config/okstratr/harnesses.toml (allowlist + model pools + rungs)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import registry
from .types import HarnessId, ModelSpec


@dataclass
class PerHarnessSettings:
    """Per-harness model pool, default, effort/rung map, and free-form settings."""

    models: list[str] = field(default_factory=list)
    default_model: str | None = None
    # trivial|normal|hard → model id or {model, flags}
    effort: dict[str, Any] = field(default_factory=dict)
    # e.g. {"reasoning": "low"} for grok-4.6
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"models": list(self.models)}
        if self.default_model:
            d["default_model"] = self.default_model
        if self.effort:
            d["effort"] = dict(self.effort)
        if self.settings:
            d["settings"] = dict(self.settings)
        return d


@dataclass
class HarnessConfig:
    """User harness allowlist + preference + model pools + rungs."""

    enabled: list[HarnessId] = field(default_factory=lambda: ["grok"])
    preference: list[HarnessId] = field(default_factory=list)
    # harness_id -> list of model ids (legacy flat form; merged into harness.*)
    models: dict[str, list[str]] = field(default_factory=dict)
    # Phase 2: per-harness nested settings
    harness: dict[str, PerHarnessSettings] = field(default_factory=dict)
    # optional per-role overrides: role -> harness_id
    role_harness: dict[str, HarnessId] = field(default_factory=dict)
    # default model settings (adapter, backend, …)
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

    def settings_for(self, harness_id: HarnessId) -> PerHarnessSettings:
        hid = (harness_id or "").strip().lower()
        if hid in self.harness:
            return self.harness[hid]
        # Synthesize from legacy flat models + builtins
        models = list(self.models.get(hid) or self.models.get(harness_id) or [])
        if not models:
            h = registry.get(hid)
            if h and h.default_models:
                models = list(h.default_models)
        return PerHarnessSettings(models=models, default_model=models[0] if models else None)

    def models_for(self, harness_id: HarnessId) -> list[ModelSpec]:
        s = self.settings_for(harness_id)
        out: list[ModelSpec] = []
        for item in s.models:
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
            h = registry.get((harness_id or "").strip().lower())
            if h and h.default_models:
                out = [ModelSpec(id=m) for m in h.default_models]
        return out

    def default_model_for(self, harness_id: HarnessId) -> str | None:
        s = self.settings_for(harness_id)
        if s.default_model:
            return s.default_model
        mods = self.models_for(harness_id)
        return mods[0].id if mods else None

    def effort_map_for(self, harness_id: HarnessId) -> dict[str, Any]:
        return dict(self.settings_for(harness_id).effort or {})

    def preferred_backend(self) -> str:
        """herdr | direct — from defaults.adapter or defaults.backend."""
        raw = (
            self.defaults.get("backend")
            or self.defaults.get("adapter")
            or "herdr"
        )
        return str(raw).strip().lower() or "herdr"

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": list(self.enabled),
            "preference": list(self.preference),
            "models": {k: list(v) for k, v in self.models.items()},
            "harness": {k: v.to_dict() for k, v in self.harness.items()},
            "role_harness": dict(self.role_harness),
            "defaults": dict(self.defaults),
            "path": str(self.path) if self.path else None,
        }


def config_dir() -> Path:
    raw = (os.environ.get("OKSTRATR_CONFIG_DIR") or "").strip()
    if raw:
        p = Path(raw).expanduser()
    else:
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
        enabled=["grok", "claude"],
        preference=["grok", "claude"],
        models={
            "grok": ["grok-4.6", "grok-4"],
            "claude": ["claude-haiku", "haiku", "claude-sonnet-4", "claude-opus-4"],
            "codex": ["gpt-5", "o3"],
        },
        harness={
            "grok": PerHarnessSettings(
                models=["grok-4.6", "grok-4"],
                default_model="grok-4.6",
                effort={"trivial": "grok-4.6", "normal": "grok-4.6", "hard": "grok-4.6"},
                settings={"reasoning": "low"},
            ),
            "claude": PerHarnessSettings(
                models=["claude-haiku", "haiku", "claude-sonnet-4", "claude-opus-4"],
                default_model="claude-haiku",
                effort={
                    "trivial": "claude-haiku",
                    "normal": "claude-sonnet-4",
                    "hard": "claude-opus-4",
                },
            ),
            "codex": PerHarnessSettings(
                models=["gpt-5", "o3"],
                default_model="gpt-5",
                effort={"trivial": "gpt-5", "normal": "gpt-5", "hard": "o3"},
            ),
        },
        defaults={"adapter": "herdr", "backend": "herdr"},
    )


def _parse_per_harness(raw: Any) -> dict[str, PerHarnessSettings]:
    out: dict[str, PerHarnessSettings] = {}
    if not isinstance(raw, dict):
        return out
    for hid, body in raw.items():
        key = str(hid).strip().lower()
        if isinstance(body, list):
            # shorthand: harness.claude = ["m1","m2"]
            out[key] = PerHarnessSettings(models=[str(x) for x in body])
            continue
        if not isinstance(body, dict):
            continue
        models_raw = body.get("models") or []
        models: list[str] = []
        if isinstance(models_raw, list):
            models = [str(x) for x in models_raw]
        elif isinstance(models_raw, str):
            models = [x.strip() for x in models_raw.split(",") if x.strip()]
        default_model = body.get("default_model")
        if default_model is not None:
            default_model = str(default_model).strip() or None
        effort = body.get("effort") if isinstance(body.get("effort"), dict) else {}
        settings = body.get("settings") if isinstance(body.get("settings"), dict) else {}
        # also accept effort_trivial style keys
        for rung in ("trivial", "normal", "hard"):
            alt = body.get(f"effort_{rung}") or body.get(rung)
            if alt and rung not in effort:
                effort[rung] = alt
        out[key] = PerHarnessSettings(
            models=models,
            default_model=default_model,
            effort=dict(effort or {}),
            settings=dict(settings or {}),
        )
    return out


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
    # Nested [harnesses.harness.claude] or [harness.claude]
    harness_raw = data.get("harness") or {}
    per = _parse_per_harness(harness_raw)
    # Also accept top-level default_model table
    dm = data.get("default_model") or {}
    if isinstance(dm, dict):
        for k, v in dm.items():
            key = str(k).strip().lower()
            s = per.get(key) or PerHarnessSettings(models=list(models.get(key) or []))
            s.default_model = str(v).strip() or None
            per[key] = s
    # Effort table: [harnesses.effort.claude] trivial=...
    effort_tbl = data.get("effort") or {}
    if isinstance(effort_tbl, dict):
        for k, v in effort_tbl.items():
            key = str(k).strip().lower()
            s = per.get(key) or PerHarnessSettings(models=list(models.get(key) or []))
            if isinstance(v, dict):
                s.effort = {str(rk): vv for rk, vv in v.items()}
            per[key] = s
    # Sync flat models from per-harness when present
    for hid, s in per.items():
        if s.models and hid not in models:
            models[hid] = list(s.models)
        elif not s.models and hid in models:
            s.models = list(models[hid])
    return HarnessConfig(
        enabled=[str(e).strip().lower() for e in enabled if str(e).strip()],
        preference=[str(p).strip().lower() for p in preference if str(p).strip()],
        models=models,
        harness=per,
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
    if "harnesses" in data and isinstance(data["harnesses"], dict):
        body = data["harnesses"]
    else:
        body = data
    cfg = _parse_toml(body)
    cfg.path = p
    return cfg


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _dump_effort_val(v: Any) -> str:
    if isinstance(v, dict):
        # inline table
        parts = []
        if v.get("model") or v.get("id"):
            parts.append(f'model = "{_toml_escape(str(v.get("model") or v.get("id")))}"')
        flags = v.get("flags")
        if isinstance(flags, list) and flags:
            arr = ", ".join(f'"{_toml_escape(str(f))}"' for f in flags)
            parts.append(f"flags = [{arr}]")
        return "{ " + ", ".join(parts) + " }"
    return f'"{_toml_escape(str(v))}"'


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
    # Prefer harness nested models; fall back to flat
    model_keys = set(cfg.models) | set(cfg.harness)
    for hid in sorted(model_keys):
        mods = list(cfg.harness[hid].models) if hid in cfg.harness and cfg.harness[hid].models else list(cfg.models.get(hid) or [])
        if not mods:
            continue
        arr = ", ".join(f'"{_toml_escape(m)}"' for m in mods)
        lines.append(f"{hid} = [{arr}]")
    # Per-harness nested tables
    for hid in sorted(cfg.harness.keys()):
        s = cfg.harness[hid]
        lines.append("")
        lines.append(f"[harnesses.harness.{hid}]")
        if s.default_model:
            lines.append(f'default_model = "{_toml_escape(s.default_model)}"')
        if s.models:
            arr = ", ".join(f'"{_toml_escape(m)}"' for m in s.models)
            lines.append(f"models = [{arr}]")
        if s.effort:
            lines.append("")
            lines.append(f"[harnesses.harness.{hid}.effort]")
            for rung, val in s.effort.items():
                lines.append(f"{rung} = {_dump_effort_val(val)}")
        if s.settings:
            lines.append("")
            lines.append(f"[harnesses.harness.{hid}.settings]")
            for sk, sv in s.settings.items():
                if isinstance(sv, bool):
                    lines.append(f"{sk} = {'true' if sv else 'false'}")
                elif isinstance(sv, (int, float)):
                    lines.append(f"{sk} = {sv}")
                else:
                    lines.append(f'{sk} = "{_toml_escape(str(sv))}"')
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
        cfg.enabled = ["grok"]
    save(cfg, path or cfg.path)
    return cfg


def _ensure_harness_settings(cfg: HarnessConfig, hid: str) -> PerHarnessSettings:
    if hid not in cfg.harness:
        mods = list(cfg.models.get(hid) or [])
        cfg.harness[hid] = PerHarnessSettings(models=mods)
    return cfg.harness[hid]


def set_value(key: str, value: str, *, path: Path | None = None) -> HarnessConfig:
    """Set config key.

    Keys:
      enabled | preference | models.<id> | defaults.<k> | role_harness.<role>
      harness.<id>.default_model | harness.<id>.models | harness.<id>.effort.<rung>
      backend (alias defaults.backend)
      blackboard.duration | blackboard.duration_days | …
    """
    k0 = key.strip().lower()
    if k0.startswith("blackboard.") or k0 in (
        "duration",
        "duration_days",
        "retention",
        "retention_days",
        "archive_on_clear",
    ):
        from okstratr import bb_settings

        bb_settings.set_value(k0 if k0.startswith("blackboard.") else f"blackboard.{k0}", value)
        return load(path)
    cfg = load(path)
    k = k0
    if k in ("backend", "adapter"):
        cfg.defaults["backend"] = value.strip().lower()
        cfg.defaults["adapter"] = value.strip().lower()
    elif k == "enabled":
        cfg.enabled = [x.strip().lower() for x in value.split(",") if x.strip()]
        if not cfg.enabled:
            cfg.enabled = ["grok"]
    elif k == "preference":
        cfg.preference = [x.strip().lower() for x in value.split(",") if x.strip()]
    elif k.startswith("models."):
        hid = k.split(".", 1)[1]
        mods = [x.strip() for x in value.split(",") if x.strip()]
        cfg.models[hid] = mods
        s = _ensure_harness_settings(cfg, hid)
        s.models = mods
    elif k.startswith("defaults."):
        dk = k.split(".", 1)[1]
        cfg.defaults[dk] = value
    elif k.startswith("role_harness.") or k.startswith("role."):
        role = k.split(".", 1)[1]
        cfg.role_harness[role] = value.strip().lower()
    elif k.startswith("harness."):
        # harness.claude.default_model | harness.claude.models | harness.claude.effort.hard
        parts = k.split(".")
        if len(parts) < 3:
            raise ValueError(
                "use harness.<id>.default_model|models|effort.<rung>"
            )
        hid = parts[1]
        field = parts[2]
        s = _ensure_harness_settings(cfg, hid)
        if field == "default_model":
            s.default_model = value.strip() or None
        elif field == "models":
            mods = [x.strip() for x in value.split(",") if x.strip()]
            s.models = mods
            cfg.models[hid] = mods
        elif field == "settings":
            # harness.grok.settings.reasoning low  OR harness.grok.settings {"reasoning":"low"}
            if len(parts) >= 4:
                sk = parts[3]
                s.settings[sk] = value.strip()
            else:
                import json as _json
                try:
                    parsed = _json.loads(value)
                    if isinstance(parsed, dict):
                        s.settings.update({str(k): v for k, v in parsed.items()})
                    else:
                        raise ValueError("settings value must be object")
                except _json.JSONDecodeError as e:
                    if "=" in value:
                        sk, _, sv = value.partition("=")
                        s.settings[sk.strip()] = sv.strip()
                    else:
                        raise ValueError(
                            "use harness.<id>.settings.<key> <value>"
                        ) from e
        elif field == "effort" and len(parts) >= 4:
            rung = parts[3]
            s.effort[rung] = value.strip()
        else:
            raise ValueError(
                f"unknown harness field: {field} "
                "(default_model|models|effort.<rung>)"
            )
    else:
        raise ValueError(
            f"unknown config key: {key} "
            "(use enabled|preference|models.<id>|defaults.<k>|role_harness.<role>|"
            "harness.<id>.default_model|backend)"
        )
    save(cfg, path or cfg.path)
    return cfg


def list_for_api(cfg: HarnessConfig | None = None) -> dict[str, Any]:
    """Public harness rows for Panel/TUI/HTTP (enable flags, models, effort rungs)."""
    from . import registry

    cfg = cfg or load()
    installed = registry.detect_all()
    rows: list[dict[str, Any]] = []
    for hdef in registry.list_defs():
        hid = hdef.id
        settings = cfg.settings_for(hid) if hasattr(cfg, "settings_for") else None
        models = [m.id if hasattr(m, "id") else str(m) for m in cfg.models_for(hid)]
        rows.append(
            {
                "id": hid,
                "label": hdef.label or hid,
                "herdr_kind": hdef.herdr_kind,
                "enabled": cfg.is_enabled(hid),
                "installed": bool(installed.get(hid)),
                "bin_names": list(hdef.bin_names),
                "default_model": cfg.default_model_for(hid),
                "models": models,
                "effort": dict(cfg.effort_map_for(hid) or {}),
                "settings": dict(getattr(settings, "settings", None) or {}),
                "notes": hdef.notes or "",
            }
        )
    bb = {}
    try:
        from okstratr import bb_settings

        bb = bb_settings.load()
        bb = {**bb, "chip": bb_settings.mode_chip()}
    except Exception:  # noqa: BLE001
        bb = {"duration_days": 3.0, "chip": "bb: 3d"}
    return {
        "ok": True,
        "path": str(cfg.path or config_path()),
        "enabled": list(cfg.enabled),
        "preference": list(cfg.preference_order()),
        "defaults": dict(cfg.defaults),
        "backend": cfg.preferred_backend(),
        "harnesses": rows,
        "blackboard": bb,
    }
