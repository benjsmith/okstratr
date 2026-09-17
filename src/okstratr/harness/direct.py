"""Direct CLI harness adapter stub (no Herdr) — Phase 1 dry-run only."""

from __future__ import annotations

from typing import Any

from .types import SeatRequest, SeatResult


def run_direct_stub(
    req: SeatRequest,
    seat: SeatResult,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Phase 1: record what a subprocess adapter would do; do not exec.

    Real direct adapters land in P2. This keeps the seating path
    harness-agnostic when Herdr is absent.
    """
    if not seat.ok:
        return {
            "ok": False,
            "adapter": "direct",
            "dry_run": dry_run,
            "error": seat.error or "harness selection failed",
            "seat": seat.to_dict(),
        }
    would = [
        {
            "argv": [seat.harness_id or "?", "--model", seat.model or "default"],
            "cwd": None,
            "prompt": req.objective or req.node_id,
            "note": "P1 stub — no subprocess",
        }
    ]
    return {
        "ok": True,
        "adapter": "direct",
        "dry_run": True,
        "harness_id": seat.harness_id,
        "herdr_kind": seat.herdr_kind,
        "model": seat.model,
        "would_exec": would,
        "message": f"direct-adapter dry-run stub for {req.node_id}",
        "seat": seat.to_dict(),
    }
