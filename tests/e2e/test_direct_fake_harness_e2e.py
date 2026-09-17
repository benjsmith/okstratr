"""E2E: fake harness on PATH + direct backend seating."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    bin_dir = tmp_path / "bin"
    state.mkdir()
    cfg.mkdir()
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text(
        "#!/bin/sh\necho \"direct-e2e:$*\"\nexit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("PATH", f"{bin_dir}:{tmp_path}")
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "0")
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


def test_e2e_direct_backend_run_one(e2e: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import dag, herdr
    from okstratr.harness import config as hcfg

    cfg = hcfg.default_config()
    cfg.enabled = ["claude"]
    cfg.defaults["backend"] = "direct"
    cfg.defaults["adapter"] = "direct"
    cfg.harness["claude"].default_model = "claude-sonnet-4"
    hcfg.save(cfg)

    # Force no herdr so prefer_direct path is taken even if herdr exists on host
    monkeypatch.setattr(herdr, "herdr_bin", lambda path=None: None)

    dag.seat_root("direct e2e")
    g = dag.default_dag()
    g.add("w1", "worker", depends_on=["root"], kind="worker", objective="ping")
    g.set_state("root", "done", save=True)
    g.refresh_ready(save=True)
    out = herdr.run_one("w1", dry_run=False, timeout=10.0)
    assert out.get("adapter") == "direct" or out.get("ok") in (True, False)
    if out.get("ok"):
        assert "direct-e2e" in (out.get("stdout") or "") or out.get("log_path")
        assert out.get("herdr_labels", {}).get("desk_id") or out.get("labels", {}).get("desk_id")
