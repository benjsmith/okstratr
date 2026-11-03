"""Seat findings handback: how a seat's answer reaches the kernel.

A seat files its structured result with ``okstratr findings add`` for its
run and plan node. The result is written to
``state/runs/<run_id>/handback/<node_id>.json`` (one file per node, so
parallel seats never write the same file) and posted to the blackboard as
an ``evidence`` entry tagged ``findings`` and ``candidate``, so people and
other seats can see it. Candidate findings are not claims: only verified
findings are promoted to ``claim`` entries (``evidence.promote_supported``).

The kernel reads these files after the host says the seat is done. It never
reads pane text or seat transcripts, so the same path works under Herdr,
the direct adapter, the file queue, and a bare CLI.

Payload shapes (JSON object; several calls merge):

- investigator / executor / reducer: ``{"findings": [{"claim", "evidence":
  [{"source", "excerpt_or_fact"}], "confidence"}]}``; executors may add
  ``"checks": [{"name", "passed"}]`` (tests or commands they ran).
- verifier: ``{"classifications": [{"finding_id", "verdict"}],
  "confidence", "unresolved": [...]}``
- synthesizer: ``{"answer": "...", "objective_met": true|false, "gap": "..."}``
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import evidence as ev

PROVENANCE_PREFIX = "okstratr.findings:"
MAX_POST_CHARS = 6000


def handback_dir(run_id: str) -> Path:
    return ev.run_dir(run_id) / "handback"


def handback_path(run_id: str, node_id: str) -> Path:
    return handback_dir(run_id) / f"{ev.safe_run_id(node_id)}.json"


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    with lock.open("a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _load(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _merge(base: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    if isinstance(payload.get("findings"), list):
        seen = {" ".join(str(f.get("claim") or "").lower().split())
                for f in out.get("findings") or [] if isinstance(f, dict)}
        merged = list(out.get("findings") or [])
        for f in payload["findings"]:
            if isinstance(f, str):
                f = {"claim": f}
            if not isinstance(f, dict) or not str(f.get("claim") or "").strip():
                continue
            key = " ".join(str(f["claim"]).lower().split())
            if key in seen:
                continue
            seen.add(key)
            merged.append(f)
        out["findings"] = merged
    elif "claim" in payload:
        return _merge(base, {"findings": [payload]})
    if isinstance(payload.get("checks"), list):
        out["checks"] = list(out.get("checks") or []) + [
            c for c in payload["checks"] if isinstance(c, dict)
        ]
    for key in ("classifications", "confidence", "unresolved", "conflicts", "unsupported"):
        if key in payload:
            out[key] = payload[key]
    for key in ("answer", "gap"):
        if key in payload:
            out[key] = str(payload[key] or "")
    if "objective_met" in payload:
        v = payload["objective_met"]
        if isinstance(v, str):
            v = {"yes": True, "true": True, "no": False, "false": False}.get(v.strip().lower())
        out["objective_met"] = v if isinstance(v, bool) else None
    for key in ("tokens", "seconds"):
        if key in payload:
            try:
                out[key] = float(payload[key])
            except (TypeError, ValueError):
                pass
    return out


def kind_of(payload: dict[str, Any]) -> str:
    if "answer" in payload or "objective_met" in payload:
        return "synthesis"
    if "classifications" in payload or "unresolved" in payload:
        return "verification"
    return "findings"


def add(
    payload: dict[str, Any],
    *,
    run_id: str,
    node_id: str,
    author: str = "agent",
    post: bool = True,
) -> dict[str, Any]:
    """File one seat result for (run_id, node_id); merge with earlier calls."""
    if not isinstance(payload, dict):
        raise ValueError("findings payload must be a JSON object")
    rid = ev.safe_run_id(run_id)
    nid = str(node_id or "").strip()
    if not nid:
        raise ValueError("node id is required (OKSTRATR_NODE_ID or --node)")
    path = handback_path(rid, nid)
    with _locked(path):
        merged = _merge(_load(path), payload)
        merged["run_id"] = rid
        merged["node_id"] = nid
        ev.write_json(path, merged)
    kind = kind_of(payload)
    entry = None
    if post:
        from . import blackboard

        text = json.dumps(payload, ensure_ascii=False)
        if len(text) > MAX_POST_CHARS:
            text = text[:MAX_POST_CHARS] + " …"
        tags = ["findings", kind, f"run:{rid}"]
        if kind == "findings":
            tags.append("candidate")
        entry = blackboard.Blackboard().post(
            text,
            author=author or "agent",
            kind="evidence",
            tags=tags,
            provenance=f"{PROVENANCE_PREFIX}{rid}",
            node_id=nid,
        )
    return {
        "ok": True,
        "run_id": rid,
        "node_id": nid,
        "kind": kind,
        "findings": len(merged.get("findings") or []),
        "path": str(path),
        "blackboard_id": (entry or {}).get("id"),
    }


def read(run_id: str, node_id: str) -> dict[str, Any] | None:
    """The filed result for one node, or None. Falls back to blackboard posts."""
    rid = ev.safe_run_id(run_id)
    data = _load(handback_path(rid, node_id))
    if data:
        return data
    try:
        from . import blackboard

        merged: dict[str, Any] = {}
        prov = f"{PROVENANCE_PREFIX}{rid}"
        for e in blackboard.Blackboard().by_kind("evidence"):
            if e.get("provenance") != prov or str(e.get("node_id") or "") != str(node_id):
                continue
            try:
                raw = json.loads(str(e.get("text") or ""))
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                merged = _merge(merged, raw)
        return merged or None
    except Exception:  # noqa: BLE001
        return None


def list_nodes(run_id: str) -> list[str]:
    d = handback_dir(run_id)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def result_text(node_type: str, data: dict[str, Any] | None) -> str:
    """Kernel-facing text for one node, in the shape AdaptiveRun parses."""
    if not data:
        return ""
    if node_type == "verify":
        keys = ("classifications", "confidence", "unresolved", "conflicts", "unsupported")
        return json.dumps({k: data[k] for k in keys if k in data})
    if node_type == "synthesize":
        answer = str(data.get("answer") or "").strip()
        met = data.get("objective_met")
        if met is True:
            tail = "OBJECTIVE_MET: yes"
        elif met is False:
            gap = " ".join(str(data.get("gap") or "").split())
            tail = f"OBJECTIVE_MET: no — {gap}" if gap else "OBJECTIVE_MET: no"
        else:
            tail = ""
        return "\n".join(p for p in (answer, tail) if p)
    body: dict[str, Any] = {"findings": list(data.get("findings") or [])}
    if data.get("checks"):
        body["checks"] = list(data["checks"])
    return json.dumps(body)


def failing_checks(data: dict[str, Any] | None) -> int:
    return sum(1 for c in (data or {}).get("checks") or [] if isinstance(c, dict) and not c.get("passed"))


FILE_HINT = " For long or quoted text, write the JSON to a file and pass --file PATH instead of --json."


def instructions(run_id: str, node_id: str, node_type: str) -> str:
    """Seat prompt lines telling the seat how to hand its result back."""
    return _instructions(run_id, node_id, node_type) + FILE_HINT


def _instructions(run_id: str, node_id: str, node_type: str) -> str:
    cmd = f"okstratr findings add --run {run_id} --node {node_id}"
    if node_type == "verify":
        shape = ('{"classifications": [{"finding_id": "...", "verdict": '
                 '"supported|contradicted|insufficient|inconsistent"}], "confidence": 0.0, "unresolved": []}')
        read_cmd = f"okstratr findings show --run {run_id}"
        return (f"Read the findings to check with: {read_cmd}\n"
                f"When done, file your verdicts: {cmd} --json '{shape}'")
    if node_type == "synthesize":
        shape = '{"answer": "...", "objective_met": true, "gap": ""}'
        read_cmd = f"okstratr findings show --run {run_id} --supported"
        return (f"Read the checked findings with: {read_cmd}\n"
                f"When done, file your answer: {cmd} --json '{shape}' "
                "(objective_met false plus the gap if something is still missing).")
    shape = '{"findings": [{"claim": "...", "evidence": [{"source": "..."}], "confidence": 0.0}]}'
    extra = ' Add "checks": [{"name": "...", "passed": true}] for any tests or commands you ran.' \
        if node_type == "execute" else ""
    return f"When done, file your findings: {cmd} --json '{shape}'.{extra}"


def default_ids(env: dict[str, str] | None = None) -> tuple[str, str]:
    e = env if env is not None else os.environ
    return (e.get("OKSTRATR_RUN_ID") or "").strip(), (
        e.get("OKSTRATR_PLAN_NODE_ID") or e.get("OKSTRATR_NODE_ID") or ""
    ).strip()
