"""host_notify envelope + schedule.fire_due emit (contract C2)."""

from __future__ import annotations

import json
from pathlib import Path
from time import time

import pytest


@pytest.fixture()
def iso_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    for key in (
        "OKSTRATR_HOST_NOTIFY_URL",
        "OKSTRATR_HOSTED",
        "OKSTRATR_HOST",
        "OKSTRATR_JSON_NOTIFY",
    ):
        monkeypatch.delenv(key, raising=False)

    import okstratr.blackboard as bb
    import okstratr.dag as dag
    import okstratr.desks as desks
    import okstratr.host_notify as hn
    import okstratr.schedule as schedule
    import okstratr.status as status

    for mod in (bb, dag):
        if hasattr(mod, "_DEFAULT"):
            mod._DEFAULT = None
        if hasattr(mod, "_DEFAULT_PATH"):
            mod._DEFAULT_PATH = None
    if hasattr(desks, "_DEFAULT"):
        desks._DEFAULT = None
    if hasattr(desks, "_DEFAULT_PATH"):
        desks._DEFAULT_PATH = None
    if hasattr(status, "_loaded"):
        status._loaded = False
    if hasattr(status, "_loaded_from"):
        status._loaded_from = None
    if hasattr(status, "_seated_objective"):
        status._seated_objective = ""
    if hasattr(status, "_state"):
        status._state = "setup"
    hn.set_json_notify(None)
    if hasattr(schedule, "clear"):
        schedule.clear()
    return state


def test_build_and_validate_envelope(iso_env: Path) -> None:
    from okstratr import host_notify as hn

    env = hn.build_envelope(
        "schedule.start",
        title="Morning run",
        body="hedge desk",
        schedule_id="sched-1",
        desk="work",
        progress={"pct": 0, "phase": "start", "detail": "go"},
    )
    assert env["type"] == "okstratr.host_notify"
    assert env["v"] == 1
    assert env["kind"] == "schedule.start"
    assert env["desk"] == "work"
    assert env["progress"]["pct"] == 0
    assert env["progress"]["phase"] == "start"
    validated = hn.validate_envelope(env)
    assert validated["schedule_id"] == "sched-1"
    assert "ts" in validated


def test_validate_rejects_bad_kind(iso_env: Path) -> None:
    from okstratr import host_notify as hn

    with pytest.raises(hn.HostNotifyError):
        hn.validate_envelope(
            {
                "type": "okstratr.host_notify",
                "v": 1,
                "kind": "email.blast",
                "title": "x",
                "body": "",
                "progress": {"pct": None, "phase": "", "detail": ""},
                "ts": "2026-09-19T00:00:00+00:00",
            }
        )


def test_bare_summary_and_json_notify(
    iso_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr import host_notify as hn

    r = hn.emit(
        "desk.done",
        title="Desk finished",
        body="all nodes terminal",
        desk="auto",
        force_bare=True,
    )
    assert r["ok"] is True
    assert r["path"] == "bare"
    err = capsys.readouterr().err
    assert "desk.done" in err
    assert "Desk finished" in err

    monkeypatch.setenv("OKSTRATR_JSON_NOTIFY", "1")
    hn.set_json_notify(None)
    r2 = hn.emit(
        "schedule.progress",
        title="Halfway",
        desk="research",
        progress={"pct": 50, "phase": "mid", "detail": ""},
        force_bare=True,
    )
    assert r2["mode"] == "json"
    line = capsys.readouterr().err.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["kind"] == "schedule.progress"
    assert payload["progress"]["pct"] == 50


def test_hosted_posts_to_url(iso_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import host_notify as hn

    posted: list[tuple[str, dict]] = []

    def fake_http(envelope: dict, url: str, *, timeout: float = 2.5) -> dict:
        posted.append((url, envelope))
        return {"ok": True, "path": "http", "url": url, "status": 200, "body": ""}

    monkeypatch.setattr(hn, "deliver_http", fake_http)
    monkeypatch.setenv(
        "OKSTRATR_HOST_NOTIFY_URL", "http://127.0.0.1:9/api/okstratr/host-notify"
    )
    r = hn.emit("schedule.done", title="Done", schedule_id="s1", desk="deck")
    assert r["ok"] is True
    assert r["path"] == "http"
    assert posted and posted[0][0].endswith("/api/okstratr/host-notify")
    assert posted[0][1]["kind"] == "schedule.done"


def test_fire_due_emits_schedule_start(
    iso_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okstratr import desks, host_notify as hn, schedule

    emits: list[dict] = []

    def capture_emit(kind: str, **kwargs):
        env = hn.build_envelope(
            kind,
            title=kwargs.get("title") or kind,
            body=kwargs.get("body") or "",
            schedule_id=kwargs.get("schedule_id"),
            desk=kwargs.get("desk"),
            progress=kwargs.get("progress"),
            ts=kwargs.get("ts"),
            extra=kwargs.get("extra"),
        )
        emits.append(env)
        return {
            "ok": True,
            "path": "bare",
            "mode": "summary",
            "envelope": env,
        }

    monkeypatch.setattr(hn, "emit", capture_emit)

    desks.start("fake scheduled job", kind="work", drive_herdr=False)
    desks.schedule(["3s"])
    reg = desks.default_registry()
    desk = reg.active()
    assert desk is not None and desk.schedule
    desk.schedule["attached_at"] = time() - 10
    desk.schedule.pop("last_fire_ts", None)
    reg.save()

    due = schedule.due_desks()
    assert due, "expected due schedule after backdating attached_at"
    result = schedule.fire_due(emit_notify=True)
    assert result.get("count") == 1
    assert result["fired"][0]["desk_id"] == desk.id
    assert any(e["kind"] == "schedule.start" for e in emits)
    assert desk.schedule.get("last_fire_ts") is not None


def test_status_health_block(iso_env: Path) -> None:
    from okstratr import lifecycle, status

    snap = status.snapshot()
    health = snap.get("health") or {}
    assert set(health) >= {"ce", "okstratr", "wiki_build"}
    assert health["okstratr"]["state"] in ("starting", "healthy", "unhealthy", "stopped")
    assert health["ce"]["state"] in ("starting", "healthy", "unhealthy", "stopped")
    assert health["wiki_build"]["state"] in ("idle", "building", "failed")

    payload = lifecycle.status_payload()
    assert "health" in payload
    assert payload["health"]["okstratr"]["state"] in (
        "starting",
        "healthy",
        "unhealthy",
        "stopped",
    )
