"""Harness-agnostic seating — registry, config, selection (Phase 1)."""

from .config import (
    HarnessConfig,
    config_path,
    default_config,
    disable,
    enable,
    load,
    save,
    set_value,
)
from .direct import run_direct_stub
from .registry import BUILTIN, DEFAULT_PREFERENCE, detect_all, detect_installed, get, list_defs
from .select import choose_harness, reset_rr, resolve_herdr_kind
from .slash import SlashDirectives, apply_harness_slash_to_env, parse_slash_directives
from .types import HarnessDef, HarnessId, ModelSpec, SeatRequest, SeatResult

__all__ = [
    "BUILTIN",
    "DEFAULT_PREFERENCE",
    "HarnessConfig",
    "HarnessDef",
    "HarnessId",
    "ModelSpec",
    "SeatRequest",
    "SeatResult",
    "SlashDirectives",
    "apply_harness_slash_to_env",
    "choose_harness",
    "config_path",
    "default_config",
    "detect_all",
    "detect_installed",
    "disable",
    "enable",
    "get",
    "list_defs",
    "load",
    "parse_slash_directives",
    "reset_rr",
    "resolve_herdr_kind",
    "run_direct_stub",
    "save",
    "set_value",
]
