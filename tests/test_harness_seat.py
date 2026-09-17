"""Seating path uses harness registry (not hardcoded grok-only)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    c = tmp_path / "cfg"
    c.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(d))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(c))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    monkeypatch.delenv("OKSTRATR_HERDR_KIND", raising=False)
    import okstratr.blackboard as bb
    import okstratr.dag as dag
    import okstratr.status as status
    from okstratr.harness import select

    bb._DEFAULT = None
    bb._DEFAULT_PATH = None
    dag._DEFAULT = None
    dag._DEFAULT_PATH = None
    status._loaded = False
    status._loaded_from = None
    status._seated_objective = ""
    status._state = "setup"
    select.reset_rr()
    return d


def test_dry_run_shows_chosen_harness(state: Path) -> None:
    from okstratr import dag, herdr
    from okstratr.harness import config as hcfg

    cfg = hcfg.default_config()
    cfg.enabled = ["claude", "grok"]
    cfg.preference = ["claude", "grok"]
    hcfg.save(cfg)

    dag.seat_root("multi harness")
    from okstratr import cos

    cos.break_down("multi harness")
    ready = dag.default_dag().ready()
    assert ready
    node = ready[0]
    out = herdr.run_one(node.id, dry_run=True)
    assert out["ok"] is True
    assert out.get("dry_run") is True
    assert out.get("herdr_kind") == "claude"
    assert out.get("harness_id") == "claude"


def test_multi_harness_round_robin(state: Path) -> None:
    from okstratr.harness import config as hcfg
    from okstratr.harness import select
    from okstratr.harness.types import SeatRequest

    cfg = hcfg.default_config()
    cfg.enabled = ["grok", "claude"]
    cfg.preference = ["grok", "claude"]
    hcfg.save(cfg)

    def which(name: str):
        return f"/x/{name}"

    select.reset_rr()
    a = select.choose_harness(SeatRequest(node_id="a"), which=which, round_robin=True)
    b = select.choose_harness(SeatRequest(node_id="b"), which=which, round_robin=True)
    assert {a.harness_id, b.harness_id} == {"grok", "claude"}


def test_missing_harness_dry_run_fails_clearly(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import dag, herdr
    from okstratr.harness import config as hcfg
    import okstratr.harness.registry as reg

    cfg = hcfg.default_config()
    cfg.enabled = ["codex"]  # only codex
    hcfg.save(cfg)

    # Force require_installed even in dry-run path by patching resolve
    monkeypatch.setattr(
        herdr,
        "resolve_seat_kind",
        lambda **kw: {
            "ok": False,
            "error": "no enabled harness installed. enabled=['codex']; detected={'codex': False}",
        },
    )
    dag.seat_root("fail")
    g = dag.default_dag()
    g.add("w1", "worker", depends_on=["root"], kind="worker")
    g.set_state("root", "done")
    g.refresh_ready()
    out = herdr.run_one("w1", dry_run=True)
    assert out["ok"] is False
    assert "no enabled harness" in (out.get("error") or "")


def test_okstratr_herdr_kind_override(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import dag, herdr
    from okstratr.harness import config as hcfg

    cfg = hcfg.default_config()
    cfg.enabled = ["grok"]
    hcfg.save(cfg)
    monkeypatch.setenv("OKSTRATR_HERDR_KIND", "codex")

    dag.seat_root("override")
    from okstratr import cos

    cos.break_down("override")
    node = dag.default_dag().ready()[0]
    out = herdr.run_one(node.id, dry_run=True)
    assert out["ok"]
    assert out.get("herdr_kind") == "codex"
