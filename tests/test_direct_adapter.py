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


def test_build_argv_grok_positional_no_prompt_flag() -> None:
    """grok CLI rejects --prompt; prompt must be positional after options."""
    from okstratr.harness import argv as argv_mod

    cmd = argv_mod.build_argv(
        "grok",
        prompt="do the thing",
        model="grok-4.6",
        effort_flags=["--reasoning-effort", "low"],
        which=lambda n: f"/bin/{n}" if n == "grok" else None,
        cwd="/tmp/ws",
        disable_web_search=True,
    )
    assert cmd[0] == "/bin/grok"
    assert "--prompt" not in cmd
    assert cmd[-1] == "do the thing"
    # options before positional prompt
    assert "--model" in cmd and "grok-4.6" in cmd
    assert cmd[cmd.index("--model") + 1] == "grok-4.6"
    assert "--reasoning-effort" in cmd and "low" in cmd
    assert cmd[cmd.index("--reasoning-effort") + 1] == "low"
    assert "--cwd" in cmd and cmd[cmd.index("--cwd") + 1] == "/tmp/ws"
    assert "--disable-web-search" in cmd
    # effort before model (stable option order)
    assert cmd.index("--reasoning-effort") < cmd.index("--model") < cmd.index("--cwd")
    assert cmd.index("--cwd") < cmd.index("--disable-web-search") < len(cmd) - 1


def test_build_argv_grok_web_on_skips_disable() -> None:
    from okstratr.harness import argv as argv_mod

    cmd = argv_mod.build_argv(
        "grok",
        prompt="hi",
        model="grok-4",
        which=lambda n: "/usr/bin/grok" if n == "grok" else None,
        disable_web_search=False,
    )
    assert "--disable-web-search" not in cmd
    assert cmd[-1] == "hi"
    assert "--prompt" not in cmd


def test_spawn_fake_grok_records_positional_argv(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """e2e: fake grok records argv; must not see --prompt."""
    from okstratr.harness.direct import run_direct
    from okstratr.harness.types import SeatRequest, SeatResult
    from okstratr import web_egress

    fake = tmp_path / "bin"
    fake.mkdir()
    argv_log = tmp_path / "grok-argv.txt"
    script = fake / "grok"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{argv_log}"\n'
        "echo fake-grok-positional-ok\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:{tmp_path}")

    web_egress.set_mode("off")

    seat = SeatResult(
        ok=True, harness_id="grok", herdr_kind="grok", model="grok-4.6", adapter="direct"
    )
    req = SeatRequest(
        node_id="n-pos", objective="seat objective", desk_id="deskP", thread_id="thP"
    )
    out = run_direct(
        req,
        seat,
        dry_run=False,
        timeout=10.0,
        effort_flags=["--reasoning-effort", "low"],
    )
    assert out["ok"] is True
    assert "fake-grok-positional-ok" in (out.get("stdout") or "")
    recorded = argv_log.read_text(encoding="utf-8").splitlines()
    assert "--prompt" not in recorded
    assert recorded[-1] == "seat objective"
    assert "--model" in recorded and "grok-4.6" in recorded
    assert "--reasoning-effort" in recorded and "low" in recorded
    assert "--disable-web-search" in recorded
