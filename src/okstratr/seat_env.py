"""Environment handed to seats.

Seats run on the user's subscription logins, not on provider API keys.
Provider keys in okstratr's own environment are removed before any seat
process starts, so a seat cannot bill an API account by accident.
Set ``OKSTRATR_SEAT_API_KEYS=allow`` to pass them through on purpose.
"""

from __future__ import annotations

import os
from typing import Mapping

PROVIDER_KEY_VARS: tuple[str, ...] = (
    "XAI_API_KEY",
    "GROK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
)


def keys_allowed(env: Mapping[str, str] | None = None) -> bool:
    raw = (env if env is not None else os.environ).get("OKSTRATR_SEAT_API_KEYS", "")
    return raw.strip().lower() in ("allow", "1", "true", "yes", "on")


def strip_provider_keys(env: Mapping[str, str]) -> dict[str, str]:
    """Copy of ``env`` without provider API keys (unless explicitly allowed)."""
    out = dict(env)
    if keys_allowed(out):
        return out
    for k in PROVIDER_KEY_VARS:
        out.pop(k, None)
    return out
