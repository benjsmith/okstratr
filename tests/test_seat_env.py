"""Seats never inherit provider API keys from okstratr's environment."""

from __future__ import annotations

from pathlib import Path

import pytest

DUMMY = "dummy-not-a-key"


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
    monkeypatch.delenv("OKSTRATR_SEAT_API_KEYS", raising=False)
    monkeypatch.setenv("XAI_API_KEY", DUMMY)
    monkeypatch.setenv("OPENAI_API_KEY", DUMMY)
    return state


def test_strip_provider_keys_removes_keys_and_keeps_the_rest(env: Path) -> None:
    from okstratr.seat_env import strip_provider_keys

    out = strip_provider_keys({"XAI_API_KEY": DUMMY, "OPENAI_API_KEY": DUMMY, "PATH": "/bin", "HOME": "/h"})
    assert "XAI_API_KEY" not in out and "OPENAI_API_KEY" not in out
    assert out["PATH"] == "/bin" and out["HOME"] == "/h"
    kept = strip_provider_keys({"XAI_API_KEY": DUMMY, "OKSTRATR_SEAT_API_KEYS": "allow"})
    assert kept["XAI_API_KEY"] == DUMMY


def test_direct_seat_process_has_no_provider_keys(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from okstratr.harness.direct import run_direct
    from okstratr.harness.types import SeatRequest, SeatResult

    fake = tmp_path / "bin"
    fake.mkdir()
    script = fake / "grok"
    script.write_text(
        "#!/bin/sh\n"
        'if [ -n "$XAI_API_KEY" ]; then echo HAS_XAI; else echo NO_XAI; fi\n'
        'if [ -n "$OPENAI_API_KEY" ]; then echo HAS_OPENAI; else echo NO_OPENAI; fi\n'
        'echo "node=$OKSTRATR_NODE_ID"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:{tmp_path}")
    seat = SeatResult(ok=True, harness_id="grok", herdr_kind="grok", model="grok-4", adapter="direct")
    out = run_direct(SeatRequest(node_id="n-env", objective="hi"), seat, dry_run=False, timeout=10.0)
    text = out.get("stdout") or ""
    assert out["ok"], out
    assert "NO_XAI" in text and "NO_OPENAI" in text
    assert "HAS_" not in text
    assert "node=n-env" in text
    # An explicit env passed by the caller is stripped too.
    out = run_direct(
        SeatRequest(node_id="n-env2", objective="hi"), seat, dry_run=False, timeout=10.0,
        env={"PATH": f"{fake}:/usr/bin:/bin", "XAI_API_KEY": DUMMY},
    )
    assert "NO_XAI" in (out.get("stdout") or "")


def test_herdr_seat_env_has_no_provider_keys(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import dag, herdr

    seen: list[dict[str, str]] = []

    def fake_cmd(cmd, *, timeout=None, env=None, **_kw):  # noqa: ANN001
        seen.append(dict(env or {}))
        return {"ok": True, "returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(herdr, "_run_cmd", fake_cmd)
    monkeypatch.setattr(herdr, "_split_seat_pane", lambda *a, **k: {"ok": True, "pane_id": "p1"})
    monkeypatch.setattr(herdr, "_stop_agent", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(herdr, "_close_pane", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        herdr, "resolve_seat_kind",
        lambda **k: {"ok": True, "herdr_kind": "grok", "harness_id": "grok", "model": None},
    )
    node = dag.Node(id="n-h", title="t", objective="do it", role="worker")
    herdr._live_run_node(node, bin_path="/bin/true", timeout=5.0)
    assert seen
    for e in seen:
        assert "XAI_API_KEY" not in e and "OPENAI_API_KEY" not in e
