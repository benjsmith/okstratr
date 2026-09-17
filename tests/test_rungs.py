"""Schema migrate/load + select-by-rung tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "cfg"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(d))
    monkeypatch.delenv("OKSTRATR_HARNESSES_TOML", raising=False)
    from okstratr.harness import select

    select.reset_rr()
    return d


def test_effort_to_rung() -> None:
    from okstratr.harness.rungs import effort_to_rung

    assert effort_to_rung(0.1) == "trivial"
    assert effort_to_rung(0.5) == "normal"
    assert effort_to_rung(0.9) == "hard"
    assert effort_to_rung(None) == "normal"


def test_config_rungs_roundtrip(cfg_dir: Path) -> None:
    from okstratr.harness import config as hcfg

    cfg = hcfg.default_config()
    cfg.enabled = ["claude", "grok"]
    cfg.harness["claude"].default_model = "claude-sonnet-4"
    cfg.harness["claude"].effort = {
        "trivial": "claude-haiku",
        "normal": "claude-sonnet-4",
        "hard": "claude-opus-4",
    }
    path = hcfg.save(cfg)
    assert path.is_file()
    raw = path.read_text(encoding="utf-8")
    assert "default_model" in raw
    assert "effort" in raw
    loaded = hcfg.load()
    assert loaded.default_model_for("claude") == "claude-sonnet-4"
    assert loaded.effort_map_for("claude")["hard"] == "claude-opus-4"


def test_config_set_harness_default_model(cfg_dir: Path) -> None:
    from okstratr.harness import config as hcfg

    hcfg.save(hcfg.default_config())
    cfg = hcfg.set_value("harness.claude.default_model", "claude-opus-4")
    assert cfg.harness["claude"].default_model == "claude-opus-4"
    cfg = hcfg.set_value("harness.claude.effort.hard", "claude-opus-4")
    assert cfg.harness["claude"].effort["hard"] == "claude-opus-4"
    cfg = hcfg.set_value("backend", "direct")
    assert cfg.preferred_backend() == "direct"


def test_select_by_rung(cfg_dir: Path) -> None:
    from okstratr.harness import config as hcfg
    from okstratr.harness import select
    from okstratr.harness.types import SeatRequest

    cfg = hcfg.default_config()
    cfg.enabled = ["claude"]
    hcfg.save(cfg)

    def which(name: str):
        return f"/bin/{name}" if name in ("claude", "claude-code") else None

    hard = select.choose_harness(
        SeatRequest(node_id="h", prefer_harness="claude", rung="hard"),
        cfg=hcfg.load(),
        which=which,
        round_robin=False,
    )
    assert hard.ok
    assert hard.model == "claude-opus-4"
    assert hard.detail.get("model_select", {}).get("rung") == "hard"

    trivial = select.choose_harness(
        SeatRequest(node_id="t", prefer_harness="claude", effort=0.1),
        cfg=hcfg.load(),
        which=which,
        round_robin=False,
    )
    assert trivial.model == "claude-haiku"


def test_slash_model_harness_colon() -> None:
    from okstratr.harness.slash import apply_harness_slash_to_env, parse_slash_directives

    d = parse_slash_directives("/model claude:sonnet ship it")
    assert d.model_harness == "claude"
    assert d.model == "sonnet"
    assert d.harnesses == ["claude"]
    assert d.objective == "ship it"
    env = apply_harness_slash_to_env(d)
    assert env["OKSTRATR_HERDR_KIND"] == "claude"
    assert env["OKSTRATR_MODEL"] == "sonnet"

    d2 = parse_slash_directives("/rung hard /harness claude do")
    assert d2.rung == "hard"
    assert d2.harnesses == ["claude"]


def test_cli_model_list(cfg_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from okstratr.cli import main

    assert main(["model", "list"]) == 0
    out = capsys.readouterr().out
    assert "claude" in out or "grok" in out
