"""Live desks run the kernel one seat at a time through okstratr.live.

Desks never use ``run_plan`` (the in-process scheduler); each seat's result
comes from ``okstratr findings add``, never from pane text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from okstratr import orchestration as orch


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    cfg = tmp_path / "cfg"
    state.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(state))
    monkeypatch.setenv("OKSTRATR_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    for k in ("OKSTRATR_HOST", "OKSTRATR_HOST_DONE", "HERDR_HOME", "OKSTRATR_HERDR_HOME"):
        monkeypatch.delenv(k, raising=False)
    from okstratr import dag

    dag._DEFAULT = None
    dag._DEFAULT_PATH = None
    return state


OBJ = "Compare the evidence on remote work across sources; which claims disagree and why?"


@pytest.mark.parametrize("kind", ["auto", "work"])
def test_live_desk_never_runs_the_in_process_scheduler(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    from okstratr import dag, desks, herdr

    def boom(*a, **k):
        raise AssertionError("run_plan used on a live desk")

    monkeypatch.setattr(orch, "run_plan", boom)
    desks.start(OBJ, kind=kind)
    g = dag.default_dag(force_reload=True)
    assert len(g.nodes) > 1
    out = herdr.run_ready(limit=1, dry_run=True)
    assert out["dry_run"] is True and out["ran"]


def _plan_nodes(g):
    return [n for n in g.nodes.values() if getattr(n, "plan_node_id", None) and getattr(n, "run_id", None)]


@pytest.mark.parametrize("met", [True, False])
def test_desk_seats_feed_the_kernel_through_findings(monkeypatch: pytest.MonkeyPatch, met: bool) -> None:
    from okstratr import dag, desks, handback, herdr
    from okstratr import evidence as ev

    desks.start(OBJ, kind="auto")
    g = dag.default_dag(force_reload=True)
    seats = _plan_nodes(g)
    assert seats, "desk nodes carry run_id and plan_node_id"
    rid = seats[0].run_id
    prompt = herdr._node_prompt(seats[0]) if hasattr(herdr, "_node_prompt") else ""
    if prompt:
        assert f"okstratr findings add --run {rid} --node {seats[0].plan_node_id}" in prompt

    filed: set[str] = set()
    for _ in range(12):
        g = dag.default_dag(force_reload=True)
        for n in _plan_nodes(g):
            if n.plan_node_id in filed:
                continue
            filed.add(n.plan_node_id)
            nt = n.plan_node_id
            if nt.startswith("verif"):
                store = ev.open_run(rid)
                payload = {"classifications": [{"finding_id": f.finding_id, "verdict": "supported"}
                                               for f in store.candidates()]}
            elif nt.startswith("synth"):
                payload = {"answer": "remote work: mixed evidence", "objective_met": met,
                           "gap": "" if met else "no source on productivity"}
            else:
                payload = {"findings": [{"claim": f"claim {nt}", "evidence": [{"source": f"{nt}.md"}],
                                         "confidence": 0.7}]}
            handback.add(payload, run_id=rid, node_id=n.plan_node_id, post=False)
        out = herdr.run_ready(limit=4, dry_run=True)
        if not out.get("ran"):
            break
    kernel = (ev.run_dir(rid) / "live.json")
    assert kernel.exists()
    store = ev.open_run(rid)
    assert store.findings, "findings filed by seats reached the evidence store"
    import json

    live = json.loads(kernel.read_text(encoding="utf-8"))
    assert {"inv-0", "inv-1", "verify", "synth"} <= set(live["state"]["results"])
    decisions = live["kernel"]["host_decisions"]
    first = decisions[0]
    if met:
        assert first["action"] in ("stop", "respect")
    else:
        # The desk's host said done, okstratr's evidence says not: override, recorded.
        assert first["action"] == "continue" and first["override"]
        assert "no source on productivity" in first["reason"]
        from okstratr import blackboard

        posts = [e for e in blackboard.Blackboard().by_kind("decision") if "host-done" in (e.get("tags") or [])]
        assert posts and any("override" in e["tags"] for e in posts)
        assert (ev.run_dir(rid) / "decisions.jsonl").exists()


def test_docs_describe_where_the_kernel_runs() -> None:
    root = Path(__file__).resolve().parents[1]
    assert "okstratr.live" in (orch.__doc__ or "")
    assert "findings add" in (orch.__doc__ or "")
    assert "Offline only" not in (root / "README.md").read_text(encoding="utf-8")
    kernel = (root / "docs" / "DESK-KERNEL.md").read_text(encoding="utf-8")
    assert "Where the kernel runs" in kernel and "findings add" in kernel
