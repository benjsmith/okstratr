"""Pick harness + model for a seat (preference + allowlist + rung)."""

from __future__ import annotations

from typing import Callable

from . import config as harness_config
from . import registry
from . import rungs
from .types import HarnessId, SeatRequest, SeatResult

# Simple process-local round-robin cursor.
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
      1. OKSTRATR_HERDR_KIND env override — handled in resolve_herdr_kind
      2. req.prefer_harness if enabled (+ installed)
      3. role_harness mapping
      4. preference_order ∩ enabled ∩ installed (round-robin among candidates)

    Model selection: prefer_model → effort/rung map → default_model → pool[0].
    """
    global _rr_cursor
    cfg = cfg or harness_config.load()
    req = req or SeatRequest(node_id="?")

    prefer = (req.prefer_harness or "").strip().lower() or None
    if not prefer and req.role:
        prefer = (cfg.role_harness.get(req.role) or "").strip().lower() or None

    candidates = cfg.preference_order()
    if prefer and prefer in candidates:
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

    backend = cfg.preferred_backend()
    # Direct adapter requires install; Herdr may fall back to enabled-only
    strict = require_installed or backend == "direct"
    pool = installed_ok if installed_ok else ([] if strict else enabled_ok)

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
            detail={"enabled": enabled, "detected": detected, "backend": backend},
            adapter=backend,
        )

    if round_robin and len(pool) > 1 and not prefer:
        idx = _rr_cursor % len(pool)
        _rr_cursor += 1
        chosen = pool[idx]
    else:
        chosen = pool[0]

    hdef = registry.get(chosen)
    assert hdef is not None
    models = [m.id for m in cfg.models_for(chosen)]
    model, model_detail = rungs.resolve_model_for_rung(
        models=models,
        default_model=cfg.default_model_for(chosen),
        effort_map=cfg.effort_map_for(chosen),
        rung=req.rung,
        effort=req.effort,
        prefer_model=req.prefer_model,
    )

    labels = {
        "desk_id": req.desk_id,
        "thread_id": req.thread_id or (f"thread-{req.desk_id}" if req.desk_id else None),
        "role": req.role,
        "node_id": req.node_id,
        "harness_id": chosen,
        "model": model,
    }

    return SeatResult(
        ok=True,
        harness_id=chosen,
        herdr_kind=hdef.herdr_kind,
        model=model,
        adapter=backend,
        detail={
            "candidates": pool,
            "installed": installed_ok,
            "enabled_fallback": not bool(installed_ok),
            "label": hdef.label,
            "model_select": model_detail,
            "rung": model_detail.get("rung"),
            "backend": backend,
        },
        labels={k: v for k, v in labels.items() if v is not None},
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
        h = registry.get(override) or next(
            (d for d in registry.list_defs() if d.herdr_kind == override),
            None,
        )
        return SeatResult(
            ok=True,
            harness_id=h.id if h else override,
            herdr_kind=h.herdr_kind if h else override,
            model=(req.prefer_model if req else None),
            adapter="herdr",
            detail={"source": "OKSTRATR_HERDR_KIND"},
            labels={
                "desk_id": req.desk_id if req else None,
                "thread_id": req.thread_id if req else None,
                "node_id": req.node_id if req else None,
            },
        )
    return choose_harness(
        req, cfg=cfg, which=which, require_installed=require_installed
    )


def list_models(cfg: harness_config.HarnessConfig | None = None) -> list[dict]:
    """Flatten enabled harness → models for ``okstratr model list``."""
    cfg = cfg or harness_config.load()
    rows: list[dict] = []
    for hid in cfg.preference_order():
        s = cfg.settings_for(hid)
        mods = s.models or [m.id for m in cfg.models_for(hid)]
        rows.append(
            {
                "harness": hid,
                "enabled": cfg.is_enabled(hid),
                "default_model": s.default_model or cfg.default_model_for(hid),
                "models": list(mods),
                "effort": dict(s.effort or {}),
            }
        )
    return rows
