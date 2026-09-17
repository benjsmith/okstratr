"""Blackboard — live JSONL controlled by a single duration knob.

Privacy policy (ADR-002):
- ``blackboard.duration`` default 3 days — live entries older than duration
  are dropped (rewrite jsonl) on read/post/prune/serve.
- ``duration = 0``: ephemeral — agent/CoS posts clear ASAP; hard max age
  60 minutes for all entries.
- ``bb clear`` hard-wipes live board (no archives by default).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from time import time
from typing import Any
from uuid import uuid4

from .paths import state_dir

VALID_KINDS = frozenset({"claim", "note", "decision", "evidence"})

AGENT_AUTHORS = frozenset(
    {
        "cos",
        "herdr",
        "direct",
        "grok",
        "claude",
        "codex",
        "system",
        "kernel",
        "okstratr",
        "bandit",
        "pi",
        "omp",
        "opencode",
        "cursor",
        "agent",
        "worker",
        "investigator",
    }
)


def _bb_path() -> Path:
    return state_dir() / "blackboard.jsonl"


def _index_path() -> Path:
    return state_dir() / "blackboard.index.json"


def is_agent_author(author: str, provenance: str = "") -> bool:
    a = (author or "").strip().lower()
    prov = (provenance or "").strip().lower()
    if prov.startswith("okstratr."):
        return True
    if a in AGENT_AUTHORS:
        return True
    if a.startswith("agent") or a.startswith("system"):
        return True
    return False


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not path.is_file():
        return entries
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return entries
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            entries.append(obj)
    return entries


def _rewrite_jsonl(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, default=str) + "\n")
    tmp.replace(path)


def _entry_ts(entry: dict[str, Any]) -> float:
    try:
        return float(entry.get("ts") or 0)
    except (TypeError, ValueError):
        return 0.0


def _max_age_seconds() -> float | None:
    """Return max age in seconds for live entries, or None to keep forever."""
    try:
        from . import bb_settings

        days = float(bb_settings.duration_days())
        ephemeral = days <= 0.0
        if ephemeral:
            return float(bb_settings.EPHEMERAL_MAX_MINUTES) * 60.0
        return days * 86400.0
    except Exception:  # noqa: BLE001
        return 3.0 * 86400.0


def _is_ephemeral_mode() -> bool:
    try:
        from . import bb_settings

        return bb_settings.is_ephemeral()
    except Exception:  # noqa: BLE001
        return False


class Blackboard:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else _bb_path()
        self._entries: list[dict[str, Any]] | None = None

    def _ensure_loaded(self) -> list[dict[str, Any]]:
        if self._entries is not None:
            return self._entries
        self._entries = _load_jsonl(self.path)
        return self._entries

    def reload(self) -> Blackboard:
        self._entries = None
        self._ensure_loaded()
        return self

    def _append(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        self._ensure_loaded().append(entry)
        self._write_index()
        global _DEFAULT, _DEFAULT_MTIME
        if _DEFAULT is self:
            _DEFAULT_MTIME = _file_mtime(self.path)

    def _write_index(self) -> None:
        entries = self._ensure_loaded()
        by_kind: dict[str, int] = {}
        for e in entries:
            k = str(e.get("kind") or "note")
            by_kind[k] = by_kind.get(k, 0) + 1
        idx = {
            "count": len(entries),
            "by_kind": by_kind,
            "updated_at": time(),
            "path": str(self.path),
        }
        ip = _index_path() if self.path == _bb_path() else self.path.with_suffix(".index.json")
        try:
            ip.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

    def post(
        self,
        text: str,
        author: str = "human",
        *,
        kind: str = "note",
        tags: list[str] | None = None,
        provenance: str = "",
        node_id: str | None = None,
    ) -> dict[str, Any]:
        self.prune()
        k = (kind or "note").strip().lower()
        if k not in VALID_KINDS:
            k = "note"
        entry: dict[str, Any] = {
            "id": str(uuid4()),
            "ts": time(),
            "author": str(author or "human"),
            "text": str(text),
            "kind": k,
            "tags": [str(t) for t in (tags or [])],
            "provenance": str(provenance or ""),
        }
        if node_id:
            entry["node_id"] = str(node_id)
        if is_agent_author(str(author or ""), str(provenance or "")):
            entry["agent"] = True
        self._append(entry)
        try:
            from . import ops_audit

            ops_audit.append(
                "blackboard.post",
                kind="file",
                path=str(self.path),
                note=f"author={entry['author']}",
            )
        except Exception:  # noqa: BLE001
            pass
        return entry

    def head(self, n: int = 10) -> list[dict[str, Any]]:
        self.prune()
        entries = self._ensure_loaded()
        if n <= 0:
            return []
        return list(entries[-n:])

    def search(self, substr: str) -> list[dict[str, Any]]:
        self.prune()
        needle = (substr or "").lower()
        if not needle:
            return []
        out: list[dict[str, Any]] = []
        for e in self._ensure_loaded():
            blob = " ".join(
                [
                    str(e.get("text") or ""),
                    str(e.get("author") or ""),
                    str(e.get("kind") or ""),
                    str(e.get("provenance") or ""),
                    " ".join(str(t) for t in (e.get("tags") or [])),
                    str(e.get("node_id") or ""),
                ]
            ).lower()
            if needle in blob:
                out.append(e)
        return out

    def by_kind(self, kind: str) -> list[dict[str, Any]]:
        self.prune()
        k = (kind or "").strip().lower()
        return [e for e in self._ensure_loaded() if str(e.get("kind") or "").lower() == k]

    def prune(self, *, clear_agents_asap: bool | None = None) -> dict[str, Any]:
        """Drop entries past duration; in ephemeral mode also clear agents ASAP.

        When ``duration == 0``:
        - drop ALL entries older than 60 minutes
        - drop agent/CoS entries immediately (ASAP) when clear_agents_asap
          (default True in ephemeral mode)
        """
        entries = self._ensure_loaded()
        max_age = _max_age_seconds()
        ephemeral = _is_ephemeral_mode()
        if clear_agents_asap is None:
            clear_agents_asap = ephemeral
        now = time()
        kept: list[dict[str, Any]] = []
        pruned_age = 0
        pruned_agent = 0
        for e in entries:
            ts = _entry_ts(e)
            age = now - ts if ts else 1e18
            agent = bool(e.get("agent")) or is_agent_author(
                str(e.get("author") or ""), str(e.get("provenance") or "")
            )
            if ephemeral and clear_agents_asap and agent:
                pruned_agent += 1
                continue
            if max_age is not None and age > max_age:
                pruned_age += 1
                continue
            kept.append(e)
        pruned = pruned_age + pruned_agent
        if pruned > 0:
            if kept:
                _rewrite_jsonl(self.path, kept)
            elif self.path.is_file():
                try:
                    self.path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._entries = kept
            self._write_index()
            global _DEFAULT, _DEFAULT_MTIME
            if _DEFAULT is self:
                _DEFAULT_MTIME = _file_mtime(self.path)
            try:
                from . import ops_audit

                ops_audit.append(
                    "blackboard.prune",
                    kind="file",
                    path=str(self.path),
                    note=f"pruned={pruned} age={pruned_age} agent={pruned_agent} kept={len(kept)}",
                )
            except Exception:  # noqa: BLE001
                pass
        try:
            from . import bb_settings

            days = bb_settings.duration_days()
        except Exception:  # noqa: BLE001
            days = 3.0
        return {
            "pruned": pruned,
            "pruned_age": pruned_age,
            "pruned_agent": pruned_agent,
            "kept": len(kept),
            "duration_days": days,
            "ephemeral": ephemeral,
        }

    def clear_agents(self) -> dict[str, Any]:
        """Drop agent-authored entries now (ephemeral ASAP / desk quiet)."""
        return self.prune(clear_agents_asap=True)

    def clear(self) -> dict[str, Any]:
        """Hard-wipe live board. No archives by default."""
        entries = self._ensure_loaded()
        archived: str | None = None
        do_archive = False
        try:
            from . import bb_settings

            do_archive = bool(bb_settings.archive_on_clear())
        except Exception:  # noqa: BLE001
            do_archive = False

        if do_archive and self.path.is_file() and entries:
            stamp = int(time())
            archived_path = self.path.with_name(f"{self.path.name}.archive.{stamp}")
            shutil.move(str(self.path), str(archived_path))
            archived = str(archived_path)
        elif self.path.is_file():
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
        if self.path.is_file():
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
        self._entries = []
        self._write_index()
        global _DEFAULT, _DEFAULT_MTIME
        if _DEFAULT is self:
            _DEFAULT_MTIME = _file_mtime(self.path)
        legacy = delete_legacy_archives(self.path.parent, prefix=self.path.name)
        # Also remove leftover ephemeral file from earlier design
        eph = state_dir() / "blackboard.ephemeral.jsonl"
        if eph.is_file():
            try:
                eph.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            from . import ops_audit

            ops_audit.append(
                "blackboard.clear",
                kind="file",
                path=str(self.path),
                note=f"count_before={len(entries)} archived={bool(archived)}",
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "cleared": True,
            "archived": archived,
            "count_before": len(entries),
            "legacy_archives_removed": legacy.get("removed", 0),
        }

    def summary(self) -> dict[str, Any]:
        self.prune()
        entries = self._ensure_loaded()
        by_kind: dict[str, int] = {}
        for e in entries:
            k = str(e.get("kind") or "note")
            by_kind[k] = by_kind.get(k, 0) + 1
        try:
            from . import bb_settings

            mode = bb_settings.mode_chip()
            duration = bb_settings.duration_days()
            ephemeral = bb_settings.is_ephemeral()
        except Exception:  # noqa: BLE001
            mode = "bb: 3d"
            duration = 3.0
            ephemeral = False
        return {
            "count": len(entries),
            "by_kind": by_kind,
            "head": self.head(24),
            "mode": mode,
            "duration_days": duration,
            "ephemeral": ephemeral,
        }

    def texts(self, n: int = 10) -> list[str]:
        return [str(x.get("text") or "") for x in self.head(n)]


def delete_legacy_archives(
    directory: Path | None = None, *, prefix: str = "blackboard.jsonl"
) -> dict[str, Any]:
    """Cleanup ``*.archive.<unix>`` and leftover ephemeral jsonl."""
    d = directory or state_dir()
    removed: list[str] = []
    try:
        for p in d.iterdir():
            name = p.name
            if not p.is_file():
                continue
            if name.startswith(f"{prefix}.archive.") or name == "blackboard.ephemeral.jsonl":
                try:
                    p.unlink()
                    removed.append(str(p))
                except OSError:
                    pass
    except OSError:
        pass
    if removed:
        try:
            from . import ops_audit

            ops_audit.append(
                "blackboard.legacy_archive_cleanup",
                kind="file",
                path=str(d),
                note=f"removed={len(removed)}",
            )
        except Exception:  # noqa: BLE001
            pass
    return {"removed": len(removed), "paths": removed}


def prune() -> dict[str, Any]:
    bb = default_blackboard()
    ret = bb.prune()
    legacy = delete_legacy_archives()
    invalidate_default()
    return {"ok": True, "retention": ret, "legacy_archives": legacy}


def clear_agents_asap() -> dict[str, Any]:
    """Desk quiet / ephemeral ASAP — drop agent posts when duration=0 (always safe)."""
    bb = default_blackboard()
    if _is_ephemeral_mode():
        out = bb.prune(clear_agents_asap=True)
    else:
        out = bb.prune(clear_agents_asap=False)
    invalidate_default()
    return out


_DEFAULT: Blackboard | None = None
_DEFAULT_PATH: Path | None = None
_DEFAULT_MTIME: float | None = None


def _file_mtime(path: Path) -> float | None:
    try:
        if path.is_file():
            return path.stat().st_mtime
    except OSError:
        return None
    return None


def default_blackboard(*, force_reload: bool = False) -> Blackboard:
    global _DEFAULT, _DEFAULT_PATH, _DEFAULT_MTIME
    path = _bb_path()
    mtime = _file_mtime(path)
    stale = (
        _DEFAULT is not None
        and _DEFAULT_PATH == path
        and not force_reload
        and mtime != _DEFAULT_MTIME
    )
    if _DEFAULT is None or force_reload or _DEFAULT_PATH != path or stale:
        _DEFAULT = Blackboard(path).reload()
        _DEFAULT_PATH = path
        _DEFAULT_MTIME = mtime
    return _DEFAULT


def invalidate_default() -> None:
    global _DEFAULT, _DEFAULT_PATH, _DEFAULT_MTIME
    _DEFAULT = None
    _DEFAULT_PATH = None
    _DEFAULT_MTIME = None


def on_serve_start() -> dict[str, Any]:
    bb = default_blackboard(force_reload=True)
    ret = bb.prune(clear_agents_asap=_is_ephemeral_mode())
    legacy = delete_legacy_archives()
    invalidate_default()
    return {"retention": ret, "legacy_archives": legacy}


def clear() -> dict[str, Any]:
    result = default_blackboard().clear()
    invalidate_default()
    return result


def post(
    text: str,
    author: str = "human",
    *,
    kind: str = "note",
    tags: list[str] | None = None,
    provenance: str = "",
    node_id: str | None = None,
) -> dict[str, Any]:
    return default_blackboard().post(
        text,
        author,
        kind=kind,
        tags=tags,
        provenance=provenance,
        node_id=node_id,
    )


def head(n: int = 10) -> list[dict[str, Any]]:
    return default_blackboard().head(n)


def search(substr: str) -> list[dict[str, Any]]:
    return default_blackboard().search(substr)


def by_kind(kind: str) -> list[dict[str, Any]]:
    return default_blackboard().by_kind(kind)


def texts(n: int = 10) -> list[str]:
    return default_blackboard().texts(n)


def summary() -> dict[str, Any]:
    return default_blackboard().summary()
