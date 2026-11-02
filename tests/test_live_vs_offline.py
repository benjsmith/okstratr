"""Live desks use the plan shape only; run_plan / AdaptiveRun stay offline."""

from __future__ import annotations

from pathlib import Path

import pytest

from okstratr import orchestration as orch


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    from okstratr import dag

    dag._DEFAULT = None
    dag._DEFAULT_PATH = None
    return state


@pytest.mark.parametrize("kind", ["auto", "work"])
def test_live_desk_never_runs_the_offline_scheduler(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    from okstratr import dag, desks, herdr

    def boom(*a, **k):
        raise AssertionError("offline scheduler used on a live desk")

    monkeypatch.setattr(orch, "run_plan", boom)
    monkeypatch.setattr(orch, "AdaptiveRun", boom)
    desks.start("Compare the evidence on remote work across sources; which claims disagree and why?", kind=kind)
    g = dag.default_dag(force_reload=True)
    assert len(g.nodes) > 1
    out = herdr.run_ready(limit=1, dry_run=True)
    assert out["dry_run"] is True and out["ran"]


def test_offline_pieces_are_labelled() -> None:
    assert "offline" in (orch.__doc__ or "").lower()
    assert "offline" in (orch.run_plan.__doc__ or "").lower()
    assert "offline" in (orch.AdaptiveRun.__doc__ or "").lower()
    readme = Path(__file__).resolve().parents[1] / "README.md"
    kernel = Path(__file__).resolve().parents[1] / "docs" / "DESK-KERNEL.md"
    assert "Offline only" in readme.read_text(encoding="utf-8")
    assert "Live desks vs offline runs" in kernel.read_text(encoding="utf-8")
