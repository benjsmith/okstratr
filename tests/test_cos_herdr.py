"""Tests for CoS breakdown + Herdr run-ready (dry-run, temp state dir)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "okstratr-state"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(d))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    import okstratr.blackboard as bb
    import okstratr.dag as dag
    import okstratr.status as status

    bb._DEFAULT = None
    bb._DEFAULT_PATH = None
    dag._DEFAULT = None
    dag._DEFAULT_PATH = None
    status._loaded = False
    status._loaded_from = None
    status._seated_objective = ""
    status._state = "setup"
    return d


def test_cos_break_idempotent(state_dir: Path) -> None:
    from okstratr import blackboard, cos, dag

    dag.seat_root("Ship desk brain")
    r1 = cos.break_down("Ship desk brain")
    assert r1["ok"] is True
    assert set(r1["created"]) == {
        "cos-clarify",
        "cos-gather",
        "cos-execute",
        "cos-verify",
    }
    g = dag.default_dag()
    assert g.nodes["root"].state == "done"
    assert g.nodes["cos-clarify"].state == "ready"
    assert g.nodes["cos-clarify"].depends_on == ["root"]
    assert g.nodes["cos-gather"].depends_on == ["cos-clarify"]
    assert g.nodes["cos-verify"].depends_on == ["cos-execute"]

    # Blackboard plan note
    hits = blackboard.search("CoS plan")
    assert len(hits) >= 1
    assert hits[-1]["author"] == "cos"

    # Idempotent re-run
    r2 = cos.break_down("Ship desk brain")
    assert r2["created"] == []
    assert set(r2["updated"]) == set(r1["created"])
    assert r2["idempotent"] is True
    g2 = dag.default_dag(force_reload=True)
    assert len([n for n in g2.nodes if n.startswith("cos-")]) == 4


def test_seat_auto_cos_and_flag(state_dir: Path) -> None:
    from okstratr.cli import main
    from okstratr import dag

    assert main(["seat", "Auto CoS objective"]) == 0
    g = dag.default_dag(force_reload=True)
    assert "cos-clarify" in g.nodes
    assert g.nodes["root"].state == "done"

    # With existing children, seat without --cos should not re-break... wait:
    # should_auto_break is False when more than root exists.
    # But break_down is only called when do_cos; without --cos and not auto, skip.
    n_before = len(g.nodes)
    assert main(["seat", "Still seated"]) == 0
    g = dag.default_dag(force_reload=True)
    # no new cos nodes; still 5 (root + 4)
    assert len(g.nodes) == n_before

    # Explicit --cos refreshes (idempotent)
    assert main(["seat", "Force CoS", "--cos"]) == 0
    g = dag.default_dag(force_reload=True)
    assert "cos-clarify" in g.nodes


def test_cos_break_cli(state_dir: Path) -> None:
    from okstratr.cli import main
    from okstratr import dag

    assert main(["seat", "--reset", "CLI break obj"]) == 0
    # seat auto-broke already; reset path: seat --reset creates only root then auto-breaks
    g = dag.default_dag(force_reload=True)
    assert "cos-execute" in g.nodes

    assert main(["cos", "break"]) == 0
    assert main(["cos", "Advise only objective"]) == 0


def test_herdr_run_ready_dry_run(state_dir: Path) -> None:
    from okstratr import cos, dag, herdr
    from okstratr.cli import main

    dag.seat_root("Finite jobs")
    cos.break_down("Finite jobs")
    g = dag.default_dag()
    assert "cos-clarify" in [n.id for n in g.ready()]

    out = herdr.run_ready(limit=1, dry_run=True)
    assert out["dry_run"] is True
    assert out["ran"] == ["cos-clarify"]
    assert out["results"][0]["ok"] is True
    assert out["results"][0]["state"] == "done"
    assert out["results"][0]["dry_run"] is True

    g = dag.default_dag(force_reload=True)
    assert g.nodes["cos-clarify"].state == "done"
    assert g.nodes["cos-gather"].state == "ready"

    # CLI
    assert main(["herdr", "run-ready", "--limit", "1", "--dry-run"]) == 0
    g = dag.default_dag(force_reload=True)
    assert g.nodes["cos-gather"].state == "done"
    assert g.nodes["cos-execute"].state == "ready"


def test_herdr_run_ready_respects_env_dry_run(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import cos, dag, herdr

    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    dag.seat_root("Env dry")
    cos.break_down("Env dry")
    out = herdr.run_ready(limit=2)  # dry_run=None → env
    assert out["dry_run"] is True
    assert len(out["ran"]) == 2
    assert all(r["ok"] for r in out["results"])


def test_herdr_always_stops_in_live_path(state_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Live path must invoke stop even when wait fails (finite-job rule)."""
    from okstratr import cos, dag, herdr

    monkeypatch.delenv("OKSTRATR_HERDR_DRY_RUN", raising=False)
    monkeypatch.setenv("OKSTRATR_HERDR_TIMEOUT", "5")

    fake = tmp_path / "herdr"
    log = tmp_path / "herdr-log.txt"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'case "$*" in\n'
        '  *wait*) exit 1 ;;\n'
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")

    dag.seat_root("Live stop")
    cos.break_down("Live stop")
    out = herdr.run_ready(limit=1, dry_run=False)
    assert out["ran"] == ["cos-clarify"]
    # wait failed → node failed, but stop must appear in log
    log_text = log.read_text(encoding="utf-8")
    assert "agent start" in log_text
    assert "agent stop" in log_text or "agent kill" in log_text
    g = dag.default_dag(force_reload=True)
    assert g.nodes["cos-clarify"].state == "failed"


def test_http_cos_and_herdr_run_ready(state_dir: Path) -> None:
    from okstratr.server import Handler
    from http.server import ThreadingHTTPServer
    import threading
    import urllib.request

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"

        req = urllib.request.Request(
            base + "/api/seat",
            data=json.dumps({"objective": "HTTP CoS", "cos": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            seat = json.loads(r.read().decode())
        assert "cos_break" in seat
        assert "cos-clarify" in (seat["cos_break"].get("created") or seat["dag"]["ready"] or [])

        req = urllib.request.Request(
            base + "/api/herdr/run-ready",
            data=json.dumps({"limit": 1, "dry_run": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read().decode())
        assert body["dry_run"] is True
        assert body["ran"] == ["cos-clarify"]
        assert body["results"][0]["state"] == "done"

        with urllib.request.urlopen(base + "/api/dag") as r:
            dag_body = json.loads(r.read().decode())
        assert "cos-gather" in dag_body["ready"]
    finally:
        httpd.shutdown()
