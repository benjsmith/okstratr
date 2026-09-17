"""CoS multi-harness investigator fan-out."""

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
    monkeypatch.delenv("OKSTRATR_HARNESS_PREFER", raising=False)
    monkeypatch.delenv("OKSTRATR_MODEL_BY_HARNESS", raising=False)
    monkeypatch.delenv("OKSTRATR_MODEL", raising=False)
    monkeypatch.delenv("OKSTRATR_HERDR_KIND", raising=False)
    return state


def test_switchbay_fanout_two_harnesses(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import cos
    from okstratr.harness import config as hcfg

    cfg = hcfg.default_config()
    cfg.enabled = ["grok", "claude"]
    cfg.preference = ["grok", "claude"]
    hcfg.save(cfg)

    monkeypatch.setenv("OKSTRATR_HARNESS_PREFER", "grok,claude")
    monkeypatch.setenv("OKSTRATR_MODEL_BY_HARNESS", "grok:grok-4.6,claude:haiku")

    steps = cos.switchbay_steps()
    ids = [cos._unpack_step(s)[0] for s in steps]
    assert ids[0] == "investigator-grok"
    assert ids[1] == "investigator-claude"
    assert "investigator" not in ids
    assert "synthesizer" in ids
    g_step = cos._unpack_step(steps[0])
    c_step = cos._unpack_step(steps[1])
    assert g_step[5] == "grok" and g_step[6] == "grok-4.6"
    assert c_step[5] == "claude" and c_step[6] == "haiku"
    syn = cos._unpack_step([s for s in steps if cos._unpack_step(s)[0] == "synthesizer"][0])
    assert syn[3] == ["investigator-grok", "investigator-claude"]


def test_switchbay_single_when_one_enabled(env: Path) -> None:
    from okstratr import cos
    from okstratr.harness import config as hcfg

    cfg = hcfg.default_config()
    cfg.enabled = ["grok"]
    cfg.preference = ["grok"]
    hcfg.save(cfg)

    steps = cos.switchbay_steps()
    ids = [cos._unpack_step(s)[0] for s in steps]
    assert ids == ["investigator", "synthesizer", "verifier"]


def test_break_down_persists_prefer(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import cos, dag
    from okstratr.harness import config as hcfg

    cfg = hcfg.default_config()
    cfg.enabled = ["grok", "claude"]
    hcfg.save(cfg)
    monkeypatch.setenv("OKSTRATR_HARNESS_PREFER", "grok,claude")
    monkeypatch.setenv("OKSTRATR_MODEL_BY_HARNESS", "grok:grok-4.6,claude:haiku")

    out = cos.break_down("dual brief", kind="work")
    assert out["ok"]
    g = dag.default_dag(force_reload=True)
    assert "investigator-grok" in g.nodes
    assert "investigator-claude" in g.nodes
    assert g.nodes["investigator-grok"].prefer_harness == "grok"
    assert g.nodes["investigator-grok"].prefer_model == "grok-4.6"
    assert g.nodes["investigator-claude"].prefer_harness == "claude"
    assert g.nodes["investigator-claude"].prefer_model == "haiku"
    assert g.nodes["synthesizer"].depends_on == [
        "investigator-grok",
        "investigator-claude",
    ]
    # both ready after root done
    ready = {n.id for n in g.ready()}
    assert "investigator-grok" in ready
    assert "investigator-claude" in ready


def test_slash_multi_model_map() -> None:
    from okstratr.harness.slash import apply_harness_slash_to_env, parse_slash_directives

    d = parse_slash_directives(
        "/harness grok,claude /model grok:grok-4.6,claude:haiku dual investigators please"
    )
    assert d.harnesses == ["grok", "claude"]
    assert d.models_by_harness == {"grok": "grok-4.6", "claude": "haiku"}
    assert d.objective == "dual investigators please"
    env = apply_harness_slash_to_env(d)
    assert env["OKSTRATR_HARNESS_PREFER"] == "grok,claude"
    assert "grok:grok-4.6" in env["OKSTRATR_MODEL_BY_HARNESS"]
    assert "claude:haiku" in env["OKSTRATR_MODEL_BY_HARNESS"]


def test_node_seat_prefs_pin(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import dag, herdr

    monkeypatch.setenv("OKSTRATR_HARNESS_PREFER", "grok,claude")
    monkeypatch.setenv("OKSTRATR_MODEL", "should-not-win")
    n = dag.Node(
        id="investigator-claude",
        title="Investigate (claude)",
        role="investigator",
        prefer_harness="claude",
        prefer_model="haiku",
    )
    h, m = herdr._node_seat_prefs(n)
    assert h == "claude"
    assert m == "haiku"
