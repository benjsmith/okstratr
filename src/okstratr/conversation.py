"""Desk ↔ CoS conversation history for the observer / Omarchy panel.

Herdr remains the agent runtime. When a Herdr transcript file is available for
a desk we surface it; otherwise we synthesize a thin stub from the desk brief
plus CoS / herdr blackboard turns so the UI is never a cryptic activity dump.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .paths import state_dir


def _herdr_home() -> Path:
    raw = (os.environ.get("HERDR_HOME") or os.environ.get("OKSTRATR_HERDR_HOME") or "").strip()
    if raw:
        return Path(raw).expanduser()
    xdg = (os.environ.get("XDG_STATE_HOME") or "").strip()
    if xdg:
        return Path(xdg).expanduser() / "herdr"
    return Path.home() / ".local" / "state" / "herdr"


def transcript_candidates(desk_id: str) -> list[Path]:
    """Known Herdr / okstratr transcript locations for a desk (first hit wins)."""
    did = str(desk_id or "").strip()
    if not did or did.startswith("kind:"):
        return []
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in did)[:64]
    herdr = _herdr_home()
    desks = state_dir() / "desks" / did
    return [
        desks / "herdr_transcript.jsonl",
        desks / "conversation.jsonl",
        desks / "cos_conversation.jsonl",
        herdr / "transcripts" / f"{safe}.jsonl",
        herdr / "transcripts" / f"{did}.jsonl",
        herdr / "conversations" / f"{safe}.jsonl",
        herdr / "agents" / safe / "transcript.jsonl",
        Path.home() / ".local" / "share" / "herdr" / "transcripts" / f"{safe}.jsonl",
        state_dir() / "harness_logs" / f"{safe}.transcript.jsonl",
    ]


def _parse_jsonl_messages(path: Path, *, limit: int = 80) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            messages.append(
                {
                    "role": "system",
                    "author": "herdr",
                    "text": line[:2000],
                    "ts": None,
                    "source": "raw_line",
                }
            )
            continue
        if not isinstance(obj, dict):
            continue
        role = str(
            obj.get("role")
            or obj.get("speaker")
            or obj.get("author")
            or ("assistant" if obj.get("agent") else "user")
        )
        body = obj.get("text") or obj.get("content") or obj.get("message") or obj.get("body") or ""
        if isinstance(body, list):
            parts = []
            for p in body:
                if isinstance(p, dict):
                    parts.append(str(p.get("text") or p.get("content") or ""))
                else:
                    parts.append(str(p))
            body = "\n".join(parts)
        messages.append(
            {
                "role": role,
                "author": str(obj.get("author") or role),
                "text": str(body)[:4000],
                "ts": obj.get("ts") or obj.get("timestamp") or obj.get("created_at"),
                "source": "herdr_transcript",
                "id": obj.get("id"),
            }
        )
    if limit > 0 and len(messages) > limit:
        return messages[-limit:]
    return messages


def _desk_record(desk_id: str) -> dict[str, Any] | None:
    try:
        from . import desks as desks_mod

        reg = desks_mod.load_registry()
        d = reg.desks.get(str(desk_id))
        if d is None:
            return None
        return d.to_dict() if hasattr(d, "to_dict") else dict(d.__dict__)
    except Exception:  # noqa: BLE001
        return None


def _entry_matches_desk(entry: dict[str, Any], desk_id: str, *, kind: str | None = None) -> bool:
    did = str(desk_id or "").strip()
    if not did:
        return False
    if str(entry.get("desk_id") or "") == did:
        return True
    tags = [str(t) for t in (entry.get("tags") or [])]
    if did in tags or f"desk:{did}" in tags:
        return True
    text = str(entry.get("text") or "")
    if did in text:
        return True
    if kind:
        k = str(kind).strip().lower()
        if k and k in {t.lower() for t in tags}:
            author = str(entry.get("author") or "").lower()
            prov = str(entry.get("provenance") or "")
            if author in ("cos", "herdr") or "okstratr.cos" in prov or "okstratr.herdr" in prov:
                return True
    return False


def _synthesize_from_blackboard(
    desk_id: str,
    *,
    desk: dict[str, Any] | None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    from . import blackboard as bb_mod

    kind = str((desk or {}).get("kind") or "") or None
    objective = str((desk or {}).get("objective") or "").strip()
    messages: list[dict[str, Any]] = []
    if objective:
        messages.append(
            {
                "role": "user",
                "author": "human",
                "text": objective,
                "ts": (desk or {}).get("created_at") or (desk or {}).get("updated_at"),
                "source": "desk_objective",
            }
        )
    try:
        entries = list(bb_mod.default_blackboard().head(80))
    except Exception:  # noqa: BLE001
        entries = []
    matched = [e for e in entries if _entry_matches_desk(e, desk_id, kind=kind)]
    if not matched and kind:
        for e in entries:
            tags = {str(t).lower() for t in (e.get("tags") or [])}
            if str(e.get("author") or "").lower() == "cos" and (
                kind.lower() in tags or "breakdown" in tags
            ):
                matched.append(e)
    for e in matched:
        author = str(e.get("author") or "system")
        role = "assistant" if author.lower() in ("cos", "herdr", "assistant") else "system"
        if author.lower() == "human":
            role = "user"
        messages.append(
            {
                "role": role,
                "author": author,
                "text": str(e.get("text") or "")[:4000],
                "ts": e.get("ts"),
                "source": "blackboard_stub",
                "id": e.get("id"),
                "kind": e.get("kind"),
            }
        )
    if limit > 0 and len(messages) > limit:
        return messages[-limit:]
    return messages


def conversation_for_desk(desk_id: str | None, *, limit: int = 80) -> dict[str, Any]:
    """Return CoS/Herdr conversation turns for a desk.

    ``source`` is ``herdr_transcript`` when a file was read, else ``stub``.
    """
    did = str(desk_id or "").strip()
    if not did or did.startswith("kind:"):
        return {
            "ok": False,
            "error": "desk_id required",
            "desk_id": did or None,
            "messages": [],
            "source": "none",
            "stub": True,
        }
    desk = _desk_record(did)
    for path in transcript_candidates(did):
        if path.is_file():
            messages = _parse_jsonl_messages(path, limit=limit)
            return {
                "ok": True,
                "desk_id": did,
                "desk": desk,
                "messages": messages,
                "source": "herdr_transcript",
                "transcript_path": str(path),
                "stub": False,
                "available": True,
            }
    messages = _synthesize_from_blackboard(did, desk=desk, limit=limit)
    return {
        "ok": True,
        "desk_id": did,
        "desk": desk,
        "messages": messages,
        "source": "stub",
        "stub": True,
        "available": bool(messages),
        "transcript_path": None,
        "hint": (
            "Herdr transcript not found; showing desk objective + CoS/Herdr "
            "blackboard turns. Wire Herdr transcript path when available."
        ),
        "candidates_checked": [str(p) for p in transcript_candidates(did)[:6]],
    }


def blackboard_items_for_desk(
    desk_id: str | None,
    *,
    n: int = 24,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    """Live blackboard rows scoped to one desk (kind fallback for legacy tags)."""
    from . import blackboard as bb_mod

    did = str(desk_id or "").strip()
    items = list(bb_mod.default_blackboard().head(max(n * 4, 40)))
    if not did or did.startswith("kind:"):
        return items[-n:] if n > 0 else items
    desk = _desk_record(did)
    dkind = kind or (str((desk or {}).get("kind") or "") or None)
    matched = [e for e in items if _entry_matches_desk(e, did, kind=dkind)]
    if not matched and dkind:
        for e in items:
            tags = {str(t).lower() for t in (e.get("tags") or [])}
            if dkind.lower() in tags:
                matched.append(e)
    return matched[-n:] if n > 0 else matched
