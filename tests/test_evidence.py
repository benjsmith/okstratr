"""Per-run evidence store: candidates, verdicts, promotion."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(d))
    import okstratr.blackboard as bb

    bb._DEFAULT = None
    bb._DEFAULT_PATH = None
    return d


FINDINGS = """```json
{"findings": [
  {"claim": "A is true", "evidence": [{"source": "wiki/a.md", "kind": "wiki", "excerpt_or_fact": "A"}], "confidence": 0.8},
  {"claim": "B is true", "evidence": [], "confidence": 0.9}
]}
```"""


def _verify(ev, verdicts: dict[str, str], node_id: str = "verifier"):
    from okstratr import evidence

    rows = [{"finding_id": f.finding_id, "verdict": verdicts[f.claim]} for f in ev.unclassified_candidates()]
    rec = evidence.VerificationRecord(
        node_id=node_id,
        classifications=rows,
        confidence=0.8,
        unsupported=sum(1 for v in verdicts.values() if v != "supported"),
    )
    ev.append_verification(rec)


def test_parse_findings_and_candidates(state_dir: Path) -> None:
    from okstratr import evidence

    items = evidence.parse_findings(FINDINGS, node_id="investigator")
    assert [f.claim for f in items] == ["A is true", "B is true"]
    assert all(f.verdict == "candidate" for f in items)
    assert items[0].evidence[0].source == "wiki/a.md"
    ev = evidence.open_run("r1")
    ev.append_findings(items)
    assert len(ev.unclassified_candidates()) == 2


def test_each_run_has_its_own_store(state_dir: Path) -> None:
    from okstratr import evidence

    a = evidence.open_run("run-a")
    a.append_findings(evidence.parse_findings(FINDINGS, node_id="inv"))
    evidence.save_run(a)
    b = evidence.open_run("run-b")
    assert b.findings == []
    evidence.save_run(b)
    assert evidence.run_evidence_path("run-a").is_file()
    assert evidence.run_evidence_path("run-a").parent.parent == state_dir / "runs"
    again = evidence.open_run("run-a")
    assert [f.claim for f in again.findings] == ["A is true", "B is true"]
    assert set(evidence.list_runs()) == {"run-a", "run-b"}


def test_run_id_is_path_safe(state_dir: Path) -> None:
    from okstratr import evidence

    p = evidence.run_evidence_path("../../etc/passwd")
    assert (state_dir / "runs") in p.parents
    assert evidence.safe_run_id("") == "run"


def test_verification_appends_classified_sibling(state_dir: Path) -> None:
    from okstratr import evidence

    ev = evidence.open_run("r2")
    ev.append_findings(evidence.parse_findings(FINDINGS, node_id="inv"))
    _verify(ev, {"A is true": "supported", "B is true": "insufficient"})
    # candidates are kept; classified copies appended (append-only)
    assert len(ev.findings) == 4
    assert ev.unclassified_candidates() == []
    view = {f.claim: f.verdict for f in ev.synthesis_view()}
    assert view == {"A is true": "supported", "B is true": "insufficient"}


def test_only_supported_claims_reach_shared_blackboard(state_dir: Path) -> None:
    from okstratr import blackboard, evidence

    ev = evidence.open_run("r3")
    ev.append_findings(evidence.parse_findings(FINDINGS, node_id="inv"))
    # Before verification nothing is promotable.
    assert evidence.promote_supported(ev) == []
    _verify(ev, {"A is true": "supported", "B is true": "contradicted"})
    posted = evidence.promote_supported(ev, desk_id="d1")
    assert len(posted) == 1
    assert posted[0]["kind"] == "claim"
    assert posted[0]["text"].startswith("A is true")
    assert posted[0]["provenance"] == "okstratr.run:r3"
    assert "desk:d1" in posted[0]["tags"]
    # idempotent
    assert evidence.promote_supported(ev) == []
    texts = [r["text"] for r in blackboard.head(50)]
    assert not any(t.startswith("B is true") for t in texts)


def test_later_reverify_overrides_earlier_support(state_dir: Path) -> None:
    from okstratr import evidence

    ev = evidence.open_run("r4")
    ev.append_findings(evidence.parse_findings(FINDINGS, node_id="inv"))
    a = ev.findings[0]
    ev.append_verification(evidence.VerificationRecord(
        node_id="verifier", classifications=[{"finding_id": a.finding_id, "verdict": "supported"}],
    ))
    ev.append_verification(evidence.VerificationRecord(
        node_id="verify-x1", classifications=[{"finding_id": a.finding_id, "verdict": "contradicted"}],
    ))
    assert evidence.supported_findings(ev) == []


def test_compact_for_prompt_role_views(state_dir: Path) -> None:
    from okstratr import evidence

    ev = evidence.open_run("r5")
    ev.append_findings(evidence.parse_findings(FINDINGS, node_id="inv"))
    out = ev.compact_for_prompt(role="verify")
    assert "A is true" in out
    assert len(out) < 8000


def test_parse_verification_tolerates_junk(state_dir: Path) -> None:
    from okstratr import evidence

    rec = evidence.parse_verification("not json at all", node_id="v")
    assert rec.classifications == []
    rec2 = evidence.parse_verification(
        '{"classifications":[{"finding_id":"f1","verdict":"supported"}],"confidence":2,"conflicts":1}',
        node_id="v",
    )
    assert rec2.confidence == 1.0
    assert rec2.conflicts == 1


def test_corrupt_run_file_starts_empty(state_dir: Path) -> None:
    from okstratr import evidence

    p = evidence.run_evidence_path("bad")
    p.parent.mkdir(parents=True)
    p.write_text("{nope", encoding="utf-8")
    ev = evidence.open_run("bad")
    assert ev.findings == [] and ev.orchestration_id == "bad"
