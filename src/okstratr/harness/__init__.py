"""Harness-agnostic seating — registry, config, selection, direct adapter."""

from .config import (
    HarnessConfig,
    PerHarnessSettings,
    config_path,
    default_config,
    disable,
    enable,
    load,
    save,
    set_value,
)
from .direct import kill_direct_for_desk, run_direct, run_direct_stub
from .registry import BUILTIN, DEFAULT_PREFERENCE, detect_all, detect_installed, get, list_defs
from .rungs import RUNGS, effort_to_rung, parse_model_token, resolve_model_for_rung
from .select import choose_harness, list_models, reset_rr, resolve_herdr_kind
from .slash import SLASH_HELP, SlashDirectives, apply_harness_slash_to_env, parse_slash_directives
from .types import HarnessDef, HarnessId, ModelSpec, SeatRequest, SeatResult

__all__ = [
    "BUILTIN",
    "DEFAULT_PREFERENCE",
    "RUNGS",
    "SLASH_HELP",
    "HarnessConfig",
    "HarnessDef",
    "HarnessId",
    "ModelSpec",
    "PerHarnessSettings",
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
    "effort_to_rung",
    "enable",
    "get",
    "kill_direct_for_desk",
    "list_defs",
    "list_models",
    "load",
    "parse_model_token",
    "parse_slash_directives",
    "reset_rr",
    "resolve_herdr_kind",
    "resolve_model_for_rung",
    "run_direct",
    "run_direct_stub",
    "save",
    "set_value",
]
