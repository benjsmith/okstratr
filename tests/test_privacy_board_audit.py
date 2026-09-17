"""Privacy: duration retention, ephemeral ASAP, visible names, ops audit."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "okstratr-state"
    d.mkdir()
    cfg = tmp_path / "okstratr-config"
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(d))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    for k in (
        "OKSTRATR_BB_DURATION",
        "OKSTRATR_BB_DURATION_DAYS",
        "OKSTRATR_BB_RETENTION_DAYS",
        "OKSTRATR_BB_ARCHIVE_ON_CLEAR",
    ):
        monkeypatch.delenv(k, raising=False)
    import okstratr.blackboard as bb

    bb._DEFAULT = None
    bb._DEFAULT_PATH = None
    bb._DEFAULT_MTIME = None
    return d


def test_parse_duration_units() -> None:
    from okstratr.bb_settings import parse_duration

    assert parse_duration("3") == 3.0
    assert parse_duration("3d") == 3.0
    assert parse_duration("24h") == 1.0
    assert abs(parse_duration("60m") - (60.0 / (24 * 60))) < 1e-9
    assert parse_duration(0) == 0.0


def test_duration_prune_drops_old_entries(state_dir: Path) -> None:
    from okstratr import bb_settings, blackboard

    bb_settings.save({"duration_days": 3})
    path = state_dir / "blackboard.jsonl"
    old_ts = time.time() - (5 * 86400)
    new_ts = time.time()
    rows = [
        {"id": "old", "ts": old_ts, "author": "human", "text": "OLD", "kind": "note", "tags": [], "provenance": ""},
        {"id": "new", "ts": new_ts, "author": "human", "text": "NEW", "kind": "note", "tags": [], "provenance": ""},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    blackboard.invalidate_default()
    out = blackboard.prune()
    assert out["retention"]["pruned"] == 1
    texts = [e["text"] for e in blackboard.head(10)]
    assert texts == ["NEW"]
    assert not list(state_dir.glob("blackboard.jsonl.archive.*"))


def test_duration_zero_clears_agents_asap(state_dir: Path) -> None:
    from okstratr import bb_settings, blackboard

    bb_settings.save({"duration_days": 0})
    blackboard.post("keep human", author="human")
    blackboard.post("drop me", author="cos", provenance="okstratr.cos")
    # Human still within 60m; agent should be pruned ASAP in ephemeral mode
    out = blackboard.prune()
    texts = [e["text"] for e in blackboard.head(20)]
    assert "keep human" in texts
    assert "drop me" not in texts


def test_duration_zero_hard_max_60m(state_dir: Path) -> None:
    from okstratr import bb_settings, blackboard

    bb_settings.save({"duration_days": 0})
    path = state_dir / "blackboard.jsonl"
    old_ts = time.time() - (90 * 60)  # 90 minutes ago
    path.write_text(
        json.dumps(
            {"id": "old", "ts": old_ts, "author": "human", "text": "STALE", "kind": "note", "tags": [], "provenance": ""}
        )
        + "\n",
        encoding="utf-8",
    )
    blackboard.invalidate_default()
    blackboard.prune()
    assert blackboard.head(10) == []


def test_clear_no_archive_by_default(state_dir: Path) -> None:
    from okstratr import blackboard

    blackboard.post("secret", author="human")
    legacy = state_dir / "blackboard.jsonl.archive.999"
    legacy.write_text("{}\n", encoding="utf-8")
    out = blackboard.clear()
    assert out["cleared"] is True
    assert out.get("archived") is None
    assert not (state_dir / "blackboard.jsonl").is_file()
    assert not list(state_dir.glob("blackboard.jsonl.archive.*"))


def test_invisible_name_rejection() -> None:
    from okstratr.workspace import assert_visible_name

    assert assert_visible_name("notes.txt")["ok"] is True
    assert assert_visible_name(".hidden")["ok"] is False
    assert assert_visible_name("trailing.")["ok"] is False
    assert assert_visible_name("foo\u202egnp.exe")["ok"] is False
    assert assert_visible_name("a\u200bb")["ok"] is False


def test_resolve_rejects_dotfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import workspace

    r = workspace.resolve_in_sandbox(".secret", root=str(tmp_path))
    assert r["ok"] is False
    assert workspace.resolve_in_sandbox("ok.txt", root=str(tmp_path))["ok"] is True


def test_audit_chain_survives_clear(state_dir: Path) -> None:
    from okstratr import blackboard, ops_audit

    ops_audit.append("test.op", kind="process", note="one")
    ops_audit.append("test.op2", kind="file", path="/tmp/x", note="two")
    assert ops_audit.verify()["ok"] is True
    audit_path = state_dir / "ops_audit.jsonl"
    before_len = len(audit_path.read_text())
    blackboard.post("x", author="human")
    blackboard.clear()
    assert audit_path.is_file()
    assert len(audit_path.read_text()) >= before_len
    assert ops_audit.verify()["ok"] is True
    assert "blackboard.clear" in audit_path.read_text()


def test_config_set_duration(state_dir: Path) -> None:
    from okstratr import bb_settings
    from okstratr.harness import config as harness_config

    harness_config.set_value("blackboard.duration", "7")
    assert bb_settings.duration_days() == 7.0
    harness_config.set_value("blackboard.duration", "0")
    assert bb_settings.is_ephemeral() is True
    assert "ephemeral" in bb_settings.mode_chip()


def test_slash_duration_parse() -> None:
    from okstratr.harness.slash import parse_slash_directives

    d = parse_slash_directives("/bb duration 0")
    assert d.duration_value == "0"
    d2 = parse_slash_directives("/bb duration 3d")
    assert d2.duration_value == "3d"
    d3 = parse_slash_directives("/bb prune")
    assert d3.prune_board is True
