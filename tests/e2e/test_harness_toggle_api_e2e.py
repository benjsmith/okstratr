"""E2E: config toggle via HTTP harness API (Phase 3)."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest


@pytest.fixture()
def e2e_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    from okstratr.harness import config as hcfg
    from okstratr.harness import select as sel

    sel.reset_rr()
    hcfg.save(hcfg.default_config())
    return state


@pytest.fixture()
def http_server(e2e_env: Path, monkeypatch: pytest.MonkeyPatch):
    from okstratr import PORT, server

    # Bind ephemeral port
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    monkeypatch.setattr(server, "PORT", port, raising=False)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def _json(method: str, hostport: str, path: str, body: dict | None = None) -> dict:
    conn = HTTPConnection(hostport, timeout=5)
    raw = json.dumps(body or {}).encode() if body is not None or method != "GET" else None
    headers = {"Accept": "application/json"}
    if raw is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=raw, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode()
    conn.close()
    return json.loads(data) if data else {}


def test_harness_toggle_via_api(http_server: str) -> None:
    listed = _json("GET", http_server, "/api/harness")
    assert listed.get("ok") is True
    assert "grok" in listed.get("enabled", [])

    enabled = _json("POST", http_server, "/api/harness/enable", {"id": "claude"})
    assert enabled.get("ok") is True
    assert "claude" in enabled.get("enabled", [])
    row = next(r for r in enabled["harnesses"] if r["id"] == "claude")
    assert row["enabled"] is True

    disabled = _json("POST", http_server, "/api/harness/disable", {"id": "claude"})
    assert "claude" not in disabled.get("enabled", [])

    status = _json("GET", http_server, "/api/status")
    assert "desk_session" in status
    assert status["desk_session"]["schema"].startswith("okstratr.desk_session")
    assert status.get("harness", {}).get("ok") is True

    session = _json("GET", http_server, "/api/desk_session")
    assert session.get("schema", "").startswith("okstratr.desk_session")
    assert isinstance(session.get("desks"), list)

    reloaded = _json("POST", http_server, "/api/harness/reload", {})
    assert reloaded.get("ok") is True
