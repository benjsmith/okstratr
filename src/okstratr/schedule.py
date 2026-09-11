"""Scheduling / attention windows — stub."""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any


@dataclass
class Window:
    label: str
    start_ts: float
    end_ts: float | None = None

    def open(self) -> bool:
        now = time()
        if now < self.start_ts:
            return False
        if self.end_ts is not None and now > self.end_ts:
            return False
        return True


_windows: list[Window] = []


def clear() -> None:
    _windows.clear()


def add_window(label: str, start_ts: float | None = None, end_ts: float | None = None) -> Window:
    w = Window(label=label, start_ts=start_ts if start_ts is not None else time(), end_ts=end_ts)
    _windows.append(w)
    return w


def open_windows() -> list[Window]:
    return [w for w in _windows if w.open()]


def summary() -> dict[str, Any]:
    return {
        "windows": len(_windows),
        "open": [w.label for w in open_windows()],
    }
