"""Desk CoS conversation API + desk-scoped blackboard."""

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


def _get_text(hostport: str, path: str) -> str:
    conn = HTTPConnection(hostport, timeout=5)
    conn.request("GET", path, headers={"Accept": "*/*"})
    resp = conn.getresponse()
    body = resp.read().decode()
    code = resp.status
    conn.close()
    assert code == 200
    return body


def test_conversation_stub_and_herdr_transcript(env: Path, http_server: str) -> None:
    started = _json(
        http_server,
        "/api/desk/start",
        "POST",
        {"kind": "work", "objective": "Ship desk chrome", "drive_herdr": False},
    )
    desk = (started.get("desk") or {}).get("desk") or started.get("desk") or {}
    desk_id = str(desk.get("id") or started.get("desk_id") or "")
    assert desk_id

    stub = _json(http_server, f"/api/desk/conversation?desk_id={desk_id}")
    assert stub["ok"] is True
    assert stub["stub"] is True
    assert stub["source"] == "stub"
    assert any("Ship desk chrome" in str(m.get("text") or "") for m in stub["messages"])

    # Alias path
    alias = _json(http_server, f"/api/herdr/conversation?desk_id={desk_id}")
    assert alias["ok"] is True

    # Write a Herdr transcript and prefer it
    tdir = env / "desks" / desk_id
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "herdr_transcript.jsonl").write_text(
        json.dumps({"role": "user", "author": "human", "text": "hello cos"})
        + "\n"
        + json.dumps({"role": "assistant", "author": "cos", "text": "plan ready"})
        + "\n",
        encoding="utf-8",
    )
    live = _json(http_server, f"/api/desk/conversation?desk_id={desk_id}")
    assert live["stub"] is False
    assert live["source"] == "herdr_transcript"
    assert len(live["messages"]) == 2
    assert live["messages"][1]["author"] == "cos"


def test_blackboard_desk_scoped(env: Path, http_server: str) -> None:
    started = _json(
        http_server,
        "/api/desk/start",
        "POST",
        {"kind": "code", "objective": "scoped bb", "drive_herdr": False},
    )
    desk = (started.get("desk") or {}).get("desk") or started.get("desk") or {}
    desk_id = str(desk.get("id") or "")
    assert desk_id

    from okstratr import blackboard

    blackboard.post("noise for other desk", author="human", kind="note", tags=["other"])
    blackboard.post(
        "code claim for desk",
        author="cos",
        kind="decision",
        tags=["cos", "breakdown", "code", desk_id, f"desk:{desk_id}"],
    )

    scoped = _json(http_server, f"/api/blackboard?n=20&desk_id={desk_id}")
    texts = [str(i.get("text") or "") for i in scoped["items"]]
    assert any("code claim" in t for t in texts)
    assert scoped.get("desk_id") == desk_id


def test_observer_chrome_has_switcher_and_conversation(http_server: str) -> None:
    text = _get_text(http_server, "/observer/")
    assert 'id="context-switcher"' in text
    assert 'id="desk-switcher"' in text
    assert 'id="workspace-switcher"' in text
    assert 'id="conversation-panel"' in text
    assert 'id="conversation"' in text
    assert 'id="bb-desk-label"' in text
    # Still no persistent chat bar
    assert 'id="objective"' not in text
