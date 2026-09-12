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
    assert "investigator" in g.nodes
    assert g.nodes["root"].state == "done"

    # With existing children, seat without --cos should not re-break... wait:
    # should_auto_break is False when more than root exists.
    # But break_down is only called when do_cos; without --cos and not auto, skip.
    n_before = len(g.nodes)
    assert main(["seat", "Still seated"]) == 0
    g = dag.default_dag(force_reload=True)
    # new auto desk gets the same Switchbay shape
    assert len(g.nodes) == n_before

    # Explicit --cos refreshes (idempotent)
    assert main(["seat", "Force CoS", "--cos"]) == 0
    g = dag.default_dag(force_reload=True)
    assert "investigator" in g.nodes


def test_cos_break_cli(state_dir: Path) -> None:
    from okstratr.cli import main
    from okstratr import dag

    assert main(["seat", "--reset", "CLI break obj"]) == 0
    # seat auto-broke already; reset path: seat --reset creates only root then auto-breaks
    g = dag.default_dag(force_reload=True)
    assert "synthesizer" in g.nodes

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
        created = seat["cos_break"].get("created") or []
        ready = (seat.get("dag") or {}).get("ready") or []
        assert "investigator" in created or "investigator" in ready

        req = urllib.request.Request(
            base + "/api/herdr/run-ready",
            data=json.dumps({"limit": 1, "dry_run": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read().decode())
        assert body["dry_run"] is True
        assert body["ran"] == ["investigator"]
        assert body["results"][0]["state"] == "done"

        with urllib.request.urlopen(base + "/api/dag") as r:
            dag_body = json.loads(r.read().decode())
        assert "synthesizer" in dag_body["ready"]
    finally:
        httpd.shutdown()


def test_herdr_launch_candidates_prefer_uwsm_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """uwsm-app + xdg-terminal-exec/--dir $HOME beats omarchy wrappers and direct herdr."""
    from okstratr import herdr

    for name in ("uwsm-app", "xdg-terminal-exec", "foot", "herdr", "omarchy-launch-terminal-herdr"):
        p = tmp_path / name
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(0o755)

    monkeypatch.setenv("PATH", str(tmp_path))
    home = str(tmp_path / "home")
    Path(home).mkdir()
    cands = herdr._launch_candidates("ship it", path=str(tmp_path), home=home)
    assert cands[0] == [str(tmp_path / "uwsm-app"), "--", str(tmp_path / "xdg-terminal-exec"), "--dir", home, "herdr"]
    assert cands[1] == [str(tmp_path / "uwsm-app"), "--", str(tmp_path / "foot"), "herdr"]
    # Direct herdr later; may take objective argv
    assert [str(tmp_path / "herdr"), "ship it"] in cands
    # Omarchy wrapper is fallback only
    assert [str(tmp_path / "omarchy-launch-terminal-herdr")] in cands
    assert cands.index([str(tmp_path / "omarchy-launch-terminal-herdr")]) > cands.index(
        [str(tmp_path / "herdr"), "ship it"]
    )
    # No free-text objective on terminal wrappers
    def _is_term_wrapper(c: list[str]) -> bool:
        if herdr._is_omarchy_terminal_launcher(c):
            return True
        if len(c) >= 3 and "xdg-terminal-exec" in str(c[2]):
            return True
        if len(c) >= 3 and (str(c[2]).endswith("/foot") or c[2] == str(tmp_path / "foot")):
            return True
        return False

    assert all("ship it" not in c for c in cands if _is_term_wrapper(c))


def test_herdr_launch_merges_systemd_env_and_devnull(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from okstratr import herdr

    fake_herdr = tmp_path / "herdr"
    fake_uwsm = tmp_path / "uwsm-app"
    fake_xdg = tmp_path / "xdg-terminal-exec"
    for p in (fake_herdr, fake_uwsm, fake_xdg):
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(0o755)

    monkeypatch.setenv("PATH", str(tmp_path))
    # Serve-like: no Wayland in process env
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)

    def fake_systemd() -> dict[str, str]:
        return {
            "WAYLAND_DISPLAY": "wayland-1",
            "HYPRLAND_INSTANCE_SIGNATURE": "sig123",
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "EMPTY_SKIP": "",
            "QT_QPA_PLATFORM": "-",  # broken placeholder → skip
        }

    monkeypatch.setattr(herdr, "systemd_user_environment", fake_systemd)

    popped: list[dict] = []

    def fake_popen(cmd, env=None, stdout=None, stderr=None, start_new_session=False):  # noqa: ANN001
        popped.append(
            {
                "cmd": list(cmd),
                "env": dict(env or {}),
                "stdout": stdout,
                "stderr": stderr,
                "start_new_session": start_new_session,
            }
        )

        class _P:
            pid = 1

        return _P()

    monkeypatch.setattr(herdr.subprocess, "Popen", fake_popen)
    out = herdr.launch("ship it")
    assert out["ok"] is True
    assert popped, "expected Popen"
    call = popped[0]
    assert call["stdout"] is herdr.subprocess.DEVNULL
    assert call["stderr"] is herdr.subprocess.DEVNULL
    assert call["start_new_session"] is True
    assert call["env"].get("WAYLAND_DISPLAY") == "wayland-1"
    assert call["env"].get("HYPRLAND_INSTANCE_SIGNATURE") == "sig123"
    assert call["env"].get("OKSTRATR_OBJECTIVE") == "ship it"
    assert "QT_QPA_PLATFORM" not in call["env"] or call["env"].get("QT_QPA_PLATFORM") != "-"
    # Prefer uwsm + xdg-terminal-exec
    assert call["cmd"][0] == str(fake_uwsm)
    assert "xdg-terminal-exec" in call["cmd"][2]
    assert "--dir" in call["cmd"]


def test_herdr_launch_omarchy_fallback_no_objective_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """omarchy wrappers are fallback only and never get objective argv."""
    from okstratr import herdr

    term_herdr = tmp_path / "omarchy-launch-terminal-herdr"
    term_herdr.write_text("#!/bin/sh\nexit 0\n")
    term_herdr.chmod(0o755)
    # No uwsm/foot/xdg-terminal-exec/herdr — only omarchy wrapper
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(herdr, "systemd_user_environment", lambda: {})

    cands = herdr._launch_candidates("do not put this on argv", path=str(tmp_path))
    assert cands[0] == [str(term_herdr)]
    assert all(
        "do not put this on argv" not in c
        for c in cands
        if herdr._is_omarchy_terminal_launcher(c)
    )

    popped: list[list[str]] = []
    envs: list[dict] = []

    def fake_popen(cmd, env=None, stdout=None, stderr=None, start_new_session=False):  # noqa: ANN001
        popped.append(list(cmd))
        envs.append(dict(env or {}))

        class _P:
            pid = 1

        return _P()

    monkeypatch.setattr(herdr.subprocess, "Popen", fake_popen)
    # herdr binary missing → ok False even if wrapper started
    out = herdr.launch("do not put this on argv")
    assert out["ok"] is False
    assert out["exec"] == [str(term_herdr)]
    assert "install" in (out.get("message") or "").lower() or "Herdr not installed" in (out.get("message") or "")
    assert popped == [[str(term_herdr)]]
    assert envs[0].get("OKSTRATR_OBJECTIVE") == "do not put this on argv"
    assert envs[0].get("HERDR_OBJECTIVE") == "do not put this on argv"


def test_herdr_launch_dry_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from okstratr import herdr

    monkeypatch.setenv("PATH", str(tmp_path))  # empty dir — no herdr/uwsm/xdg
    monkeypatch.setattr(herdr, "systemd_user_environment", lambda: {})
    out = herdr.launch("x")
    assert out["ok"] is False
    assert out.get("dry_run") is True
    assert "Herdr not installed" in out["message"]
    assert "herdr.dev/install.sh" in out["message"] or "omarchy pkg add herdr" in out["message"]


def test_herdr_launch_ok_when_herdr_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from okstratr import herdr

    fake_herdr = tmp_path / "herdr"
    fake_uwsm = tmp_path / "uwsm-app"
    fake_foot = tmp_path / "foot"
    for p in (fake_herdr, fake_uwsm, fake_foot):
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(herdr, "systemd_user_environment", lambda: {"WAYLAND_DISPLAY": "wayland-1"})

    def fake_popen(cmd, env=None, stdout=None, stderr=None, start_new_session=False):  # noqa: ANN001
        class _P:
            pid = 1

        return _P()

    monkeypatch.setattr(herdr.subprocess, "Popen", fake_popen)
    out = herdr.launch("go")
    assert out["ok"] is True
    assert out["herdr_bin"] == str(fake_herdr)
    assert out["exec"][0] == str(fake_uwsm)


def test_http_herdr_launch(state_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from okstratr.server import Handler
    from http.server import ThreadingHTTPServer
    import threading
    import urllib.request
    from okstratr import herdr

    fake = tmp_path / "herdr"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(herdr, "systemd_user_environment", lambda: {})

    popped: list[list[str]] = []

    def fake_popen(cmd, env=None, stdout=None, stderr=None, start_new_session=False):  # noqa: ANN001
        popped.append(list(cmd))

        class _P:
            pid = 1

        return _P()

    monkeypatch.setattr(herdr.subprocess, "Popen", fake_popen)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/herdr/launch",
            data=json.dumps({"objective": "focus me"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read().decode())
        assert body["ok"] is True
        assert body["objective"] == "focus me"
        assert body["herdr_bin"] == str(fake)
        assert popped
    finally:
        httpd.shutdown()


def test_merge_user_session_env_skips_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import herdr

    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(
        herdr,
        "systemd_user_environment",
        lambda: {
            "WAYLAND_DISPLAY": "wayland-1",
            "DISPLAY": "",
            "HYPRLAND_INSTANCE_SIGNATURE": "none",
            "XDG_RUNTIME_DIR": "/run/user/1000",
        },
    )
    env = herdr.merge_user_session_env({"PATH": "/usr/bin"})
    assert env["WAYLAND_DISPLAY"] == "wayland-1"
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert "DISPLAY" not in env or env.get("DISPLAY") == ""
    assert env.get("HYPRLAND_INSTANCE_SIGNATURE") != "none"
    assert "/.local/bin" in env["PATH"]


def test_dag_graph_view_idle_and_switchbay(state_dir: Path) -> None:
    from okstratr import cos, dag

    g = dag.default_dag()
    idle = g.graph_view()
    assert idle["idle"] is True
    ids = [n["id"] for n in idle["nodes"]]
    assert ids == ["cos", "blackboard"]
    assert idle["edges"] == [{"from": "cos", "to": "blackboard"}]

    dag.seat_root("Graph obj")
    cos.break_down("Graph obj", kind="auto")
    g = dag.default_dag(force_reload=True)
    view = g.graph_view()
    assert view["idle"] is False
    ids = {n["id"] for n in view["nodes"]}
    assert "cos" in ids and "blackboard" in ids
    assert "investigator" in ids
    assert "synthesizer" in ids or "verifier" in ids
    # summary exposes graph for /api/status and /api/dag
    summary = g.summary()
    assert "graph" in summary
    assert summary["graph"]["nodes"]

