"""Unit tests for direct CLI adapter (mocked subprocess)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("OKSTRATR_HERDR_DRY_RUN", raising=False)
    monkeypatch.delenv("OKSTRATR_DIRECT_DRY_RUN", raising=False)
    return state


def test_build_argv_claude() -> None:
    from okstratr.harness import argv as argv_mod

    cmd = argv_mod.build_argv(
        "claude",
        prompt="hello",
        model="claude-sonnet-4",
        which=lambda n: f"/bin/{n}" if n == "claude" else None,
    )
    assert cmd[0] == "/bin/claude"
    assert "claude-sonnet-4" in cmd
    assert "hello" in cmd


def test_build_argv_not_installed() -> None:
    from okstratr.harness import argv as argv_mod

    with pytest.raises(FileNotFoundError, match="not installed"):
        argv_mod.build_argv("omp", prompt="x", which=lambda _n: None)


def test_dry_run_stub(env: Path) -> None:
    from okstratr.harness.direct import run_direct
    from okstratr.harness.types import SeatRequest, SeatResult

    seat = SeatResult(ok=True, harness_id="grok", herdr_kind="grok", model="grok-4", adapter="direct")
    req = SeatRequest(node_id="n1", objective="do it", desk_id="d1", thread_id="t1")
    out = run_direct(req, seat, dry_run=True)
    assert out["ok"] and out["dry_run"]
    assert out["labels"]["desk_id"] == "d1"
    assert out["harness_id"] == "grok"


def test_spawn_fake_harness(env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """e2e-ish: fake harness script on PATH."""
    from okstratr.harness.direct import run_direct
    from okstratr.harness.types import SeatRequest, SeatResult

    fake = tmp_path / "bin"
    fake.mkdir()
    script = fake / "grok"
    script.write_text("#!/bin/sh\necho fake-grok-ok\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:{tmp_path}")

    seat = SeatResult(ok=True, harness_id="grok", herdr_kind="grok", model="grok-4", adapter="direct")
    req = SeatRequest(node_id="n2", objective="hi", desk_id="deskA", thread_id="thA")
    out = run_direct(req, seat, dry_run=False, timeout=10.0)
    assert out["ok"] is True
    assert out["adapter"] == "direct"
    assert out["labels"]["desk_id"] == "deskA"
    assert "fake-grok-ok" in (out.get("stdout") or "")
    assert out.get("log_path")


def test_kill_on_desk(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr.harness import procs
    from okstratr.harness.direct import kill_direct_for_desk

    # Register a fake dead pid
    procs.register(
        procs.ProcRecord(pid=1, harness_id="grok", node_id="n", desk_id="d9", thread_id="t9")
    )
    out = kill_direct_for_desk("d9")
    assert out["ok"]
    assert out["count"] >= 1
