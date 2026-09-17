"""Tamper-evident ops audit log (metadata only — never file contents or prompts)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .paths import state_dir

_GENESIS = "0" * 64
_SEQ_LOCK_NOTE = "best-effort append; concurrent writers may race on seq"


def _audit_path() -> Path:
    return state_dir() / "ops_audit.jsonl"


def _canonical(obj: dict[str, Any]) -> str:
    """Stable JSON for hashing (sorted keys, no whitespace variance)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _hash_record(prev_hash: str, body: dict[str, Any]) -> str:
    material = (prev_hash or _GENESIS) + _canonical(body)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _argv_digest(argv: list[str] | tuple[str, ...] | None) -> str | None:
    if not argv:
        return None
    # Digest argv strings only — never treat as secrets to log in clear.
    blob = _canonical({"argv": [str(a) for a in argv]})
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _last_record(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    last: dict[str, Any] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "hash" in obj:
            last = obj
    return last


def append(
    op: str,
    *,
    kind: str = "process",
    path: str | None = None,
    argv: list[str] | tuple[str, ...] | None = None,
    cwd: str | None = None,
    desk_id: str | None = None,
    node_id: str | None = None,
    harness_id: str | None = None,
    pid: int | None = None,
    rc: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Append one metadata-only audit record; return the sealed record."""
    dest = _audit_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    prev = _last_record(dest)
    prev_hash = str(prev.get("hash") or _GENESIS) if prev else _GENESIS
    seq = int(prev.get("seq") or 0) + 1 if prev else 1
    body: dict[str, Any] = {
        "seq": seq,
        "ts": time.time(),
        "prev_hash": prev_hash,
        "op": str(op),
        "kind": str(kind if kind in ("file", "process") else "process"),
    }
    if path:
        body["path"] = str(path)
    digest = _argv_digest(argv)
    if digest:
        body["argv_digest"] = digest
    if cwd:
        body["cwd"] = str(cwd)
    if desk_id:
        body["desk_id"] = str(desk_id)
    if node_id:
        body["node_id"] = str(node_id)
    if harness_id:
        body["harness_id"] = str(harness_id)
    if pid is not None:
        body["pid"] = int(pid)
    if rc is not None:
        body["rc"] = int(rc)
    if note:
        # Never store prompts / file contents — keep note short metadata.
        body["note"] = str(note)[:240]
    sealed = dict(body)
    sealed["hash"] = _hash_record(prev_hash, body)
    try:
        with dest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sealed, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        # Best-effort: still return sealed record for callers/tests.
        pass
    return sealed


def read_records(*, n: int | None = None, head: bool = False) -> list[dict[str, Any]]:
    """Load audit records. ``n`` limits count; ``head=True`` takes from start."""
    path = _audit_path()
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    if n is None or n <= 0:
        return out
    if head:
        return out[:n]
    return out[-n:]


def verify() -> dict[str, Any]:
    """Walk the hash chain; return ok + details on first break."""
    records = read_records()
    if not records:
        return {"ok": True, "count": 0, "path": str(_audit_path())}
    prev_hash = _GENESIS
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            return {
                "ok": False,
                "count": len(records),
                "broken_at": i,
                "error": "non-dict record",
                "path": str(_audit_path()),
            }
        stored = str(rec.get("hash") or "")
        body = {k: v for k, v in rec.items() if k != "hash"}
        # Ensure required chain fields present
        if str(body.get("prev_hash") or "") != prev_hash:
            return {
                "ok": False,
                "count": len(records),
                "broken_at": i,
                "seq": body.get("seq"),
                "error": f"prev_hash mismatch: expected {prev_hash[:12]}…",
                "path": str(_audit_path()),
            }
        expected = _hash_record(prev_hash, body)
        if stored != expected:
            return {
                "ok": False,
                "count": len(records),
                "broken_at": i,
                "seq": body.get("seq"),
                "error": "hash mismatch",
                "path": str(_audit_path()),
            }
        prev_hash = stored
    return {
        "ok": True,
        "count": len(records),
        "tip_hash": prev_hash,
        "tip_seq": records[-1].get("seq"),
        "path": str(_audit_path()),
    }


def tail(n: int = 20) -> list[dict[str, Any]]:
    return read_records(n=n, head=False)


def head(n: int = 20) -> list[dict[str, Any]]:
    return read_records(n=n, head=True)


def path() -> str:
    return str(_audit_path())
