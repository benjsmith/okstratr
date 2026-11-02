"""A finished Herdr job is a batch of seats, not the desk being done."""

from __future__ import annotations

import pytest

from okstratr import herdr_jobs


def test_batch_without_quiet_is_progress():
    kind, _, body, prog = herdr_jobs.finish_notice(
        "j1", desk_id="d1", desk_kind="auto", fail=None, quieted=False, schedule_id=None, ran=2)
    assert kind == "desk.progress" and prog["phase"] == "running" and "more remain" in body


def test_quieted_desk_is_done():
    kind, *_ = herdr_jobs.finish_notice(
        "j1", desk_id="d1", desk_kind="auto", fail=None, quieted=True, schedule_id=None)
    assert kind == "desk.done"


def test_failure_without_schedule_is_not_schedule_failed():
    kind, _, _, prog = herdr_jobs.finish_notice(
        "j1", desk_id="d1", desk_kind="auto", fail="boom", quieted=False, schedule_id=None)
    assert kind == "desk.progress" and prog["phase"] == "failed"
    kind, *_ = herdr_jobs.finish_notice(
        "j1", desk_id="d1", desk_kind="auto", fail="boom", quieted=False, schedule_id="s1")
    assert kind == "schedule.failed"


def test_finish_job_emits_progress_not_done(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path))
    from okstratr import host_notify, status

    sent = []
    monkeypatch.setattr(host_notify, "emit", lambda kind, **kw: sent.append(kind))
    monkeypatch.setattr(status, "write_status", lambda *a, **k: None)
    monkeypatch.setitem(herdr_jobs._jobs, "jx", {"id": "jx", "state": "running", "limit": 4})
    herdr_jobs._finish_job("jx", herdr_run={"ran": ["a"], "desk_quieted": False}, herdr_err=None, desk_id=None)
    assert sent == ["desk.progress"]
