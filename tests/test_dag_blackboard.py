"""Tests for persistent DAG + blackboard (OKSTRATR_STATE_DIR)."""

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
    # Force reload of singletons after env change
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


def test_dag_persist_ready_done(state_dir: Path) -> None:
    from okstratr.dag import Dag, default_dag, seat_root

    seat_root("Ship it")
    g = default_dag()
    assert "root" in g.nodes
    assert g.nodes["root"].state == "ready"
    assert g.nodes["root"].title == "Ship it"

    g.add("a", "A", depends_on=["root"])
    g.add("b", "B", depends_on=["a"])
    assert [n.id for n in g.ready()] == ["root"]
    assert g.nodes["a"].state == "pending"
    assert g.nodes["b"].state == "pending"

    g.mark_done("root")
    assert g.nodes["a"].state == "ready"
    assert "a" in [n.id for n in g.ready()]

    g.mark_done("a")
    assert g.nodes["b"].state == "ready"

    # Reload from disk
    g2 = Dag.open(state_dir / "dag.json")
    assert g2.nodes["root"].state == "done"
    assert g2.nodes["b"].state == "ready"
    assert (state_dir / "dag.json").is_file()


def test_dag_topo_and_cycle(state_dir: Path) -> None:
    from okstratr.dag import CycleError, Dag

    g = Dag.open(state_dir / "dag.json")
    g.add("x", "X")
    g.add("y", "Y", depends_on=["x"])
    g.add("z", "Z", depends_on=["y"])
    assert g.topo_order() == ["x", "y", "z"]

    g.add("bad", "Bad", depends_on=["z"])
    g.nodes["x"].depends_on = ["bad"]
    g.save()
    with pytest.raises(CycleError):
        g.topo_order()


def test_dag_seat_without_reset_keeps_nodes(state_dir: Path) -> None:
    from okstratr.dag import default_dag, seat_root

    seat_root("One")
    g = default_dag()
    g.add("keep", "Keep me", depends_on=["root"])
    seat_root("Two")  # no reset
    g = default_dag(force_reload=True)
    assert "keep" in g.nodes
    assert g.nodes["root"].title == "Two"

    seat_root("Fresh", reset=True)
    g = default_dag(force_reload=True)
    assert list(g.nodes.keys()) == ["root"]
    assert g.nodes["root"].title == "Fresh"


def test_dag_blocked_reasons_and_fail(state_dir: Path) -> None:
    from okstratr.dag import default_dag, seat_root

    seat_root("Obj")
    g = default_dag()
    g.add("child", "Child", depends_on=["root"])
    reasons = g.blocked_reasons("child")
    assert "child" in reasons
    assert any("root" in r for r in reasons["child"])

    g.mark_failed("root", notes="boom")
    assert g.nodes["root"].state == "failed"
    assert g.nodes["root"].notes == "boom"


def test_blackboard_post_search_clear(state_dir: Path) -> None:
    from okstratr import blackboard

    e = blackboard.post(
        "root is green",
        author="ben",
        kind="claim",
        tags=["desk", "qa"],
        node_id="root",
        provenance="manual",
    )
    assert e["kind"] == "claim"
    assert e["node_id"] == "root"
    assert (state_dir / "blackboard.jsonl").is_file()

    blackboard.post("just a note", kind="note")
    blackboard.post("ship it", kind="decision", tags=["ship"])

    hits = blackboard.search("green")
    assert len(hits) == 1
    assert hits[0]["kind"] == "claim"

    claims = blackboard.by_kind("claim")
    assert len(claims) == 1

    summ = blackboard.summary()
    assert summ["count"] == 3
    assert summ["by_kind"]["claim"] == 1

    # Persist across reload
    from okstratr.blackboard import Blackboard

    bb2 = Blackboard(state_dir / "blackboard.jsonl").reload()
    assert len(bb2.head(10)) == 3

    cleared = blackboard.clear()
    assert cleared["cleared"] is True
    assert cleared["count_before"] == 3
    assert blackboard.summary()["count"] == 0
    # archive should exist
    archives = list(state_dir.glob("blackboard.jsonl.archive.*"))
    assert len(archives) == 1


def test_cli_dag_bb(state_dir: Path) -> None:
    from okstratr.cli import main

    assert main(["seat", "CLI seat"]) == 0
    assert main(["dag", "add", "t1", "Task one", "--depends", "root"]) == 0
    assert main(["dag", "list"]) == 0
    assert main(["dag", "ready"]) == 0
    assert main(["dag", "done", "root"]) == 0
    assert main(["dag", "ready"]) == 0
    assert main(["bb", "post", "looks", "good", "--kind", "claim", "--node-id", "t1"]) == 0
    assert main(["bb", "head", "5"]) == 0
    assert main(["bb", "search", "good"]) == 0
    assert main(["status"]) == 0

    status = json.loads((state_dir / "status.json").read_text(encoding="utf-8"))
    assert status["objective"] == "CLI seat"
    assert status["dag"]["nodes"] >= 2
    assert status["blackboard"]["count"] >= 1


def test_http_dag_blackboard(state_dir: Path) -> None:
    from okstratr.server import Handler
    from http.server import ThreadingHTTPServer
    import threading
    import urllib.request

    from okstratr import dag

    dag.seat_root("HTTP seat")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"

        with urllib.request.urlopen(base + "/api/dag") as r:
            body = json.loads(r.read().decode())
        # /api/dag returns nodes as a list (TUI); node_count is the integer
        n = body.get("node_count")
        if n is None:
            nodes = body.get("nodes")
            n = len(nodes) if isinstance(nodes, list) else int(nodes or 0)
        assert n >= 1

        req = urllib.request.Request(
            base + "/api/dag/nodes",
            data=json.dumps(
                {"id": "h1", "title": "HTTP node", "depends_on": ["root"]}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            node = json.loads(r.read().decode())
        assert node["id"] == "h1"
        assert node["state"] == "pending"

        req = urllib.request.Request(
            base + "/api/dag/nodes/root/state",
            data=json.dumps({"state": "done"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            root = json.loads(r.read().decode())
        assert root["state"] == "done"

        with urllib.request.urlopen(base + "/api/dag") as r:
            body = json.loads(r.read().decode())
        assert "h1" in body["ready"]

        req = urllib.request.Request(
            base + "/api/blackboard",
            data=json.dumps(
                {
                    "text": "evidence from http",
                    "kind": "evidence",
                    "node_id": "h1",
                    "author": "test",
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            entry = json.loads(r.read().decode())
        assert entry["kind"] == "evidence"

        with urllib.request.urlopen(base + "/api/blackboard?kind=evidence") as r:
            bb = json.loads(r.read().decode())
        assert any(i.get("text") == "evidence from http" for i in bb["items"])

        with urllib.request.urlopen(base + "/api/status") as r:
            snap = json.loads(r.read().decode())
        assert "dag" in snap and "items" in snap["dag"]
        assert snap["blackboard"]["count"] >= 1
    finally:
        httpd.shutdown()
