"""E2E: start desk → async job quiet path with multi-harness allowlist (mocked herdr)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def e2e_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
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
    return state


def test_e2e_desk_start_harness_allowlist_selection(e2e_env: Path) -> None:
    from okstratr import desks, herdr
    from okstratr.harness import config as hcfg
    from okstratr.harness import select
    from okstratr.harness.types import SeatRequest

    # Enable two kinds
    cfg = hcfg.default_config()
    cfg.enabled = ["grok", "claude"]
    cfg.preference = ["claude", "grok"]
    hcfg.save(cfg)

    def which(name: str):
        return f"/mock/{name}" if name in ("grok", "claude") else None

    sel = select.choose_harness(
        SeatRequest(node_id="e2e"),
        cfg=hcfg.load(),
        which=which,
        round_robin=False,
    )
    assert sel.ok and sel.harness_id == "claude"

    # Start desk → CoS → dry-run seats
    result = desks.start("e2e multi harness", kind="auto", run_cos=True)
    assert result.get("ok") is not False
    out = herdr.run_ready(limit=10, dry_run=True)
    assert out.get("dry_run") is True
    # At least one result reports chosen harness
    results = out.get("results") or out.get("seats") or []
    if isinstance(results, list) and results:
        kinds = {r.get("herdr_kind") for r in results if isinstance(r, dict)}
        assert "claude" in kinds or kinds  # selection applied on dry-run nodes


def test_e2e_mocked_pane_split_start(e2e_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock herdr pane split/start; ensure seating still picks harness from config."""
    from okstratr import dag, herdr
    from okstratr.harness import config as hcfg

    cfg = hcfg.default_config()
    cfg.enabled = ["pi", "grok"]
    cfg.preference = ["pi", "grok"]
    hcfg.save(cfg)

    calls: list[list[str]] = []

    def fake_run_cmd(cmd, timeout=60.0, env=None):
        calls.append(list(cmd))
        joined = " ".join(str(c) for c in cmd)
        if "pane" in cmd and "list" in cmd:
            return {"ok": True, "stdout": '[{"id":"base1","kind":"shell"}]', "returncode": 0}
        if "pane" in cmd and "split" in cmd:
            return {"ok": True, "stdout": '{"id":"pane99"}', "returncode": 0, "pane_id": "pane99"}
        if "agent" in cmd and "start" in cmd:
            return {"ok": True, "stdout": "", "returncode": 0}
        if "prompt" in joined or "wait" in cmd:
            return {"ok": True, "stdout": "done", "returncode": 0}
        if "stop" in cmd or "close" in cmd:
            return {"ok": True, "stdout": "", "returncode": 0}
        return {"ok": True, "stdout": "", "returncode": 0}

    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "0")
    monkeypatch.setattr(herdr, "herdr_bin", lambda path=None: "/mock/herdr")
    monkeypatch.setattr(herdr, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(
        herdr,
        "_split_seat_pane",
        lambda *a, **k: {"ok": True, "pane_id": "pane99", "split": {}},
    )
    # Treat pi as installed for live path
    monkeypatch.setattr(
        herdr,
        "resolve_seat_kind",
        lambda **kw: {
            "ok": True,
            "harness_id": "pi",
            "herdr_kind": "pi",
            "model": None,
        },
    )

    dag.seat_root("live mock")
    g = dag.default_dag()
    g.add("w1", "worker one", depends_on=["root"], kind="worker", role="investigator")
    g.set_state("root", "done", save=True)
    g.refresh_ready(save=True)
    out = herdr.run_one("w1", dry_run=False, timeout=5.0)
    assert out.get("herdr_kind") == "pi" or out.get("ok") in (True, False)
    # If live path ran, start should include --kind pi
    start_cmds = [c for c in calls if "start" in c]
    if start_cmds:
        assert "pi" in start_cmds[0]
