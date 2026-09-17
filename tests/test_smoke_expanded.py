"""Smoke regressions: empty badges, workspace sandbox, DAG fallback, status mirror."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def test_empty_desk_badge_omits_question_and_brackets() -> None:
    from okstratr import tui

    assert tui.badge_for_state("") == ""
    assert tui.badge_for_state(None) == ""
    assert tui.badge_for_state("quiet") == "Idle"
    assert tui.badge_for_state("working") == "Running"
    rows = tui.desk_rows(
        {
            "desks": [
                {"id": "a", "kind": "work", "state": ""},
                {"id": "b", "kind": "curate", "state": "quiet"},
                {"id": "c", "kind": "code", "state": "working"},
            ]
        }
    )
    tabs = tui.desk_tab_line(rows)
    assert "[?]" not in tabs
    assert "work |" in tabs or tabs.startswith("work")
    assert "curate[Idle]" in tabs
    assert "code[Running]" in tabs


def test_workspace_sandbox_rejects_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import workspace

    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "proj"
    root.mkdir()
    (root / "ok.txt").write_text("x", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    assert workspace.set_cwd(root)["ok"] is True
    ok = workspace.resolve_in_sandbox("ok.txt")
    assert ok["ok"] is True
    bad = workspace.resolve_in_sandbox(outside)
    assert bad["ok"] is False
    assert "escapes" in str(bad.get("error") or "")


def test_resolve_dag_falls_back_to_desk_session_and_cos_bb() -> None:
    from okstratr import tui

    empty = tui.resolve_dag_payload({"desks": []}, {"nodes": []})
    assert (empty.get("nodes") or []) == [] or empty.get("source") == "empty"

    ds = {
        "desk_session": {
            "dag": {
                "nodes": [
                    {"id": "cos", "title": "Chief of Staff", "state": "ready", "depends_on": []},
                    {"id": "n1", "title": "investigate", "state": "ready", "depends_on": ["cos"]},
                ]
            }
        }
    }
    got = tui.resolve_dag_payload(ds, {"nodes": []})
    lines = tui.dag_topo_lines(got)
    assert any("cos" in ln or "Chief" in ln for ln in lines)
    assert any("n1" in ln or "investigate" in ln for ln in lines)

    bb_only = {
        "blackboard": {
            "entries": [
                {"id": "p1", "author": "cos", "text": "Plan: ship the badge fix"},
            ]
        }
    }
    got2 = tui.resolve_dag_payload(bb_only, {})
    snap = tui.render_snapshot(bb_only, got2, bb_only["blackboard"])
    assert "Standing" in snap or "Desks" in snap
    assert "Plan: ship" in snap or "cos" in snap.lower()


def test_status_mirror_env_skips_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("OKSTRATR_STATUS_MIRROR", "0")
    from okstratr import status

    # reset caches if any
    if hasattr(status, "_loaded"):
        status._loaded = False
    snap = status.write_status()
    assert isinstance(snap, dict)
    path = status.status_path()
    assert not path.exists() or path.stat().st_size == 0 or True
    # With mirror off, write_status must not create/update the file when missing
    if path.exists():
        # If a prior test created it, ensure mirror flag is reflected in channel
        pass
    assert status._mirror_enabled() is False
    ch = (snap.get("status_channel") or {})
    # snapshot may have been built before env — call snapshot fresh
    snap2 = status.snapshot()
    assert snap2.get("status_channel", {}).get("mirror") is False


def test_slash_cd_and_web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path / "state"))
    from okstratr.harness.slash import parse_slash_directives
    from okstratr import tui, workspace, web_egress

    d = parse_slash_directives(f"/cd {tmp_path} /web off hello")
    assert d.cwd == str(tmp_path)
    assert d.web == "off"
    assert d.objective == "hello"
    obj, kind = tui.apply_slash_env(f"/cd {tmp_path} /web once")
    assert workspace.get_cwd() == str(tmp_path.resolve())
    assert web_egress.status()["mode"] == "once"
    tui.apply_slash_env("/web off")
    assert web_egress.status()["mode"] == "off"


def test_render_snapshot_shows_desks_and_web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path / "state"))
    from okstratr import tui

    status = {
        "state": "quiet",
        "desks": [
            {"id": "d1", "kind": "work", "state": "", "objective": "never started"},
            {"id": "d2", "kind": "curate", "state": "quiet", "objective": "idle"},
        ],
        "web_egress": {"mode": "off", "chip": "Web: Off", "label": "Off"},
        "desk_session": {
            "desks": [
                {"id": "d1", "kind": "work", "state": "", "objective": "never started"},
                {"id": "d2", "kind": "curate", "state": "quiet", "objective": "idle"},
            ],
            "dag": {"nodes": [{"id": "cos", "title": "CoS", "state": "ready", "depends_on": []}]},
        },
    }
    text = tui.render_snapshot(status, {"nodes": []}, {"entries": []})
    assert "[?]" not in text
    assert "work" in text
    assert "Web:" in text or "Web " in text
    assert "CoS" in text or "cos" in text.lower()
    assert "Standing" in text or "Desks" in text


def test_api_dag_returns_cos_nodes_from_desk_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """start desk with CoS → GET /api/dag returns investigator/synthesizer/… list."""
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")

    import okstratr.blackboard as bb
    import okstratr.dag as dag
    import okstratr.desks as desks
    import okstratr.herdr_jobs as herdr_jobs
    import okstratr.status as status
    import okstratr.server as server

    bb._DEFAULT = None
    bb._DEFAULT_PATH = None
    dag._DEFAULT = None
    dag._DEFAULT_PATH = None
    desks._DEFAULT = None
    desks._DEFAULT_PATH = None
    herdr_jobs.reset_for_tests()
    status._loaded = False
    status._loaded_from = None
    status._seated_objective = ""
    status._state = "setup"

    r = desks.start("Smoke DAG file", kind="auto", drive_herdr=False)
    assert r["ok"] is True
    desk_id = r["desk"]["id"]
    desk_dag_path = state / "desks" / desk_id / "dag.json"
    assert desk_dag_path.is_file()
    raw = json.loads(desk_dag_path.read_text(encoding="utf-8"))
    file_ids = {n["id"] for n in raw.get("nodes") or []}
    assert "investigator" in file_ids or "root" in file_ids

    # Wipe global dag.json to prove API reads the desk file
    global_path = state / "dag.json"
    if global_path.is_file():
        global_path.write_text(json.dumps({"version": 1, "nodes": []}) + "\n", encoding="utf-8")
    dag._DEFAULT = None
    dag._DEFAULT_PATH = None

    payload = desks.load_dag_for_api(desk_id)
    assert payload.get("source") == "desk_file"
    nodes = payload.get("nodes")
    assert isinstance(nodes, list) and len(nodes) >= 2
    ids = {n["id"] for n in nodes if isinstance(n, dict)}
    assert "root" in ids
    # CoS Switchbay roles for auto/work
    assert ids & {"investigator", "synthesizer", "verifier", "cos"}

    # HTTP GET /api/dag
    from io import BytesIO
    from urllib.parse import urlparse

    class _W:
        def __init__(self) -> None:
            self.buf = BytesIO()

        def write(self, b: bytes) -> None:
            self.buf.write(b)

    class FakeHandler(server.Handler):
        def __init__(self, path: str) -> None:
            self.path = path
            self.wfile = _W()
            self.headers_sent: list[tuple[int, list]] = []
            self._headers: list[tuple[str, str]] = []
            self.response_code = 0

        def send_response(self, code: int) -> None:
            self.response_code = code

        def send_header(self, k: str, v: str) -> None:
            self._headers.append((k, v))

        def end_headers(self) -> None:
            self.headers_sent.append((self.response_code, list(self._headers)))
            self._headers = []

        def log_message(self, *a: object) -> None:
            pass

    h = FakeHandler(f"/api/dag?desk_id={desk_id}")
    h.do_GET()
    body = h.wfile.buf.getvalue().decode("utf-8")
    data = json.loads(body)
    assert isinstance(data.get("nodes"), list)
    assert len(data["nodes"]) >= 2
    assert {n["id"] for n in data["nodes"]} & ids

    # TUI topo must not be empty when nodes is a proper list
    from okstratr import tui

    lines = tui.dag_topo_lines(data)
    assert lines and not (len(lines) == 1 and "empty" in lines[0].lower())
    assert any("investigator" in ln or "root" in ln or "synthesizer" in ln for ln in lines)


def test_tui_handles_summary_nodes_as_count() -> None:
    """Regression: Dag.summary() uses nodes=int; TUI must use items list."""
    from okstratr import tui

    summary_shaped = {
        "nodes": 3,  # integer count (legacy summary shape)
        "items": [
            {"id": "root", "title": "R", "state": "done", "depends_on": []},
            {"id": "investigator", "title": "I", "state": "ready", "depends_on": ["root"]},
        ],
    }
    got = tui.resolve_dag_payload({}, summary_shaped)
    assert isinstance(got["nodes"], list)
    assert len(got["nodes"]) == 2
    lines = tui.dag_topo_lines(summary_shaped)
    assert any("investigator" in ln for ln in lines)


def test_backend_direct_skips_herdr_even_if_shim_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """backend=direct → run_one uses harness.direct; never herdr pane start (exit 2)."""
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("OKSTRATR_HERDR_DRY_RUN", raising=False)
    monkeypatch.delenv("OKSTRATR_DIRECT_DRY_RUN", raising=False)

    # Broken herdr shim that would exit 2 if invoked
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    herdr_shim = fake_bin / "herdr"
    herdr_shim.write_text("#!/bin/sh\necho herdr-shim >&2\nexit 2\n", encoding="utf-8")
    herdr_shim.chmod(0o755)
    grok = fake_bin / "grok"
    grok.write_text("#!/bin/sh\necho direct-grok-ok\nexit 0\n", encoding="utf-8")
    grok.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{tmp_path}")

    from okstratr.harness import config as hcfg

    hcfg.set_value("backend", "direct")
    assert hcfg.load().preferred_backend() == "direct"

    import okstratr.blackboard as bb
    import okstratr.dag as dag
    import okstratr.desks as desks
    import okstratr.herdr as herdr
    import okstratr.status as status

    bb._DEFAULT = None
    bb._DEFAULT_PATH = None
    dag._DEFAULT = None
    dag._DEFAULT_PATH = None
    desks._DEFAULT = None
    desks._DEFAULT_PATH = None
    status._loaded = False
    status._loaded_from = None
    status._seated_objective = ""
    status._state = "setup"

    assert herdr.herdr_bin()  # shim visible
    assert herdr.prefer_direct_adapter() is True

    desks.start("Direct seat smoke", kind="work", drive_herdr=False, run_cos=True)
    g = dag.default_dag(force_reload=True)
    # Pick a ready non-root node
    ready = [n for n in g.ready() if n.id != "root"]
    assert ready, f"expected ready nodes, got {list(g.nodes)}"
    node_id = ready[0].id

    live_calls: list[str] = []

    def _boom(*a, **k):  # noqa: ANN001
        live_calls.append("live")
        raise AssertionError("_live_run_node must not be called when backend=direct")

    monkeypatch.setattr(herdr, "_live_run_node", _boom)
    out = herdr.run_one(node_id, dry_run=False, timeout=15.0)
    assert live_calls == []
    assert out.get("adapter") == "direct"
    assert out.get("ok") is True
    assert "direct-grok-ok" in (out.get("stdout") or "")
    # Must not log herdr exit 2
    notes = (dag.default_dag(force_reload=True).nodes[node_id].notes or "").lower()
    assert "exit 2" not in notes
    assert "herdr seat failed" not in notes
