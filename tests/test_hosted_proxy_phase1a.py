"""Phase 1a: hosted mode, public base proxy prefix, registry SSOT."""

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
def http_server(env: Path, monkeypatch: pytest.MonkeyPatch):
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


def _json(hostport: str, path: str) -> dict:
    code, _h, body = _get(hostport, path, headers={"Accept": "application/json"})
    assert code == 200, (code, body[:200])
    return json.loads(body.decode())


# —— public_base helpers ——


def test_strip_public_base(monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr.public_base import public_base, strip_public_base

    monkeypatch.delenv("OKSTRATR_PUBLIC_BASE", raising=False)
    assert public_base() == ""
    assert strip_public_base("/observer/") == "/observer/"

    monkeypatch.setenv("OKSTRATR_PUBLIC_BASE", "/embed/okstratr")
    assert public_base() == "/embed/okstratr"
    assert strip_public_base("/embed/okstratr/health") == "/health"
    assert strip_public_base("/embed/okstratr/observer/") == "/observer/"
    assert strip_public_base("/embed/okstratr") == "/"
    assert strip_public_base("/health") == "/health"


def test_hosted_shell_from_request() -> None:
    from okstratr.public_base import hosted_shell_from_request

    assert hosted_shell_from_request({"X-Okstratr-Host": "switchbay"}) == "switchbay"
    assert hosted_shell_from_request({"x-okstratr-host": "okbay"}) == "okbay"
    assert hosted_shell_from_request({}, {"host": ["switchbay"]}) == "switchbay"
    assert hosted_shell_from_request({"X-Okstratr-Host": "other"}) is None
    assert hosted_shell_from_request({}, {"host": ["nope"]}) is None
    # Header wins over query
    assert (
        hosted_shell_from_request(
            {"X-Okstratr-Host": "okbay"}, {"host": ["switchbay"]}
        )
        == "okbay"
    )


# —— HTTP: hosted mode injects bootstrap ——


def test_observer_hosted_query_injects_bootstrap(http_server: str) -> None:
    code, headers, body = _get(http_server, "/observer/?host=switchbay")
    assert code == 200
    text = body.decode("utf-8")
    assert 'window.OKSTRATR_HOSTED="switchbay"' in text
    assert headers.get("x-okstratr-hosted") == "switchbay"
    # Desks / blackboard markup still present
    assert "desk-rail" in text
    assert "dag-graph" in text or "agent-space" in text
    assert "blackboard" in text
    assert 'id="settings-panel"' in text or 'class="config"' in text


def test_observer_hosted_header_injects_bootstrap(http_server: str) -> None:
    code, headers, body = _get(
        http_server,
        "/observer/",
        headers={"X-Okstratr-Host": "okbay"},
    )
    assert code == 200
    text = body.decode("utf-8")
    assert 'window.OKSTRATR_HOSTED="okbay"' in text
    assert headers.get("x-okstratr-hosted") == "okbay"


def test_observer_bare_no_hosted(http_server: str) -> None:
    code, headers, body = _get(http_server, "/observer/")
    assert code == 200
    text = body.decode("utf-8")
    assert 'window.OKSTRATR_HOSTED=""' in text
    assert "x-okstratr-hosted" not in headers


# —— HTTP: public base prefix ——


def test_proxy_prefix_health_and_observer(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OKSTRATR_PUBLIC_BASE", "/embed/okstratr")
    from okstratr import server

    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    hostport = f"127.0.0.1:{port}"
    try:
        health = _json(hostport, "/embed/okstratr/health")
        assert health.get("ok") is True
        assert health.get("service") == "okstratr"

        # Unprefixed still works (local / bare installs)
        health2 = _json(hostport, "/health")
        assert health2.get("ok") is True

        code, headers, body = _get(
            hostport, "/embed/okstratr/observer/?host=switchbay"
        )
        assert code == 200
        text = body.decode("utf-8")
        assert 'window.OKSTRATR_PUBLIC_BASE="/embed/okstratr"' in text
        assert 'window.OKSTRATR_API="/embed/okstratr"' in text
        assert 'window.OKSTRATR_HOSTED="switchbay"' in text
        assert headers.get("x-okstratr-public-base") == "/embed/okstratr"

        api = _json(hostport, "/embed/okstratr/api/harness")
        assert api.get("ok") is True
    finally:
        httpd.shutdown()
        httpd.server_close()


# —— Registry SSOT ——


def test_registry_includes_switchbay_rail(env: Path) -> None:
    from okstratr.harness import registry
    from okstratr.harness import config as hcfg

    assert registry.get("switchbay-rail") is not None
    assert "switchbay-rail" in registry.DEFAULT_PREFERENCE
    ids = [h.id for h in registry.list_defs()]
    assert "switchbay-rail" in ids
    assert "grok" in ids

    payload = hcfg.list_for_api()
    assert payload["ok"] is True
    row = next(r for r in payload["harnesses"] if r["id"] == "switchbay-rail")
    assert row["label"]
    assert "Switchbay" in row["notes"] or "shell" in row["notes"].lower() or "rail" in row["notes"].lower()
    # Not enabled by default — shells enable via API
    assert row["enabled"] is False


def test_shells_configure_registry_via_api(http_server: str) -> None:
    """Shells write okstratr registry through HTTP (SSOT), not a parallel allowlist."""
    listed = _json(http_server, "/api/harness")
    assert listed.get("ok") is True
    ids = {r["id"] for r in listed["harnesses"]}
    assert "switchbay-rail" in ids
    assert "grok" in ids

    conn = HTTPConnection(http_server, timeout=5)
    body = json.dumps({"id": "switchbay-rail"}).encode()
    conn.request(
        "POST",
        "/api/harness/enable",
        body=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    resp = conn.getresponse()
    data = json.loads(resp.read().decode())
    conn.close()
    assert resp.status == 200
    assert data.get("ok") is True
    assert "switchbay-rail" in data.get("enabled", [])
    row = next(r for r in data["harnesses"] if r["id"] == "switchbay-rail")
    assert row["enabled"] is True


def test_observer_js_has_hosted_hooks() -> None:
    from okstratr.lifecycle import observer_asset_dir

    root = observer_asset_dir()
    js = (root / "observer.js").read_text(encoding="utf-8")
    css = (root / "observer.css").read_text(encoding="utf-8")
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "detectHosted" in js
    assert "applyHostedMode" in js
    assert "OKSTRATR_HOSTED" in js
    assert "body.hosted" in css
    assert "settings-panel" in html
