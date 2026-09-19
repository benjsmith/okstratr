"""Desk-rail Start/Stop/Dismiss/Delete (+ Quiet) → API mapping + handlers."""

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


def _get(hostport: str, path: str, *, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    conn = HTTPConnection(hostport, timeout=5)
    hdrs = {"Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    conn.request("GET", path, headers=hdrs)
    resp = conn.getresponse()
    body = resp.read()
    code = resp.status
    conn.close()
    return code, body


# —— Pure mapping ——


def test_request_for_start_stop_dismiss_delete_quiet() -> None:
    from okstratr.desk_rail import request_for

    start = request_for("start", kind="work", objective="ship it")
    assert start["method"] == "POST"
    assert start["path"] == "/api/desk/start"
    assert start["body"]["kind"] == "work"
    assert start["body"]["objective"] == "ship it"
    assert start["body"]["drive_herdr"] is True

    cont = request_for("start", kind="code", desk_id="desk-abc", objective="")
    assert cont["body"]["desk_id"] == "desk-abc"
    assert cont["body"].get("drive_herdr") is not True

    stop = request_for("stop", desk_id="desk-1")
    assert stop["path"] == "/api/desk/stop"
    assert stop["body"] == {"desk_id": "desk-1"}

    dismiss = request_for("dismiss", desk_id="desk-1")
    assert dismiss["path"] == "/api/desk/dismiss"

    delete = request_for("delete", desk_id="desk-1")
    assert delete["path"] == "/api/desk/delete"

    quiet = request_for("quiet_all")
    assert quiet["path"] == "/api/desk/quiet_standing"
    assert quiet["body"] == {}
    assert request_for("quiet_standing")["path"] == quiet["path"]


def test_request_for_rejects_placeholder_desk_id() -> None:
    from okstratr.desk_rail import request_for

    with pytest.raises(ValueError, match="real desk_id"):
        request_for("stop", desk_id="kind:work")
    with pytest.raises(ValueError, match="requires desk_id"):
        request_for("dismiss")


def test_row_actions_and_labels() -> None:
    from okstratr.desk_rail import row_actions, start_label

    assert row_actions("working") == ["start", "stop", "dismiss"]
    assert row_actions("quiet") == ["start", "stop", "dismiss"]
    assert row_actions("dismissed") == ["start", "stop", "delete"]
    assert "start" in row_actions(None, placeholder=True)
    assert start_label("quiet") == "Continue"
    assert start_label("dismissed") == "Start"
    assert start_label(None, placeholder=True) == "Start"


def test_hosted_shell_helpers() -> None:
    from okstratr.desk_rail import HOSTED_SHELLS, SWITCHBAY_ONLY_CHROME, is_hosted_shell

    assert is_hosted_shell("switchbay")
    assert is_hosted_shell("okbay")
    assert not is_hosted_shell("bare")
    assert "switchbay" in HOSTED_SHELLS
    assert any("Schedule" in s for s in SWITCHBAY_ONLY_CHROME)
    assert any("transcript" in s.lower() or "Active-run" in s for s in SWITCHBAY_ONLY_CHROME)


def test_observer_js_matches_desk_rail_paths() -> None:
    from okstratr.desk_rail import observer_paths
    from okstratr.lifecycle import observer_asset_dir

    js = (observer_asset_dir() / "observer.js").read_text(encoding="utf-8")
    html = (observer_asset_dir() / "index.html").read_text(encoding="utf-8")
    for path in observer_paths():
        # quiet-all alias may only live on server; primary path must be in JS
        if path == "/api/desk/quiet-all":
            continue
        assert path in js, path
    assert 'data-act="start"' in js
    assert 'data-act="stop"' in js
    assert 'data-act="dismiss"' in js
    assert 'data-act="delete"' in js
    assert "desk_id" in js
    assert 'id="btn-quiet-all"' in html
    assert 'id="desk-rail"' in html


# —— HTTP handlers (reuse desks lifecycle) ——


def test_http_desk_rail_lifecycle(http_server: str, env: Path) -> None:
    started = _json(
        http_server,
        "/api/desk/start",
        method="POST",
        body={"kind": "work", "objective": "rail lifecycle"},
    )
    desk = (started.get("desk") or {}).get("desk") or started.get("desk") or {}
    # start response nests desk under desk.desk sometimes
    if "id" not in desk and isinstance(started.get("desk"), dict):
        desk = started["desk"].get("desk") or started["desk"]
    desk_id = desk.get("id")
    assert desk_id, started

    # Continue with desk_id (no new twin)
    again = _json(
        http_server,
        "/api/desk/start",
        method="POST",
        body={"kind": "work", "desk_id": desk_id, "objective": ""},
    )
    again_desk = again.get("desk") or {}
    if isinstance(again_desk.get("desk"), dict):
        again_desk = again_desk["desk"]
    assert again_desk.get("id") == desk_id

    # Drive working so Stop is meaningful
    from okstratr import desks

    reg = desks.default_registry(force_reload=True)
    d = reg.desks[desk_id]
    d.state = "working"
    reg.save()

    stopped = _json(
        http_server,
        "/api/desk/stop",
        method="POST",
        body={"desk_id": desk_id},
    )
    assert stopped.get("ok") is not False
    assert stopped.get("action") == "stop"
    assert (stopped.get("desk") or {}).get("state") == "quiet"

    dismissed = _json(
        http_server,
        "/api/desk/dismiss",
        method="POST",
        body={"desk_id": desk_id},
    )
    assert dismissed.get("action") == "dismiss"
    assert (dismissed.get("desk") or {}).get("state") == "dismissed"

    deleted = _json(
        http_server,
        "/api/desk/delete",
        method="POST",
        body={"desk_id": desk_id},
    )
    assert deleted.get("ok") is not False


def test_http_quiet_all_and_hosted_observer_keeps_rail(http_server: str, env: Path) -> None:
    _json(
        http_server,
        "/api/desk/start",
        method="POST",
        body={"kind": "curate", "objective": "quiet me", "drive_herdr": True},
    )
    out = _json(http_server, "/api/desk/quiet_standing", method="POST", body={})
    assert out.get("ok") is not False
    assert out.get("action") == "quiet_standing" or "quiet" in str(out).lower()

    code, body = _get(http_server, "/observer/?host=switchbay")
    assert code == 200
    text = body.decode("utf-8")
    assert 'window.OKSTRATR_HOSTED="switchbay"' in text
    assert 'id="desk-rail"' in text
    assert 'id="btn-quiet-all"' in text
    # Settings still in DOM but hosted mode hides them via JS/CSS
    assert 'id="settings-panel"' in text or 'class="config"' in text


def test_start_by_desk_id_resumes_same_desk(env: Path) -> None:
    from okstratr import desks

    reg = desks.default_registry(force_reload=True)
    first = reg.start(objective="keep me", kind="code", drive_herdr=False)
    desk_id = first["desk"]["id"]
    assert first["desk"]["state"] == "quiet"

    second = reg.start(objective="", kind="code", desk_id=desk_id, drive_herdr=False)
    assert second["action"] == "resume"
    assert second["desk"]["id"] == desk_id
