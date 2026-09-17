"""E2E P4: HTTP status channel primary; FileView mirror matches desk_session."""

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
    from okstratr import server

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


def test_status_channel_http_primary_e2e(http_server: str, e2e_env: Path) -> None:
    from okstratr import desks, status

    desks.start("p4 e2e ssot", kind="work", drive_herdr=False)
    status.write_status()

    payload = _json("GET", http_server, "/api/status")
    ch = payload.get("status_channel") or {}
    assert ch.get("primary") == "GET /api/status"
    assert ch.get("dual_source") is False
    assert "desk_session" in payload
    assert payload["desk_session"]["schema"].startswith("okstratr.desk_session")

    session = _json("GET", http_server, "/api/desk_session")
    assert session.get("schema", "").startswith("okstratr.desk_session")
    assert session.get("desks") == payload["desk_session"].get("desks")

    mirror_path = status.status_path()
    assert mirror_path.is_file()
    mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
    assert mirror["desk_session"]["desks"] == payload["desk_session"]["desks"]


def test_harness_set_default_model_e2e(http_server: str) -> None:
    listed = _json("GET", http_server, "/api/harness")
    assert listed.get("ok") is True
    set_resp = _json(
        "POST",
        http_server,
        "/api/harness/set",
        {"key": "harness.grok.default_model", "value": "grok-4-p4"},
    )
    assert set_resp.get("ok") is True
    row = next(r for r in set_resp["harnesses"] if r["id"] == "grok")
    assert row["default_model"] == "grok-4-p4"
