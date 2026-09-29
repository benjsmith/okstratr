"""Phase 1b: desk dashboard stats/groupings in observer (Agents tab parity)."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("OKSTRATR_PUBLIC_BASE", raising=False)
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    from okstratr.harness import config as hcfg
    from okstratr.harness import select as sel

    sel.reset_rr()
    hcfg.save(hcfg.default_config())
    return state


@pytest.fixture()
def http_server(env: Path):
    from okstratr import server

    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def _get(
    hostport: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = HTTPConnection(hostport, timeout=5)
    hdrs = {"Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    conn.request("GET", path, headers=hdrs)
    resp = conn.getresponse()
    body = resp.read()
    out_headers = {k.lower(): v for k, v in resp.getheaders()}
    code = resp.status
    conn.close()
    return code, out_headers, body


def _json(hostport: str, path: str, method: str = "GET", body: dict | None = None) -> dict:
    conn = HTTPConnection(hostport, timeout=5)
    raw = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if raw is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=raw, headers=headers)
    resp = conn.getresponse()
    data = json.loads(resp.read().decode())
    code = resp.status
    conn.close()
    assert code == 200, (code, data)
    return data


def test_observer_includes_desk_dashboard_markup(http_server: str) -> None:
    code, _h, body = _get(http_server, "/observer/")
    assert code == 200
    text = body.decode("utf-8")
    assert 'id="desk-dashboard"' in text
    assert 'id="btn-quiet-all"' in text
    assert 'id="chip-desks"' in text
    assert 'id="chip-tokens"' in text
    assert 'id="chip-files"' in text
    assert 'id="desk-group-filter"' in text
    assert 'id="dash-by-kind"' in text
    assert 'id="dash-by-state"' in text
    # Still no persistent chat/query bar (modal edit textarea is OK)
    assert 'id="objective"' not in text
    assert 'id="edit-objective"' in text  # schedule/edit dialogs
    assert 'id="schedule-modal"' in text
    assert 'chat/objective input' in text or 'No chat' in text or 'Herdr' in text


def test_hosted_keeps_desk_dashboard_hides_settings(http_server: str) -> None:
    code, headers, body = _get(http_server, "/observer/?host=switchbay")
    assert code == 200
    text = body.decode("utf-8")
    assert 'window.OKSTRATR_HOSTED="switchbay"' in text
    assert headers.get("x-okstratr-hosted") == "switchbay"
    # Dashboard stats remain (Agents parity) even when settings strip is hosted-off
    assert 'id="desk-dashboard"' in text
    assert 'id="btn-quiet-all"' in text
    assert "desk-rail" in text
    assert "blackboard" in text
    assert 'id="settings-panel"' in text or 'class="config"' in text


def test_quiet_standing_api(http_server: str, env: Path) -> None:
    # Start a desk (dry-run herdr), then quiet all
    started = _json(
        http_server,
        "/api/desk/start",
        method="POST",
        body={"kind": "work", "objective": "phase1b quiet test"},
    )
    assert started.get("ok") is not False
    out = _json(http_server, "/api/desk/quiet_standing", method="POST", body={})
    assert out.get("ok") is not False
    assert out.get("action") == "quiet_standing" or "quiet" in str(out.get("message", "")).lower()


def test_lifecycle_exposes_desk_groupings(env: Path) -> None:
    from okstratr import desks, lifecycle

    reg = desks.default_registry(force_reload=True)
    reg.start(objective="groupings", kind="curate", drive_herdr=False)
    p = lifecycle.status_payload()
    assert "desks" in p
    assert "by_kind" in p["desks"]
    assert "by_state" in p["desks"]
    assert "tokens" in p
    assert "files" in p
    assert "files" in p["files"] and "lines" in p["files"]


def test_migration_doc_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    doc = root / "docs" / "MIGRATION-AGENT-DASHBOARD.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "Phase 1b" in text
    assert "no chat" in text.lower() or "No chat" in text
    assert "Quiet all" in text or "quiet_standing" in text

def test_by_state_omits_empty_placeholder_question_chip(env: Path) -> None:
    """Empty kind placeholders must not become by_state['?'] (mystery chip)."""
    from okstratr import desks, lifecycle

    reg = desks.default_registry(force_reload=True)
    # No real desks yet — standing rows are placeholders with empty state
    snap = reg.status_snapshot()
    standing = snap.get("standing") or []
    assert standing, "expected default standing placeholders"
    assert any(r.get("placeholder") or not r.get("state") for r in standing)

    p = lifecycle.status_payload()
    by_state = (p.get("desks") or {}).get("by_state") or {}
    assert "?" not in by_state
    assert "" not in by_state


def test_dag_at_rest_when_desk_quiet(env: Path) -> None:
    """Quiet desks keep last DAG structure but graph.idle / at_rest for UI."""
    from okstratr import desks
    from okstratr.dag import Dag, Node

    reg = desks.default_registry(force_reload=True)
    out = reg.start(objective="at rest graph", kind="auto", drive_herdr=False)
    desk_id = out.get("desk_id") or (out.get("desk") or {}).get("id")
    assert desk_id
    desk = reg.desks[desk_id]
    path = reg.dag_path_for(desk)
    g = Dag(path=path)
    if path.is_file():
        g.load()
    g.nodes["root"] = Node(id="root", title="root", role="cos", state="done", kind="root")
    g.nodes["worker-x"] = Node(
        id="worker-x",
        title="worker-x",
        role="investigator",
        state="running",
        depends_on=["root"],
    )
    g.save()
    reg.stop(desk_id)
    assert reg.desks[desk_id].state == "quiet"

    payload = desks.load_dag_for_api(desk_id)
    assert payload.get("at_rest") is True
    assert payload.get("desk_state") == "quiet"
    graph = payload.get("graph") or {}
    assert graph.get("idle") is True
    live = [
        n
        for n in (graph.get("nodes") or [])
        if isinstance(n, dict)
        and str(n.get("state") or "").lower()
        in ("running", "pending", "ready", "blocked", "working", "active", "busy")
    ]
    assert live == [], f"expected neutralized states, got {live}"


def test_switchbay_observer_hides_herdr_via_js_and_css(http_server: str) -> None:
    code, _h, body = _get(http_server, "/observer/?host=switchbay")
    assert code == 200
    text = body.decode("utf-8")
    # Markup still ships the button (okbay needs it); hosted JS/CSS strip it.
    assert 'id="open-herdr-workspace"' in text
    # Injected HTML defaults must already be Switchbay-neutral (no Herdr flash).
    assert "Select a desk to view the ongoing CoS conversation." in text
    assert "Select a desk to view ongoing CoS conversation in Herdr." not in text
    assert "Start the desk or open Herdr." not in text
    js_code, _jh, js_body = _get(http_server, "/observer/observer.js")
    assert js_code == 200
    js = js_body.decode("utf-8")
    assert "isSwitchbayHost" in js
    assert "currentHosted" in js
    assert "cosEmptyHtml" in js
    assert "ensureConversationHostCopy" in js
    assert "__okstratrObserverTeardown" in js
    # Sticky desk focus across poll / soft remount (selection/poll race fix).
    assert "focusSticky" in js
    assert "mountAlive" in js
    assert "mountIsLive" in js
    assert "detectPreferredDesk" in js
    assert "setFocusDesk" in js
    assert "clearFocusDesk" in js
    assert "okstratr.observer.focusDeskId" in js
    assert "open-herdr-workspace" in js
    assert "cosCopyNoDesk" in js
    assert "cosCopyNoTurns" in js
    assert "Select a desk to view the ongoing CoS conversation." in js
    assert "No CoS conversation yet for this desk. Start the desk." in js
    # Switchbay path must not bake Herdr into the neutral empty strings.
    assert 'return "Select a desk to view the ongoing CoS conversation.";' in js
    assert 'return "No CoS conversation yet for this desk. Start the desk.";' in js
    css_code, _ch, css_body = _get(http_server, "/observer/observer.css")
    assert css_code == 200
    css = css_body.decode("utf-8")
    assert 'data-okstratr-host="switchbay"' in css
    assert "open-herdr-workspace" in css

