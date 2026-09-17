"""Built-in harness definitions aligned with Herdr --kind where possible."""

from __future__ import annotations

import shutil
from typing import Callable

from .types import HarnessDef, HarnessId

# Align with Herdr --kind values where known; ids are okstratr-facing.
BUILTIN: dict[HarnessId, HarnessDef] = {
    "grok": HarnessDef(
        id="grok",
        herdr_kind="grok",
        bin_names=("grok",),
        label="Grok",
        default_models=("grok-4.6", "grok-4"),
        notes="xAI Grok CLI / Herdr grok kind (historical DEFAULT_KIND).",
    ),
    "claude": HarnessDef(
        id="claude",
        herdr_kind="claude",
        bin_names=("claude", "claude-code"),
        label="Claude Code",
        default_models=("claude-sonnet-4", "claude-opus-4"),
        notes="Anthropic Claude Code / Herdr claude kind.",
    ),
    "pi": HarnessDef(
        id="pi",
        herdr_kind="pi",
        bin_names=("pi",),
        label="Pi",
        default_models=(),
        notes="Pi agent harness.",
    ),
    "codex": HarnessDef(
        id="codex",
        herdr_kind="codex",
        bin_names=("codex",),
        label="OpenAI Codex",
        default_models=("gpt-5", "o3"),
        notes="OpenAI Codex CLI.",
    ),
    "omp": HarnessDef(
        id="omp",
        herdr_kind="omp",
        bin_names=("omp",),
        label="OMP",
        default_models=(),
    ),
    "opencode": HarnessDef(
        id="opencode",
        herdr_kind="opencode",
        bin_names=("opencode",),
        label="OpenCode",
        default_models=(),
    ),
    "cursor": HarnessDef(
        id="cursor",
        herdr_kind="cursor",
        bin_names=("cursor", "cursor-agent"),
        label="Cursor",
        default_models=(),
        notes="Cursor agent CLI when available.",
    ),
}

# Preference order when multiple harnesses are enabled + installed (P1 round-robin base).
DEFAULT_PREFERENCE: tuple[HarnessId, ...] = (
    "grok",
    "claude",
    "codex",
    "pi",
    "omp",
    "opencode",
    "cursor",
)


def get(harness_id: HarnessId) -> HarnessDef | None:
    return BUILTIN.get((harness_id or "").strip().lower())


def list_defs() -> list[HarnessDef]:
    return [BUILTIN[k] for k in DEFAULT_PREFERENCE if k in BUILTIN]


def detect_installed(
    harness_id: HarnessId,
    *,
    which: Callable[[str], str | None] | None = None,
) -> bool:
    """True if any declared binary is on PATH (or which() finds it)."""
    h = get(harness_id)
    if h is None:
        return False
    finder = which or shutil.which
    for name in h.bin_names:
        if finder(name):
            return True
    return False


def detect_all(
    *,
    which: Callable[[str], str | None] | None = None,
) -> dict[HarnessId, bool]:
    return {h.id: detect_installed(h.id, which=which) for h in list_defs()}
