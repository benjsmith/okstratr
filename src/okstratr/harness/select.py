"""Pick harness + model for a seat (P1: preference order / round-robin)."""

from __future__ import annotations

from typing import Callable

from . import config as harness_config
from . import registry
from .types import HarnessId, SeatRequest, SeatResult

# Simple process-local round-robin cursor (P1).
_rr_cursor = 0


def reset_rr() -> None:
    global _rr_cursor
    _rr_cursor = 0


def choose_harness(
    req: SeatRequest | None = None,
    *,
    cfg: harness_config.HarnessConfig | None = None,
    which: Callable[[str], str | None] | None = None,
    require_installed: bool = True,
    round_robin: bool = True,
) -> SeatResult:
    """Select an enabled harness (and model) for seating.

    Order of preference:
      1. OKSTRATR_HERDR_KIND env override (caller maps to harness) — handled in resolve_kind
      2. req.prefer_harness if enabled (+ installed)
      3. role_harness mapping
      4. preference_order ∩ enabled ∩ installed (round-robin among candidates)
    """
    global _rr_cursor
    cfg = cfg or harness_config.load()
    req = req or SeatRequest(node_id="?")

    prefer = (req.prefer_harness or "").strip().lower() or None
    if not prefer and req.role:
        prefer = (cfg.role_harness.get(req.role) or "").strip().lower() or None

    candidates = cfg.preference_order()
    if prefer and prefer in candidates:
        # Move preferred to front for this seat
        candidates = [prefer] + [c for c in candidates if c != prefer]

    enabled_ok: list[HarnessId] = []
    installed_ok: list[HarnessId] = []
    for hid in candidates:
        if not cfg.is_enabled(hid):
            continue
        if registry.get(hid) is None:
            continue
        enabled_ok.append(hid)
        if registry.detect_installed(hid, which=which):
            installed_ok.append(hid)

    # Prefer enabled∩installed. For Herdr adapter, fall back to enabled-only
    # (Herdr can seat a --kind without a standalone CLI on PATH). Strict
    # require_installed=True fails clearly when nothing is installed.
    pool = installed_ok if installed_ok else ([] if require_installed else enabled_ok)

    if not pool:
        enabled = cfg.preference_order()
        detected = registry.detect_all(which=which)
        return SeatResult(
            ok=False,
            error=(
                "no enabled harness installed. "
                f"enabled={enabled}; detected={detected}. "
                "Install a harness CLI or `okstratr harness enable …` / "
                "adjust ~/.config/okstratr/harnesses.toml"
            ),
            detail={"enabled": enabled, "detected": detected},
        )

    if round_robin and len(pool) > 1 and not prefer:
        idx = _rr_cursor % len(pool)
        _rr_cursor += 1
        chosen = pool[idx]
    else:
        chosen = pool[0]

    hdef = registry.get(chosen)
    assert hdef is not None
    models = cfg.models_for(chosen)
    model = req.prefer_model
    if not model and models:
        model = models[0].id

    return SeatResult(
        ok=True,
        harness_id=chosen,
        herdr_kind=hdef.herdr_kind,
        model=model,
        adapter=str(cfg.defaults.get("adapter") or "herdr"),
        detail={
            "candidates": pool, "installed": installed_ok, "enabled_fallback": not bool(installed_ok),
            "label": hdef.label,
        },
    )


def resolve_herdr_kind(
    *,
    env_override: str | None = None,
    req: SeatRequest | None = None,
    cfg: harness_config.HarnessConfig | None = None,
    which: Callable[[str], str | None] | None = None,
    require_installed: bool = True,
) -> SeatResult:
    """Resolve Herdr --kind for a seat.

    ``OKSTRATR_HERDR_KIND`` (env_override) still wins when set.
    Otherwise select from harness config allowlist.
    """
    override = (env_override or "").strip()
    if override:
        # Map override to harness if known; otherwise pass through as herdr_kind
        h = registry.get(override) or next(
            (d for d in registry.list_defs() if d.herdr_kind == override),
            None,
        )
        return SeatResult(
            ok=True,
            harness_id=h.id if h else override,
            herdr_kind=h.herdr_kind if h else override,
            model=None,
            adapter="herdr",
            detail={"source": "OKSTRATR_HERDR_KIND"},
        )
    return choose_harness(
        req, cfg=cfg, which=which, require_installed=require_installed
    )
