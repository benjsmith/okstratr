"""File-queue adapter: an outside host runs each seat and says when it is done.

``okstratr run --adapter queue`` writes each ready seat to
``<state>/queue/<run_id>/<node_id>.prompt.md`` with a ``<node_id>.meta.json``
next to it, then waits. The host (a person, a parent agent dispatching one
fresh subagent per seat, a script) runs the seat; the seat files its result
with ``okstratr findings add``; the host then runs ``okstratr queue done``.
That command is the host's completion signal: okstratr never decides on its
own that a queued seat finished, and never reads the seat's transcript.

Wall time is measured from ``queue claim`` (or from queueing, if the host
never claims) to ``queue done``. Tokens are what ``queue done --tokens``
reports, else what the seat filed, else an estimate from the text sizes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from .. import evidence as ev
from .. import handback
from ..paths import state_dir

STATES = ("queued", "claimed", "done", "failed")


def queue_root() -> Path:
    return state_dir() / "queue"


def queue_dir(run_id: str) -> Path:
    return queue_root() / ev.safe_run_id(run_id)


def _meta_path(run_id: str, node_id: str) -> Path:
    return queue_dir(run_id) / f"{ev.safe_run_id(node_id)}.meta.json"


def prompt_path(run_id: str, node_id: str) -> Path:
    return queue_dir(run_id) / f"{ev.safe_run_id(node_id)}.prompt.md"


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write(path: Path, data: dict[str, Any]) -> None:
    ev.write_json(path, data)


def enqueue(run_id: str, node: Any, prompt: str) -> dict[str, Any]:
    rid = ev.safe_run_id(run_id)
    nid = node.node_id
    d = queue_dir(rid)
    d.mkdir(parents=True, exist_ok=True)
    prompt_path(rid, nid).write_text(prompt.rstrip() + "\n", encoding="utf-8")
    meta = {
        "run_id": rid,
        "node_id": nid,
        "node_type": node.node_type,
        "role": node.role,
        "harness": node.harness,
        "model": node.model,
        "state": "queued",
        "queued_at": time.time(),
        "prompt": str(prompt_path(rid, nid)),
        "prompt_chars": len(prompt),
    }
    _write(_meta_path(rid, nid), meta)
    return meta


def list_seats(run_id: str | None = None, *, state: str | None = None) -> list[dict[str, Any]]:
    root = queue_dir(run_id) if run_id else queue_root()
    if not root.is_dir():
        return []
    pattern = "*.meta.json" if run_id else "*/*.meta.json"
    out = []
    for p in sorted(root.glob(pattern)):
        m = _read(p)
        if m and (state is None or m.get("state") == state):
            out.append(m)
    out.sort(key=lambda m: float(m.get("queued_at") or 0))
    return out


def show(run_id: str, node_id: str) -> dict[str, Any]:
    m = _read(_meta_path(run_id, node_id))
    if not m:
        raise KeyError(f"no queued seat {node_id} in run {run_id}")
    try:
        m["prompt_text"] = prompt_path(run_id, node_id).read_text(encoding="utf-8")
    except OSError:
        m["prompt_text"] = ""
    return m


def claim(run_id: str, node_id: str, *, by: str = "") -> dict[str, Any]:
    path = _meta_path(run_id, node_id)
    m = _read(path)
    if not m:
        raise KeyError(f"no queued seat {node_id} in run {run_id}")
    if m.get("state") != "queued":
        raise ValueError(f"seat {node_id} is {m.get('state')}, not queued")
    m.update(state="claimed", claimed_at=time.time(), claimed_by=by)
    _write(path, m)
    return m


def done(
    run_id: str,
    node_id: str,
    *,
    failed: bool = False,
    tokens: int | None = None,
    error: str = "",
) -> dict[str, Any]:
    """The host's completion signal for one queued seat."""
    path = _meta_path(run_id, node_id)
    m = _read(path)
    if not m:
        raise KeyError(f"no queued seat {node_id} in run {run_id}")
    if m.get("state") in ("done", "failed"):
        raise ValueError(f"seat {node_id} is already {m.get('state')}")
    m.update(state="failed" if failed else "done", done_at=time.time(), error=error)
    if tokens is not None:
        m["tokens"] = int(tokens)
    m["handback"] = bool(handback.read(run_id, node_id))
    _write(path, m)
    return m


def _estimate_tokens(prompt_chars: int, text: str) -> int:
    return int((prompt_chars + len(text or "")) / 4)


class QueueRunner:
    """``run_plan`` runner that hands each seat to an outside host via files."""

    def __init__(
        self,
        run_id: str,
        *,
        context_for: Callable[[Any], str] | None = None,
        poll_s: float = 1.0,
        timeout_s: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.run_id = ev.safe_run_id(run_id)
        self.context_for = context_for
        self.poll_s = poll_s
        self.timeout_s = timeout_s
        self.sleep = sleep
        self.clock = clock

    def prompt(self, node: Any, inputs: dict[str, Any]) -> str:
        from .. import orchestration as orch

        ctx = self.context_for(node) if self.context_for and node.node_type in ("verify", "synthesize") else ""
        body = orch.prompt_for(node, inputs, ctx)
        steps = handback.instructions(self.run_id, node.node_id, node.node_type)
        return (
            f"# Seat {node.node_id} ({node.node_type})\n\n{body}\n\n"
            f"## Hand back\n\n{steps}\n\n"
            "Work only from this prompt, the files it names and the commands above; "
            "do not read other seats' prompts.\n"
        )

    def __call__(self, node: Any, inputs: dict[str, Any]) -> Any:
        from .. import orchestration as orch

        prompt = self.prompt(node, inputs)
        meta = enqueue(self.run_id, node, prompt)
        start = self.clock()
        path = _meta_path(self.run_id, node.node_id)
        while True:
            m = _read(path)
            if m.get("state") in ("done", "failed"):
                break
            if self.timeout_s is not None and self.clock() - start >= self.timeout_s:
                return orch.NodeResult(node_id=node.node_id, ok=False, error="queue timeout")
            self.sleep(self.poll_s)
        data = handback.read(self.run_id, node.node_id)
        text = handback.result_text(node.node_type, data)
        t0 = float(m.get("claimed_at") or m.get("queued_at") or start)
        latency = max(0.0, float(m.get("done_at") or self.clock()) - t0)
        tokens = m.get("tokens")
        if tokens is None and data and data.get("tokens") is not None:
            tokens = data.get("tokens")
        if tokens is None:
            tokens = _estimate_tokens(int(meta.get("prompt_chars") or 0), text)
        return orch.NodeResult(
            node_id=node.node_id,
            ok=m.get("state") == "done",
            text=text,
            tokens=int(tokens),
            latency_s=round(latency, 3),
            error=str(m.get("error") or ""),
            data={"handback": bool(data), "adapter": "queue"},
        )
