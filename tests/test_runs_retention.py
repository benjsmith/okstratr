"""Run folders (plan.json, evidence.json) follow the blackboard duration."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from okstratr import bb_settings, blackboard, evidence, ops_audit


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    blackboard.invalidate_default()
    monkeypatch.setattr(blackboard, "_RUNS_PRUNED_AT", 0.0)
    return state


def _make_run(rid: str, age_seconds: float = 0.0) -> Path:
    ev = evidence.open_run(rid)
    path = evidence.save_run(ev)
    evidence.write_json(path.parent / "plan.json", {"run_id": rid})
    if age_seconds:
        t = time.time() - age_seconds
        for p in [path.parent, *path.parent.iterdir()]:
            os.utime(p, (t, t))
    return path.parent


def test_default_duration_keeps_recent_runs_and_drops_old_ones() -> None:
    assert bb_settings.duration_days() == pytest.approx(3.0)
    fresh = _make_run("fresh", age_seconds=3600)
    old = _make_run("old", age_seconds=4 * 86400)
    out = evidence.prune_runs()
    assert out == {"removed": 1, "kept": 1}
    assert fresh.is_dir() and not old.exists()
    recs = [r for r in ops_audit.read_records() if r.get("op") == "runs.prune"]
    assert recs and recs[-1]["note"] == "removed=1 kept=1"
    assert ops_audit.verify()["ok"] is True


def test_duration_setting_is_honoured() -> None:
    bb_settings.set_value("duration", "1d")
    a = _make_run("a", age_seconds=2 * 86400)
    b = _make_run("b", age_seconds=600)
    blackboard.prune()
    assert not a.exists() and b.is_dir()


def test_ephemeral_hard_max_sixty_minutes() -> None:
    bb_settings.set_value("duration", "0")
    young = _make_run("young", age_seconds=30 * 60)
    stale = _make_run("stale", age_seconds=61 * 60)
    evidence.prune_runs()
    assert young.is_dir() and not stale.exists()


def test_ephemeral_clears_runs_asap_on_quiet_and_serve_start() -> None:
    bb_settings.set_value("duration", "0")
    r1 = _make_run("r1")
    blackboard.clear_agents_asap()
    assert not r1.exists()
    r2 = _make_run("r2")
    blackboard.on_serve_start()
    assert not r2.exists()


def test_not_ephemeral_quiet_keeps_fresh_runs() -> None:
    r = _make_run("r")
    blackboard.clear_agents_asap()
    blackboard.on_serve_start()
    assert r.is_dir()


def test_bb_clear_clears_runs() -> None:
    _make_run("x")
    _make_run("y")
    out = blackboard.clear()
    assert out["runs"]["removed"] == 2
    assert evidence.list_run_dirs() == []
    assert any(r.get("op") == "runs.clear" for r in ops_audit.read_records())
    assert ops_audit.verify()["ok"] is True


def test_board_reads_age_out_runs() -> None:
    old = _make_run("old", age_seconds=5 * 86400)
    blackboard.post("hello", author="human")
    blackboard.default_blackboard(force_reload=True).head(1)
    assert not old.exists()


def test_run_files_have_visible_names(tmp_path: Path) -> None:
    d = _make_run("vis")
    names = [p.name for p in d.rglob("*")]
    assert sorted(names) == ["evidence.json", "plan.json"]
    assert evidence.safe_run_id(".hidden") == "hidden"
    assert evidence.safe_run_id("..") == "run"
    assert evidence.safe_run_id("a/../b") == "a-..-b"
    assert not evidence.safe_run_id("x\u202e").endswith("\u202e")


def test_atomic_temp_name_is_visible(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[str] = []
    real = Path.write_text

    def spy(self: Path, *a, **k):
        seen.append(self.name)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", spy)
    evidence.write_json(tmp_path / "plan.json", {})
    from okstratr import orchestration as orch

    orch.save_checkpoint(tmp_path / "state.json", orch.RunState(plan=orch.plan_single("x")))
    assert seen and not any(n.startswith(".") for n in seen)
