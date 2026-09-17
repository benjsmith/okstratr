"""Blackboard duration settings — single knob for live-board retention.

``blackboard.duration`` (default 3 days):
- ``> 0``: retain live entries for that many days
- ``= 0``: ephemeral mode — agent/CoS posts clear ASAP; hard max age 60 minutes
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .harness import config as harness_config

# Hard ceiling when duration == 0 (minutes).
EPHEMERAL_MAX_MINUTES = 60

DEFAULTS: dict[str, Any] = {
    "duration_days": 3.0,  # canonical float days; 0 = ephemeral
    "archive_on_clear": False,
}


def _settings_path() -> Path:
    return harness_config.config_dir() / "blackboard.json"


def _truthy(s: str) -> bool | None:
    v = (s or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return None


def parse_duration(value: str | int | float) -> float:
    """Parse duration to days (float). Accepts ``3``, ``3d``, ``72h``, ``60m``, ``0``.

    Minutes/hours convert to fractional days. ``0`` means ephemeral mode.
    """
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    s = str(value or "").strip().lower().replace(" ", "")
    if not s:
        raise ValueError("empty duration")
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)([dhms]?)", s)
    if not m:
        raise ValueError(f"invalid duration: {value!r} (use 3, 3d, 72h, 60m, 0)")
    n = float(m.group(1))
    unit = m.group(2) or "d"
    if unit == "d":
        days = n
    elif unit == "h":
        days = n / 24.0
    elif unit == "m":
        days = n / (24.0 * 60.0)
    elif unit == "s":
        days = n / (24.0 * 3600.0)
    else:
        days = n
    return max(0.0, days)


def load() -> dict[str, Any]:
    out = dict(DEFAULTS)
    path = _settings_path()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            if "archive_on_clear" in raw:
                out["archive_on_clear"] = bool(raw["archive_on_clear"])
            # Prefer duration / duration_days; migrate retention_days / archive_ttl_days
            if "duration_days" in raw:
                try:
                    out["duration_days"] = max(0.0, float(raw["duration_days"]))
                except (TypeError, ValueError):
                    pass
            elif "duration" in raw:
                try:
                    out["duration_days"] = parse_duration(raw["duration"])
                except ValueError:
                    pass
            elif "retention_days" in raw:
                try:
                    out["duration_days"] = max(0.0, float(raw["retention_days"]))
                except (TypeError, ValueError):
                    pass
            elif "archive_ttl_days" in raw:
                try:
                    out["duration_days"] = max(0.0, float(raw["archive_ttl_days"]))
                except (TypeError, ValueError):
                    pass

    # Env overrides
    for env_key in (
        "OKSTRATR_BB_DURATION",
        "OKSTRATR_BB_DURATION_DAYS",
        "OKSTRATR_BB_RETENTION_DAYS",
        "OKSTRATR_BB_ARCHIVE_TTL_DAYS",
    ):
        env_raw = (os.environ.get(env_key) or "").strip()
        if env_raw:
            try:
                out["duration_days"] = parse_duration(env_raw)
            except ValueError:
                pass
            break

    t = _truthy(os.environ.get("OKSTRATR_BB_ARCHIVE_ON_CLEAR") or "")
    if t is not None:
        out["archive_on_clear"] = t

    out["path"] = str(path)
    out["duration"] = out["duration_days"]  # alias for display/API
    out["ephemeral"] = float(out["duration_days"]) <= 0.0
    out["ephemeral_max_minutes"] = EPHEMERAL_MAX_MINUTES
    return out


def save(updates: dict[str, Any]) -> dict[str, Any]:
    cur = load()
    path = _settings_path()
    for k, v in updates.items():
        if k in ("duration", "duration_days", "retention_days"):
            cur["duration_days"] = parse_duration(v) if not isinstance(v, (int, float)) else max(0.0, float(v))
        elif k == "archive_on_clear":
            cur["archive_on_clear"] = bool(v)
    payload = {
        "duration_days": float(cur["duration_days"]),
        "archive_on_clear": bool(cur["archive_on_clear"]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return load()


def set_value(key: str, value: str) -> dict[str, Any]:
    k = key.strip().lower()
    if k.startswith("blackboard."):
        k = k.split(".", 1)[1]
    # Aliases
    if k in ("duration", "duration_days", "retention", "retention_days"):
        return save({"duration_days": parse_duration(value)})
    if k == "archive_on_clear":
        t = _truthy(value)
        if t is None:
            raise ValueError("blackboard.archive_on_clear expects true|false")
        return save({"archive_on_clear": t})
    raise ValueError(
        f"unknown blackboard key: {key} (duration|duration_days|archive_on_clear)"
    )


def duration_days() -> float:
    return float(load().get("duration_days") or 0.0)


def is_ephemeral() -> bool:
    return duration_days() <= 0.0


def archive_on_clear() -> bool:
    return bool(load().get("archive_on_clear"))


def mode_chip() -> str:
    d = duration_days()
    if d <= 0:
        return "bb: ephemeral(≤60m)"
    if d == int(d):
        return f"bb: {int(d)}d"
    return f"bb: {d:.3g}d"


def format_duration(days: float) -> str:
    if days <= 0:
        return "0 (ephemeral ≤60m)"
    if days == int(days):
        return f"{int(days)}d"
    return f"{days:.6g}d"
