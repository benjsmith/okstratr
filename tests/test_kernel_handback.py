"""Findings handback, host-done rules, the file queue and the time-boxed loop."""

from __future__ import annotations

import json
import threading
import time

import pytest

from okstratr import evidence as ev
from okstratr import handback
from okstratr import host_profile as hp
from okstratr import kernel_run as kr
from okstratr import orchestration as orch
from okstratr.harness import queue as q


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path / "state"))
    for k in ("OKSTRATR_HOST", "OKSTRATR_HOST_DONE", "HERDR_HOME", "OKSTRATR_HERDR_HOME",
              "OKSTRATR_SWITCHBAY_URL", "SWITCHBAY_SESSION", "OKSTRATR_RUN_ID",
              "OKSTRATR_PLAN_NODE_ID", "OKSTRATR_NODE_ID"):
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------- handback


def test_add_merges_and_posts_to_blackboard():
    from okstratr import blackboard

    a = {"findings": [{"claim": "A is true", "evidence": [{"source": "a.md"}], "confidence": 0.8}]}
    b = {"findings": [{"claim": "a is  TRUE", "confidence": 0.9}, {"claim": "B", "confidence": 0.5}],
         "checks": [{"name": "pytest", "passed": False}]}
    handback.add(a, run_id="r1", node_id="inv-1")
    out = handback.add(b, run_id="r1", node_id="inv-1")
    assert out["findings"] == 2  # duplicate claim folded
    data = handback.read("r1", "inv-1")
    assert handback.failing_checks(data) == 1
    posts = [e for e in blackboard.Blackboard().by_kind("evidence")
             if e.get("provenance") == "okstratr.findings:r1"]
    assert len(posts) == 2 and "candidate" in posts[0]["tags"] and "run:r1" in posts[0]["tags"]
    text = handback.result_text("investigate", data)
    assert json.loads(text)["findings"][0]["claim"] == "A is true"


def test_read_falls_back_to_blackboard(tmp_path):
    handback.add({"answer": "x", "objective_met": "yes"}, run_id="r2", node_id="synth")
    handback.handback_path("r2", "synth").unlink()
    data = handback.read("r2", "synth")
    assert data and data["objective_met"] is True
    assert "OBJECTIVE_MET: yes" in handback.result_text("synthesize", data)


def test_instructions_name_run_and_node():
    s = handback.instructions("r9", "verifier", "verify")
    assert "okstratr findings add --run r9 --node verifier" in s
    assert "okstratr findings show --run r9" in s and "--file" in s


# ---------------------------------------------------------------- host profiles


def test_profile_defaults_config_and_env(tmp_path):
    class Cfg:
        def settings_for(self, hid):
            return type("S", (), {"settings": {"done": "tests"} if hid == "codex" else {}})()

    assert hp.profile_for("claude", cfg=Cfg(), env={}).stop_rule == "first_answer"
    p = hp.profile_for("codex", cfg=Cfg(), env={})
    assert (p.stop_rule, p.source) == ("tests", "harnesses.toml")
    p = hp.profile_for("codex", cfg=Cfg(), env={"OKSTRATR_HOST_DONE": "codex=verified"})
    assert (p.stop_rule, p.source) == ("verified", "OKSTRATR_HOST_DONE")
    assert hp.detect_host({"HERDR_HOME": "/x"}) == "herdr"
    assert hp.detect_host({"OKSTRATR_SWITCHBAY_URL": "http://x"}) == "switchbay"
    assert hp.detect_host({}) == "cli"


def _decide(rule, **kw):
    prof = hp.HostProfile(harness="h", stop_rule=rule)
    return hp.decide_done(prof, okstratr_strength=hp.strength_rank("verified"), **kw)


def test_respect_when_host_rule_is_as_strong():
    d = _decide("verified", objective_met=True, verified=False)
    assert d.action == "respect" and not d.override


def test_override_when_host_is_weaker_and_gaps_remain():
    d = _decide("first_answer", objective_met=False, gap="no tests for b.py", verified=True)
    assert d.action == "continue" and d.override and "no tests for b.py" in d.reason
    d = _decide("tests", objective_met=True, failing_checks=2, verified=True)
    assert d.action == "continue" and "2 failing check" in d.reason


def test_weak_host_unverified_gets_a_verify_round():
    d = _decide("first_answer", objective_met=True, verified=False, preference=0.6, consequence=0.5)
    assert d.action == "verify" and d.override


def test_time_boxed_owner_loop_and_deadline():
    d = _decide("verified", objective_met=None, owner_loop=True, budget=hp.Budget(deadline=time.time() + 60))
    assert d.action == "continue" and d.override
    d = _decide("verified", objective_met=None, owner_loop=True, budget=hp.Budget(deadline=time.time() - 1))
    assert (d.action, d.reason) == ("stop", "time box reached")
    d = _decide("verified", objective_met=True, owner_loop=True)
    assert (d.action, d.reason) == ("stop", "objective met")


def test_budget_exhausted_stops_continuation():
    b = hp.Budget(max_tokens=1000, spent_tokens=1000)
    d = _decide("first_answer", objective_met=False, gap="x", verified=True, budget=b)
    assert (d.action, d.reason) == ("stop", "budget exhausted")


# ---------------------------------------------------------------- queue adapter


def _seat_reply(run_id: str, meta: dict, *, met: bool = True, fail_checks: bool = False) -> dict:
    t = meta["node_type"]
    nid = meta["node_id"]
    if t == "verify":
        store = ev.open_run(run_id)
        return {"classifications": [{"finding_id": f.finding_id, "verdict": "supported"}
                                    for f in store.candidates()], "confidence": 0.9}
    if t == "synthesize":
        return {"answer": "done", "objective_met": met, "gap": "" if met else "part B missing"}
    out = {"findings": [{"claim": f"claim from {nid}", "evidence": [{"source": f"{nid}.md"}],
                         "confidence": 0.8}]}
    if fail_checks:
        out["checks"] = [{"name": "pytest", "passed": False}]
    return out


class FakeHost:
    """Plays the parent agent: runs every queued seat, files findings, signals done."""

    def __init__(self, **reply_kw):
        self.reply_kw = reply_kw
        self.stop = threading.Event()
        self.seen: list[str] = []
        self.t = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self.stop.is_set():
            for m in q.list_seats(state="queued"):
                rid, nid = m["run_id"], m["node_id"]
                q.claim(rid, nid, by="fake")
                prompt = q.show(rid, nid)["prompt_text"]
                assert f"--run {rid} --node {nid}" in prompt
                handback.add(_seat_reply(rid, m, **self.reply_kw), run_id=rid, node_id=nid, post=False)
                q.done(rid, nid, tokens=500)
                self.seen.append(nid)
            time.sleep(0.01)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *a):
        self.stop.set()
        self.t.join(timeout=2)


def test_queue_runner_runs_a_plan_through_an_outside_host():
    with FakeHost() as host:
        out = kr.run_once(
            "Compare the retry logic in a.py and b.py and say which is safer.",
            kr.queue_runner_factory(poll_s=0.01, timeout_s=10),
            run_id="qrun", recipe="ivs_diverse_2", effort=0.5, harnesses=["claude", "codex"],
            host=hp.HostProfile(harness="claude", stop_rule="verified"), learn=False,
        )
    assert out["answer"].startswith("done")
    assert out["objective_met"] is True
    assert out["tokens"] == 500 * len(host.seen)
    assert any(n.startswith("verif") or "verify" in n for n in host.seen)
    assert out["host_decisions"] and out["host_decisions"][-1]["action"] == "respect"
    # The verifier read real finding ids, so the store has supported findings.
    assert ev.supported_findings(ev.open_run("qrun"))


def test_queue_seat_without_done_times_out():
    runner = q.QueueRunner("qt", poll_s=0.01, timeout_s=0.05)
    node = orch.PlanNode("inv", "investigate", "x")
    res = runner(node, {})
    assert not res.ok and res.error == "queue timeout"
    assert q.list_seats("qt")[0]["state"] == "queued"


def test_queue_done_is_the_only_completion_signal():
    node = orch.PlanNode("inv", "investigate", "x")
    q.enqueue("qd", node, "prompt")
    handback.add({"findings": [{"claim": "c"}]}, run_id="qd", node_id="inv", post=False)
    assert q.list_seats("qd")[0]["state"] == "queued"  # filing findings is not done
    q.claim("qd", "inv")
    with pytest.raises(ValueError):
        q.claim("qd", "inv")
    m = q.done("qd", "inv", tokens=7)
    assert m["state"] == "done" and m["handback"] is True
    with pytest.raises(ValueError):
        q.done("qd", "inv")


# ---------------------------------------------------------------- time-boxed loop


def test_loop_stops_on_objective_met_with_checkpoint():
    with FakeHost():
        loop = kr.run_loop(
            "Summarise the incident notes.", kr.queue_runner_factory(poll_s=0.01, timeout_s=10),
            run_id="loop1", for_seconds=600, recipe="single", harnesses=["claude"],
        )
    assert loop["stop_reason"] == "objective met"
    saved = json.loads((ev.run_dir("loop1") / "loop.json").read_text())
    assert saved["stop_reason"] == "objective met" and len(saved["rounds"]) == 1
    lines = (ev.run_dir("loop1") / "decisions.jsonl").read_text().strip().splitlines()
    assert json.loads(lines[-1])["reason"] == "objective met"


def test_loop_overrides_unmet_rounds_then_stops_on_no_progress():
    with FakeHost(met=False):
        loop = kr.run_loop(
            "Write the migration and its tests.", kr.queue_runner_factory(poll_s=0.01, timeout_s=10),
            run_id="loop2", for_seconds=600, recipe="single", harnesses=["claude"], max_rounds=4,
        )
    # Same claims every round → the second round adds nothing new.
    assert loop["stop_reason"].startswith("no progress")
    assert len(loop["rounds"]) == 2
    assert any(d["override"] for d in loop["rounds"][0]["host_decisions"])
    assert "part B missing" in loop["rounds"][0]["host_decisions"][0]["reason"]


def test_loop_time_box_reached_before_a_round():
    ticks = iter([1000.0, 1061.0, 1062.0, 1063.0])
    loop = kr.run_loop("x", kr.queue_runner_factory(), run_id="loop3", for_seconds=60,
                       clock=lambda: next(ticks))
    assert loop["stop_reason"] == "time box reached" and loop["rounds"] == []


def test_loop_budget_exhausted():
    with FakeHost(met=False):
        loop = kr.run_loop(
            "Write the migration.", kr.queue_runner_factory(poll_s=0.01, timeout_s=10),
            run_id="loop4", max_tokens=100, recipe="single", harnesses=["claude"],
            host=hp.HostProfile(harness="claude"),
        )
    assert loop["stop_reason"] == "budget exhausted"
    assert len(loop["rounds"]) == 1  # one 500-token seat already spent the 100-token budget


# ---------------------------------------------------------------- CLI


def test_cli_findings_and_queue_roundtrip(capsys):
    from okstratr.cli import main

    assert main(["findings", "add", "--run", "c1", "--node", "n1", "--no-post",
                 "--json", '{"findings": [{"claim": "x"}]}']) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == 1
    assert main(["findings", "list", "--run", "c1"]) == 0
    assert json.loads(capsys.readouterr().out)["nodes"] == ["n1"]
    q.enqueue("c1", orch.PlanNode("n1", "investigate", "x"), "hello")
    assert main(["queue", "claim", "c1", "n1"]) == 0
    capsys.readouterr()
    assert main(["queue", "done", "c1", "n1", "--tokens", "9"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "done"
    assert main(["host-profile", "codex"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["harness"] == "codex"


def test_parse_duration():
    from okstratr.cli_kernel import parse_duration

    assert parse_duration("90") == 90
    assert parse_duration("1h30m") == 5400
    with pytest.raises(ValueError):
        parse_duration("soon")
