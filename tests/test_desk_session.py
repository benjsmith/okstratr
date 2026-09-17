"""Unit tests for DeskSession SSOT shape (ADR-001 Phase 3)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def iso_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    # Reset lazy singletons where present
    import okstratr.blackboard as bb
    import okstratr.dag as dag
    import okstratr.status as status

    for mod in (bb, dag):
        if hasattr(mod, "_DEFAULT"):
            mod._DEFAULT = None
        if hasattr(mod, "_DEFAULT_PATH"):
            mod._DEFAULT_PATH = None
    if hasattr(status, "_loaded"):
        status._loaded = False
    if hasattr(status, "_loaded_from"):
        status._loaded_from = None
    if hasattr(status, "_seated_objective"):
        status._seated_objective = ""
    return state


def test_desk_session_schema_and_standing(iso_env: Path) -> None:
    from okstratr.desk_session import SCHEMA, build, snapshot

    sess = build()
    assert sess.schema == SCHEMA
    d = sess.to_dict()
    assert d["schema"] == SCHEMA
    assert "desks" in d and "standing" in d
    assert len(d["desks"]) >= 1
    row = d["desks"][0]
    for key in ("id", "kind", "state", "objective", "placeholder", "seats", "thread_id"):
        assert key in row
    snap = snapshot()
    assert snap["schema"] == SCHEMA
    assert snap["desks"] == snap["standing"]


def test_status_embeds_desk_session(iso_env: Path) -> None:
    from okstratr import desks, status

    desks.start("phase3 desk session", kind="work", drive_herdr=False)
    snap = status.snapshot()
    assert "desk_session" in snap
    ds = snap["desk_session"]
    assert ds and ds.get("schema", "").startswith("okstratr.desk_session")
    assert isinstance(snap.get("desks"), list)
    assert isinstance(snap.get("standing"), list)
    assert snap.get("status_channel", {}).get("primary") == "GET /api/status"
    assert snap.get("status_channel", {}).get("dual_source") is False
    # At least one non-placeholder standing desk after start
    live = [r for r in snap["desks"] if not r.get("placeholder") and r.get("objective")]
    assert live, snap["desks"]


def test_direct_seat_ref_appears(iso_env: Path) -> None:
    from okstratr.desk_session import build
    from okstratr.harness import procs

    procs.register(
        procs.ProcRecord(
            pid=4242,
            harness_id="grok",
            node_id="n1",
            desk_id="desk-test",
            thread_id="thread-test",
            argv=["grok", "-p", "hi"],
        )
    )
    # Build with a synthetic standing row by monkeypatching standing rows
    import okstratr.desks as desks_mod

    real = desks_mod.default_standing_rows

    def fake_rows(registry=None):
        return [
            {
                "id": "desk-test",
                "kind": "work",
                "state": "working",
                "objective": "seat ref",
                "placeholder": False,
                "schedule": None,
                "thread_id": "thread-test",
            }
        ]

    desks_mod.default_standing_rows = fake_rows  # type: ignore[assignment]
    try:
        d = build().to_dict()
        row = next(r for r in d["desks"] if r["id"] == "desk-test")
        adapters = {s["adapter"] for s in row["seats"]}
        assert "herdr" in adapters
        assert "direct" in adapters
        direct = next(s for s in row["seats"] if s["adapter"] == "direct")
        assert direct["pid"] == 4242
        assert direct["harness_id"] == "grok"
    finally:
        desks_mod.default_standing_rows = real  # type: ignore[assignment]
