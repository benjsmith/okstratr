"""Unit tests for harness list/enable/disable API helpers (Phase 3)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "cfg"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(d))
    monkeypatch.delenv("OKSTRATR_HARNESSES_TOML", raising=False)
    from okstratr.harness import select as sel

    sel.reset_rr()
    return d


def test_list_for_api_shape(cfg_dir: Path) -> None:
    from okstratr.harness import config as hcfg

    hcfg.save(hcfg.default_config())
    payload = hcfg.list_for_api()
    assert payload["ok"] is True
    assert payload["path"]
    assert "grok" in payload["enabled"]
    assert isinstance(payload["harnesses"], list)
    assert len(payload["harnesses"]) >= 3
    row = next(r for r in payload["harnesses"] if r["id"] == "grok")
    assert row["enabled"] is True
    assert row["default_model"]
    assert "trivial" in (row.get("effort") or {}) or row.get("effort") == {}


def test_enable_disable_persist(cfg_dir: Path) -> None:
    from okstratr.harness import config as hcfg

    hcfg.save(hcfg.default_config())
    hcfg.enable("claude")
    payload = hcfg.list_for_api()
    assert "claude" in payload["enabled"]
    claude = next(r for r in payload["harnesses"] if r["id"] == "claude")
    assert claude["enabled"] is True
    hcfg.disable("claude")
    payload = hcfg.list_for_api()
    assert "claude" not in payload["enabled"]


def test_status_includes_harness(cfg_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    from okstratr.harness import config as hcfg
    from okstratr import status

    hcfg.save(hcfg.default_config())
    snap = status.snapshot()
    assert snap.get("harness", {}).get("ok") is True
    assert isinstance(snap["harness"]["harnesses"], list)
