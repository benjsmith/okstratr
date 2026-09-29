"""Per-harness argv templates for the direct CLI adapter."""

from __future__ import annotations

from typing import Any

from . import registry
from .types import HarnessId

# Templates: {bin}, {model}, {prompt}, {prompt_file}
# grok non-TTY: positional / TTY prompt path fails with
# "Device not configured (os error 6)". Use --prompt-file +
# --output-format plain + --always-approve instead.
# Options (--model, --reasoning-effort, --cwd, --disable-web-search) must
# appear before --prompt-file / positional prompt.

_ARGV: dict[HarnessId, list[str]] = {
    "grok": [
        "{bin}",
        "--output-format",
        "plain",
        "--always-approve",
        "--prompt-file",
        "{prompt_file}",
    ],
    "claude": ["{bin}", "--print", "--model", "{model}", "{prompt}"],
    "codex": ["{bin}", "exec", "--model", "{model}", "{prompt}"],
    # Direct seats are non-interactive: -p/--print. Provider defaults to google in
    # pi unless --provider or provider/model is set — that caused azure-openai
    # "No API key" when OPENAI_API_KEY was present but argv omitted provider.
    "pi": ["{bin}", "-p", "{prompt}"],
    "omp": ["{bin}", "run", "--prompt", "{prompt}"],
    "opencode": ["{bin}", "run", "{prompt}"],
    "cursor": ["{bin}", "agent", "--print", "{prompt}"],
}

# Model-id → pi --provider when settings/env omit it (API-key providers).
_PI_MODEL_PROVIDER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("chatgpt-", "openai"),
    ("claude-", "anthropic"),
    ("haiku", "anthropic"),
    ("sonnet", "anthropic"),
    ("opus", "anthropic"),
    ("gemini", "google"),
    ("grok-", "xai"),
    ("deepseek", "deepseek"),
    ("mistral", "mistral"),
    ("llama", "groq"),
)

# Env vars that imply a default pi provider when set (first match wins).
_PI_PROVIDER_ENV: tuple[tuple[str, str], ...] = (
    ("OPENAI_API_KEY", "openai"),
    ("ANTHROPIC_API_KEY", "anthropic"),
    ("XAI_API_KEY", "xai"),
    ("GEMINI_API_KEY", "google"),
    ("DEEPSEEK_API_KEY", "deepseek"),
    ("MISTRAL_API_KEY", "mistral"),
    ("GROQ_API_KEY", "groq"),
    ("OPENROUTER_API_KEY", "openrouter"),
)

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

# Harnesses that require a prompt file (not bare positional) for non-TTY seats.
_PROMPT_FILE_HARNESSES: frozenset[HarnessId] = frozenset({"grok"})


def uses_prompt_file(harness_id: HarnessId) -> bool:
    """True when direct seats must write a --prompt-file instead of positional."""
    return (harness_id or "").strip().lower() in _PROMPT_FILE_HARNESSES


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
    """Insert option flags before --prompt-file (and path) or final positional prompt."""
    if not extra:
        return argv
    if len(argv) <= 1:
        return argv + list(extra)
    # Prefer inserting before --prompt-file <path> pair.
    try:
        idx = argv.index("--prompt-file")
        return argv[:idx] + list(extra) + argv[idx:]
    except ValueError:
        pass
    # Convention: last element is the prompt for templates that end with {prompt}.
    return argv[:-1] + list(extra) + [argv[-1]]



def parse_provider_model(model: str | None) -> tuple[str | None, str | None]:
    """Split ``provider/model`` (optional ``:thinking``) → (provider, model_id)."""
    raw = (model or "").strip()
    if not raw:
        return None, None
    # Drop optional thinking suffix used by pi (provider/id:high)
    if ":" in raw and "/" in raw.split(":", 1)[0]:
        raw = raw.split(":", 1)[0]
    if "/" in raw:
        prov, mid = raw.split("/", 1)
        prov, mid = prov.strip().lower(), mid.strip()
        if prov and mid:
            return prov, mid
    return None, raw


def infer_pi_provider(
    *,
    model: str | None = None,
    provider: str | None = None,
    settings: dict | None = None,
    env: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """Resolve (provider, model_id) for pi direct seats.

    Order: explicit provider → model ``provider/id`` slash → settings.provider
    → OKSTRATR_PI_PROVIDER / PI_PROVIDER → model-id heuristics → first set
    API-key env among known providers.

    Slash models (``xai/grok-4``) must beat a harness default like
    ``provider=openai`` so multi-provider pi desks work on one install.
    """
    import os

    environ = env if env is not None else os.environ
    settings = dict(settings or {})
    mid = (model or "").strip() or None
    prov = (provider or "").strip().lower() or None
    slash_p, slash_m = parse_provider_model(mid)
    if slash_p:
        # Explicit provider/model in the model id wins over harness defaults.
        if not prov:
            prov = slash_p
        mid = slash_m or mid
        # When caller did not pass an explicit provider kwarg, slash still
        # overrides settings.provider (checked below only if prov empty).
        if provider is None or not str(provider).strip():
            prov = slash_p
    if not prov:
        sp = settings.get("provider") or settings.get("pi_provider")
        if sp:
            prov = str(sp).strip().lower() or None
    if not prov:
        for key in ("OKSTRATR_PI_PROVIDER", "PI_PROVIDER"):
            v = (environ.get(key) or "").strip().lower()
            if v:
                prov = v
                break
    if not prov and mid:
        low = mid.lower()
        for prefix, p in _PI_MODEL_PROVIDER_PREFIXES:
            if low.startswith(prefix) or prefix in low:
                prov = p
                break
    if not prov:
        for env_key, p in _PI_PROVIDER_ENV:
            if (environ.get(env_key) or "").strip():
                prov = p
                break
    return prov, mid


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
    prompt_file: str | None = None,
    provider: str | None = None,
    settings: dict | None = None,
) -> list[str]:
    """Build argv for a direct CLI seat. Raises FileNotFoundError if not installed.

    For grok, pass ``prompt_file`` (path written by the direct adapter). A bare
    positional prompt is not used for non-TTY direct seats.
    """
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
    if uses_prompt_file(hid) and not (prompt_file or "").strip():
        raise ValueError(
            f"harness '{hid}' requires prompt_file for direct seats "
            "(positional prompt fails non-TTY: Device not configured)"
        )
    template = list(_ARGV.get(hid) or ["{bin}", "{prompt}"])
    model_s = (model or "").strip()
    provider_s = (provider or "").strip().lower()
    if hid == "pi":
        provider_s, model_s = infer_pi_provider(
            model=model_s or None,
            provider=provider_s or None,
            settings=settings,
        )
        model_s = (model_s or "").strip()
        provider_s = (provider_s or "").strip().lower()
    mapping = {
        "bin": bin_resolved,
        "model": model_s or "default",
        "prompt": prompt or "",
        "prompt_file": (prompt_file or "").strip(),
        "provider": provider_s or "",
    }
    argv = [part.format(**mapping) for part in template]
    # Options before prompt-file / positional: effort, then model, then cwd / web.
    if effort_flags:
        argv = _insert_before_prompt(argv, list(effort_flags))
    # Inject model flags when template has no {model} placeholder but model set
    if model_s and "{model}" not in " ".join(template):
        flags = _MODEL_FLAGS.get(hid) or []
        extra = [f.format(**mapping) for f in flags]
        if extra:
            argv = _insert_before_prompt(argv, extra)
    # pi: inject --provider when resolved (unless already in template)
    if hid == "pi" and provider_s and "--provider" not in argv:
        argv = _insert_before_prompt(argv, ["--provider", provider_s])
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
