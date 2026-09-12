"""Persistent blackboard — append-only JSONL under state dir."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from time import time
from typing import Any
from uuid import uuid4

from .paths import state_dir

VALID_KINDS = frozenset({"claim", "note", "decision", "evidence"})


def _bb_path() -> Path:
    return state_dir() / "blackboard.jsonl"


def _index_path() -> Path:
    return state_dir() / "blackboard.index.json"


class Blackboard:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else _bb_path()
        self._entries: list[dict[str, Any]] | None = None

    def _ensure_loaded(self) -> list[dict[str, Any]]:
        if self._entries is not None:
            return self._entries
        self._entries = []
        if not self.path.is_file():
            return self._entries
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return self._entries
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                self._entries.append(obj)
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

    def _write_index(self) -> None:
        """Optional lightweight index for status / quick counts."""
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
        self._append(entry)
        return entry

    def head(self, n: int = 10) -> list[dict[str, Any]]:
        entries = self._ensure_loaded()
        if n <= 0:
            return []
        return list(entries[-n:])

    def search(self, substr: str) -> list[dict[str, Any]]:
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
        k = (kind or "").strip().lower()
        return [e for e in self._ensure_loaded() if str(e.get("kind") or "").lower() == k]

    def clear(self) -> dict[str, Any]:
        """Archive the current JSONL and start fresh."""
        entries = self._ensure_loaded()
        archived: str | None = None
        if self.path.is_file() and entries:
            stamp = int(time())
            archived_path = self.path.with_name(f"{self.path.name}.archive.{stamp}")
            shutil.move(str(self.path), str(archived_path))
            archived = str(archived_path)
        elif self.path.is_file():
            self.path.unlink(missing_ok=True)
        self._entries = []
        self._write_index()
        return {"cleared": True, "archived": archived, "count_before": len(entries)}

    def summary(self) -> dict[str, Any]:
        entries = self._ensure_loaded()
        by_kind: dict[str, int] = {}
        for e in entries:
            k = str(e.get("kind") or "note")
            by_kind[k] = by_kind.get(k, 0) + 1
        return {
            "count": len(entries),
            "by_kind": by_kind,
            "head": self.head(5),
        }

    def texts(self, n: int = 10) -> list[str]:
        return [str(x.get("text") or "") for x in self.head(n)]


_DEFAULT: Blackboard | None = None
_DEFAULT_PATH: Path | None = None


def default_blackboard(*, force_reload: bool = False) -> Blackboard:
    global _DEFAULT, _DEFAULT_PATH
    path = _bb_path()
    if _DEFAULT is None or force_reload or _DEFAULT_PATH != path:
        _DEFAULT = Blackboard(path).reload()
        _DEFAULT_PATH = path
    return _DEFAULT


# Module-level API matching prior stub (delegates to default instance)


def clear() -> dict[str, Any]:
    return default_blackboard().clear()


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
