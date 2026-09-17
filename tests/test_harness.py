"""Unit tests for harness registry, config, select, slash."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "cfg"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(d))
    monkeypatch.delenv("OKSTRATR_HARNESSES_TOML", raising=False)
    monkeypatch.delenv("OKSTRATR_HERDR_KIND", raising=False)
    monkeypatch.delenv("OKSTRATR_HARNESS_PREFER", raising=False)
    monkeypatch.delenv("OKSTRATR_MODEL", raising=False)
    from okstratr.harness import select as sel

    sel.reset_rr()
    return d


def test_detect_installed_mock(cfg_dir: Path) -> None:
    from okstratr.harness import detect_installed, registry

    def which(name: str):
        return "/bin/claude" if name == "claude" else None

    assert detect_installed("claude", which=which) is True
    assert detect_installed("grok", which=which) is False
    assert detect_installed("nope", which=which) is False
    assert registry.get("claude").herdr_kind == "claude"


def test_config_roundtrip(cfg_dir: Path) -> None:
    from okstratr import harness

    cfg = harness.default_config() if hasattr(harness, "default_config") else None
    from okstratr.harness import config as hcfg

    cfg = hcfg.default_config()
    cfg.enabled = ["grok", "claude"]
    cfg.preference = ["claude", "grok"]
    cfg.models["claude"] = ["claude-sonnet-4", "claude-opus-4"]
    # Keep nested Phase-2 settings in sync with flat models table
    from okstratr.harness.config import PerHarnessSettings
    cfg.harness["claude"] = PerHarnessSettings(
        models=["claude-sonnet-4", "claude-opus-4"],
        default_model="claude-sonnet-4",
    )
    path = hcfg.save(cfg)
    assert path.is_file()
    loaded = hcfg.load()
    assert loaded.enabled == ["grok", "claude"]
    assert loaded.preference_order()[0] == "claude"
    assert [m.id for m in loaded.models_for("claude")] == [
        "claude-sonnet-4",
        "claude-opus-4",
    ]


def test_enable_disable(cfg_dir: Path) -> None:
    from okstratr.harness import config as hcfg

    hcfg.save(hcfg.default_config())
    cfg = hcfg.enable("claude")
    assert "claude" in cfg.enabled
    cfg = hcfg.disable("claude")
    assert "claude" not in cfg.enabled
    assert cfg.enabled  # never empty


def test_select_respects_allowlist(cfg_dir: Path) -> None:
    from okstratr.harness import config as hcfg
    from okstratr.harness import select
    from okstratr.harness.types import SeatRequest

    cfg = hcfg.default_config()
    cfg.enabled = ["claude", "codex"]
    cfg.preference = ["codex", "claude"]
    hcfg.save(cfg)

    def which(name: str):
        # both installed
        return f"/bin/{name}" if name in ("claude", "codex", "grok") else None

    select.reset_rr()
    r1 = select.choose_harness(
        SeatRequest(node_id="n1"),
        cfg=hcfg.load(),
        which=which,
        require_installed=True,
        round_robin=False,
    )
    assert r1.ok
    assert r1.harness_id == "codex"  # preference first among enabled

    # prefer_harness
    r2 = select.choose_harness(
        SeatRequest(node_id="n2", prefer_harness="claude"),
        cfg=hcfg.load(),
        which=which,
        require_installed=True,
    )
    assert r2.harness_id == "claude"


def test_select_missing_harness_error(cfg_dir: Path) -> None:
    from okstratr.harness import config as hcfg
    from okstratr.harness import select
    from okstratr.harness.types import SeatRequest

    cfg = hcfg.default_config()
    cfg.enabled = ["claude"]
    hcfg.save(cfg)

    def which(_name: str):
        return None  # nothing installed

    r = select.choose_harness(
        SeatRequest(node_id="n"),
        cfg=hcfg.load(),
        which=which,
        require_installed=True,
    )
    assert r.ok is False
    assert "no enabled harness installed" in (r.error or "")


def test_env_override_wins(cfg_dir: Path) -> None:
    from okstratr.harness import select

    r = select.resolve_herdr_kind(env_override="pi", require_installed=False)
    assert r.ok
    assert r.herdr_kind == "pi"
    assert r.detail.get("source") == "OKSTRATR_HERDR_KIND"


def test_slash_harness_model() -> None:
    from okstratr.harness.slash import apply_harness_slash_to_env, parse_slash_directives

    d = parse_slash_directives("/harness grok,claude /model grok-4 ship the desk")
    assert d.harnesses == ["grok", "claude"]
    assert d.model == "grok-4"
    assert d.objective == "ship the desk"
    env = apply_harness_slash_to_env(d)
    assert env["OKSTRATR_HERDR_KIND"] == "grok"
    assert env["OKSTRATR_MODEL"] == "grok-4"

    d2 = parse_slash_directives("/work /harness claude do the thing")
    assert d2.kind == "work"
    assert d2.harnesses == ["claude"]
    assert d2.objective == "do the thing"


def test_cli_harness_list(cfg_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from okstratr.cli import main

    assert main(["harness", "list"]) == 0
    out = capsys.readouterr().out
    assert "grok" in out
    assert "claude" in out


def test_cli_config_set(cfg_dir: Path) -> None:
    from okstratr.cli import main
    from okstratr.harness import load

    assert main(["config", "set", "enabled", "grok,claude"]) == 0
    cfg = load()
    assert cfg.enabled == ["grok", "claude"]
