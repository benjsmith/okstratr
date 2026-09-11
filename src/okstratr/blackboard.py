"""Shared blackboard for agents + human — stub."""

from __future__ import annotations

from time import time
from typing import Any

_notes: list[dict[str, Any]] = []


def clear() -> None:
    _notes.clear()


def post(text: str, author: str = "human") -> dict[str, Any]:
    note = {"ts": time(), "author": author, "text": str(text)}
    _notes.append(note)
    return note


def head(n: int = 10) -> list[dict[str, Any]]:
    return list(_notes[-n:])


def texts(n: int = 10) -> list[str]:
    return [str(x.get("text") or "") for x in head(n)]


def summary() -> dict[str, Any]:
    return {"count": len(_notes), "head": head(5)}
