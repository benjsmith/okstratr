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
    would = (out.get("would_exec") or [{}])[0]
    argv = would.get("argv") or []
    assert "--prompt-file" in argv
    assert "--output-format" in argv and "plain" in argv
    assert "--always-approve" in argv
    assert would.get("prompt_file")


def test_spawn_fake_harness(env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """e2e-ish: fake harness script on PATH."""
    from okstratr.harness.direct import run_direct
    from okstratr.harness.types import SeatRequest, SeatResult

    fake = tmp_path / "bin"
    fake.mkdir()
    script = fake / "grok"
    script.write_text(
        "#!/bin/sh\n"
        "# read --prompt-file if present\n"
        "while [ $# -gt 0 ]; do\n"
        '  if [ "$1" = "--prompt-file" ]; then shift; cat "$1"; shift; continue; fi\n'
        "  shift\n"
        "done\n"
        "echo fake-grok-ok\n"
        "exit 0\n",
        encoding="utf-8",
    )
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
    assert "--prompt-file" in (out.get("argv") or [])


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


def test_build_argv_grok_prompt_file_shape() -> None:
    """grok direct seats use --prompt-file (not positional / not --prompt)."""
    from okstratr.harness import argv as argv_mod

    cmd = argv_mod.build_argv(
        "grok",
        prompt="ignored-when-file",
        prompt_file="/tmp/ws/prompt.txt",
        model="grok-4.6",
        effort_flags=["--reasoning-effort", "low"],
        which=lambda n: f"/bin/{n}" if n == "grok" else None,
        cwd="/tmp/ws",
        disable_web_search=True,
    )
    assert cmd[0] == "/bin/grok"
    assert "--prompt" not in cmd
    assert "ignored-when-file" not in cmd
    assert "--prompt-file" in cmd
    assert cmd[cmd.index("--prompt-file") + 1] == "/tmp/ws/prompt.txt"
    assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "plain"
    assert "--always-approve" in cmd
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "grok-4.6"
    assert "--reasoning-effort" in cmd and cmd[cmd.index("--reasoning-effort") + 1] == "low"
    assert "--cwd" in cmd and cmd[cmd.index("--cwd") + 1] == "/tmp/ws"
    assert "--disable-web-search" in cmd
    # options before --prompt-file
    assert cmd.index("--reasoning-effort") < cmd.index("--model") < cmd.index("--cwd")
    assert cmd.index("--cwd") < cmd.index("--disable-web-search") < cmd.index("--prompt-file")
    # plain/always-approve present before prompt-file
    assert cmd.index("--output-format") < cmd.index("--prompt-file")
    assert cmd.index("--always-approve") < cmd.index("--prompt-file")


def test_build_argv_grok_requires_prompt_file() -> None:
    from okstratr.harness import argv as argv_mod

    with pytest.raises(ValueError, match="prompt_file"):
        argv_mod.build_argv(
            "grok",
            prompt="hi",
            which=lambda n: "/usr/bin/grok" if n == "grok" else None,
        )


def test_build_argv_grok_web_on_skips_disable() -> None:
    from okstratr.harness import argv as argv_mod

    cmd = argv_mod.build_argv(
        "grok",
        prompt="hi",
        prompt_file="/tmp/p.txt",
        model="grok-4",
        which=lambda n: "/usr/bin/grok" if n == "grok" else None,
        disable_web_search=False,
    )
    assert "--disable-web-search" not in cmd
    assert "--prompt-file" in cmd
    assert "--prompt" not in cmd


def test_spawn_fake_grok_prompt_file(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """e2e: fake grok records argv; must use --prompt-file with prompt contents."""
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
        "echo fake-grok-prompt-file-ok\n"
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
    assert "fake-grok-prompt-file-ok" in (out.get("stdout") or "")
    recorded = argv_log.read_text(encoding="utf-8").splitlines()
    assert "--prompt" not in recorded
    assert "seat objective" not in recorded  # content is in the file, not argv
    assert "--prompt-file" in recorded
    pf = recorded[recorded.index("--prompt-file") + 1]
    assert Path(pf).is_file()
    assert Path(pf).read_text(encoding="utf-8") == "seat objective"
    assert "--output-format" in recorded and "plain" in recorded
    assert "--always-approve" in recorded
    assert "--model" in recorded and "grok-4.6" in recorded
    assert "--reasoning-effort" in recorded and "low" in recorded
    assert "--disable-web-search" in recorded
