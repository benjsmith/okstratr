"""Per-harness argv templates for the direct CLI adapter."""

from __future__ import annotations

from typing import Any

from . import registry
from .types import HarnessId

# Templates: {bin}, {model}, {prompt}
# grok CLI takes a positional PROMPT (or --prompt-file), not --prompt.
# Options (--model, --reasoning-effort, --cwd, --disable-web-search) must
# appear before the positional prompt.

_ARGV: dict[HarnessId, list[str]] = {
    "grok": ["{bin}", "{prompt}"],
    "claude": ["{bin}", "--print", "--model", "{model}", "{prompt}"],
    "codex": ["{bin}", "exec", "--model", "{model}", "{prompt}"],
    "pi": ["{bin}", "{prompt}"],
    "omp": ["{bin}", "run", "--prompt", "{prompt}"],
    "opencode": ["{bin}", "run", "{prompt}"],
    "cursor": ["{bin}", "agent", "--print", "{prompt}"],
}

# Optional model flag injection when template lacks {model} but model is set.
_MODEL_FLAGS: dict[HarnessId, list[str]] = {
    "grok": ["--model", "{model}"],
    "pi": ["--model", "{model}"],
    "omp": ["--model", "{model}"],
    "opencode": ["--model", "{model}"],
    "cursor": ["--model", "{model}"],
}

# Harnesses that accept --cwd PATH before the prompt / trailing args.
_CWD_FLAG: dict[HarnessId, str] = {
    "grok": "--cwd",
}

# Harnesses that accept --disable-web-search when web egress is off.
_DISABLE_WEB_SEARCH: frozenset[HarnessId] = frozenset({"grok"})


def resolve_bin(
    harness_id: HarnessId,
    *,
    which: Any | None = None,
) -> str | None:
    """First binary on PATH for this harness, or None."""
    import shutil

    h = registry.get(harness_id)
    if h is None:
        return None
    finder = which or shutil.which
    for name in h.bin_names:
        found = finder(name)
        if found:
            return found
    return None


def _insert_before_prompt(argv: list[str], extra: list[str]) -> list[str]:
    """Insert option flags before the final positional prompt argument."""
    if not extra:
        return argv
    if len(argv) <= 1:
        return argv + list(extra)
    # Convention: last element is the prompt for templates that end with {prompt}.
    return argv[:-1] + list(extra) + [argv[-1]]


def build_argv(
    harness_id: HarnessId,
    *,
    prompt: str,
    model: str | None = None,
    bin_path: str | None = None,
    effort_flags: list[str] | None = None,
    which: Any | None = None,
    cwd: str | None = None,
    disable_web_search: bool = False,
) -> list[str]:
    """Build argv for a direct CLI seat. Raises FileNotFoundError if not installed."""
    hid = (harness_id or "").strip().lower()
    h = registry.get(hid)
    if h is None:
        raise ValueError(f"unknown harness: {harness_id}")
    bin_resolved = bin_path or resolve_bin(hid, which=which)
    if not bin_resolved:
        bins = ", ".join(h.bin_names)
        raise FileNotFoundError(
            f"harness '{hid}' not installed — none of [{bins}] on PATH"
        )
    template = list(_ARGV.get(hid) or ["{bin}", "{prompt}"])
    model_s = (model or "").strip()
    mapping = {
        "bin": bin_resolved,
        "model": model_s or "default",
        "prompt": prompt or "",
    }
    argv = [part.format(**mapping) for part in template]
    # Options before positional prompt: effort, then model, then cwd / web.
    if effort_flags:
        argv = _insert_before_prompt(argv, list(effort_flags))
    # Inject model flags when template has no {model} placeholder but model set
    if model_s and "{model}" not in " ".join(template):
        flags = _MODEL_FLAGS.get(hid) or []
        extra = [f.format(**mapping) for f in flags]
        if extra:
            argv = _insert_before_prompt(argv, extra)
    cwd_s = (cwd or "").strip()
    cwd_flag = _CWD_FLAG.get(hid)
    if cwd_s and cwd_flag:
        argv = _insert_before_prompt(argv, [cwd_flag, cwd_s])
    if disable_web_search and hid in _DISABLE_WEB_SEARCH:
        argv = _insert_before_prompt(argv, ["--disable-web-search"])
    return argv


def list_templates() -> dict[str, list[str]]:
    return {k: list(v) for k, v in _ARGV.items()}


def effort_flags_for(harness_id: HarnessId, settings: dict | None = None) -> list[str]:
    """Map harness settings (e.g. reasoning=low) to CLI flags for direct seats."""
    hid = (harness_id or "").strip().lower()
    s = dict(settings or {})
    flags: list[str] = []
    reasoning = str(s.get("reasoning") or s.get("reasoning_effort") or "").strip().lower()
    if not reasoning:
        return flags
    if hid == "grok":
        # grok CLI: --reasoning-effort low|high|… (also exportable via env)
        flags.extend(["--reasoning-effort", reasoning])
    elif hid == "claude":
        flags.extend(["--thinking", reasoning])
    elif hid == "codex":
        flags.extend(["-c", f"reasoning_effort={reasoning}"])
    else:
        flags.extend(["--reasoning-effort", reasoning])
    return flags
