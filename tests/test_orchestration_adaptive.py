"""AdaptiveRun hands the evidence picture to the expansion rule."""

from __future__ import annotations

from pathlib import Path

import pytest

from okstratr import orchestration as orch
from okstratr import orchestration_bench as bench
from okstratr import orchestration_utility as ou


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(tmp_path / "cfg"))


def test_verify_time_expansion_sees_unique_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    real = ou.choose_expansion

    def spy(**kw):
        seen.append(kw.get("unique_sources"))
        return real(**kw)

    monkeypatch.setattr(ou, "choose_expansion", spy)
    sc = next(s for s in bench.SCENARIOS if s.name == "research-maximum-hard")
    bench.run_utility(sc)
    assert seen, "no expansion decision was made"
    assert all(isinstance(x, int) and x > 0 for x in seen)
