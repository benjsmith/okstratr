"""Per-workspace model allow/deny lists."""

from __future__ import annotations

import http.client
import json
from pathlib import Path
from threading import Thread

import pytest


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    for k in ("OKSTRATR_WORKSPACE", "OKSTRATR_OKBAY_WORKSPACE", "OKSTRATR_HARNESS_PREFER",
              "OKSTRATR_MODEL_BY_HARNESS"):
        monkeypatch.delenv(k, raising=False)
    return state


def test_empty_policy_allows_everything(env: Path) -> None:
    from okstratr import model_policy as mp

    assert mp.is_allowed("claude", "claude-opus-4")
    assert mp.get("ws-a") == {"workspace": "ws-a", "inherited": True, "allowed": [], "denied": []}


def test_deny_wins_and_keys_match(env: Path) -> None:
    from okstratr import model_policy as mp

    mp.set_lists("ws-a", allowed=["claude/*", "gpt-5"], denied=["claude/claude-opus-4"])
    assert mp.is_allowed("claude", "claude-haiku", "ws-a")
    assert not mp.is_allowed("claude", "claude-opus-4", "ws-a")
    assert mp.is_allowed("codex", "gpt-5", "ws-a")  # bare model, any harness
    assert not mp.is_allowed("codex", "o3", "ws-a")  # not on the allow list
    assert not mp.is_allowed("grok", "grok-4", "ws-a")


def test_workspace_without_entry_inherits_global(env: Path) -> None:
    from okstratr import model_policy as mp

    mp.set_lists(None, denied=["grok/*"])
    assert not mp.is_allowed("grok", "grok-4", "ws-b")
    mp.set_lists("ws-b", denied=[])
    assert mp.is_allowed("grok", "grok-4", "ws-b")  # own (empty) entry overrides
    assert mp.reset("ws-b")["inherited"] is True
    assert not mp.is_allowed("grok", "grok-4", "ws-b")


def test_add_moves_between_lists_and_filter_pairs(env: Path) -> None:
    from okstratr import model_policy as mp

    mp.add("ws", "Claude/claude-opus-4", deny=False)
    out = mp.add("ws", "claude/claude-opus-4", deny=True)
    assert out["allowed"] == [] and out["denied"] == ["claude/claude-opus-4"]
    pairs = [("claude", "claude-opus-4"), ("claude", "claude-haiku"), ("grok", "grok-4")]
    assert mp.filter_pairs(pairs, "ws") == [("claude", "claude-haiku"), ("grok", "grok-4")]
    assert mp.remove("ws", "claude/claude-opus-4")["denied"] == []


def test_workspace_comes_from_active_desk_or_env(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import model_policy as mp

    assert mp.current_workspace_id() is None
    monkeypatch.setenv("OKSTRATR_WORKSPACE", "ws-env")
    assert mp.current_workspace_id() == "ws-env"


def test_cli_and_http(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from okstratr import model_policy as mp, server
    from okstratr.cli import main

    assert main(["model", "deny", "claude/claude-opus-4", "--ws", "ws-c"]) == 0
    assert json.loads(capsys.readouterr().out)["denied"] == ["claude/claude-opus-4"]
    assert main(["model", "policy", "--ws", "ws-c"]) == 0
    assert not mp.is_allowed("claude", "claude-opus-4", "ws-c")

    from http.server import ThreadingHTTPServer

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    t = Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
        conn.request("GET", "/api/models/policy?workspace=ws-c")
        body = json.loads(conn.getresponse().read().decode())
        assert body["denied"] == ["claude/claude-opus-4"]
        conn.request("POST", "/api/models/policy", body=json.dumps({"workspace": "ws-c", "allowed": ["grok/*"]}),
                     headers={"Content-Type": "application/json"})
        body = json.loads(conn.getresponse().read().decode())
        assert body["allowed"] == ["grok/*"] and body["denied"] == ["claude/claude-opus-4"]
        conn.request("POST", "/api/models/policy", body=json.dumps({"workspace": "ws-c", "denied": "x"}),
                     headers={"Content-Type": "application/json"})
        assert conn.getresponse().status == 400
    finally:
        httpd.shutdown()
