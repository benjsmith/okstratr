"""Switchbay-inspired model rungs / effort → model selection."""

from __future__ import annotations

from typing import Any

# Named difficulty rungs (trivial | normal | hard)
RUNGS = ("trivial", "normal", "hard")


def effort_to_rung(effort: float | None) -> str:
    """Map continuous effort [0,1] → trivial|normal|hard."""
    if effort is None:
        return "normal"
    try:
        e = max(0.0, min(1.0, float(effort)))
    except (TypeError, ValueError):
        return "normal"
    if e < 0.34:
        return "trivial"
    if e < 0.67:
        return "normal"
    return "hard"


def normalize_rung(rung: str | None) -> str | None:
    if not rung:
        return None
    r = str(rung).strip().lower()
    aliases = {
        "easy": "trivial",
        "low": "trivial",
        "medium": "normal",
        "med": "normal",
        "default": "normal",
        "high": "hard",
        "difficult": "hard",
    }
    r = aliases.get(r, r)
    return r if r in RUNGS else None


def resolve_model_for_rung(
    *,
    models: list[str],
    default_model: str | None,
    effort_map: dict[str, Any] | None,
    rung: str | None = None,
    effort: float | None = None,
    prefer_model: str | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Pick a model using prefer → rung map → default → first pool model.

    effort_map values may be model id strings or dicts with ``model`` / ``flags``.
    """
    detail: dict[str, Any] = {}
    if prefer_model:
        detail["source"] = "prefer_model"
        return prefer_model.strip(), detail

    rung_n = normalize_rung(rung) or effort_to_rung(effort)
    detail["rung"] = rung_n
    emap = effort_map or {}
    raw = emap.get(rung_n)
    flags: list[str] = []
    if isinstance(raw, dict):
        model = (raw.get("model") or raw.get("id") or "").strip() or None
        fl = raw.get("flags") or []
        if isinstance(fl, str):
            flags = [fl]
        elif isinstance(fl, list):
            flags = [str(x) for x in fl]
        detail["source"] = "effort_map"
        detail["flags"] = flags
        if model:
            return model, detail
    elif isinstance(raw, str) and raw.strip():
        detail["source"] = "effort_map"
        return raw.strip(), detail

    if default_model and str(default_model).strip():
        detail["source"] = "default_model"
        return str(default_model).strip(), detail

    if models:
        detail["source"] = "models_pool"
        return models[0], detail

    detail["source"] = "none"
    return None, detail


def parse_model_token(token: str) -> tuple[str | None, str | None]:
    """Parse ``claude:sonnet`` or ``grok-4`` → (harness_or_None, model).

    ``harness:model`` form sets both; bare model leaves harness None.
    """
    raw = (token or "").strip()
    if not raw:
        return None, None
    if ":" in raw:
        left, _, right = raw.partition(":")
        hid = left.strip().lower() or None
        model = right.strip() or None
        return hid, model
    return None, raw
