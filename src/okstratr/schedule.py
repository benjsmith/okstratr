"""Scheduling / attention windows.

Wires ``schedule_parse`` + per-desk ``desks.schedule`` attachments into a status
summary. Attention-window UI (next fire chip) is next; this module exposes the
data for status.json / panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any

from .schedule_parse import (
    ParsedSchedule,
    ScheduleParseError,
    describe,
    parse_schedule_args,
)


@dataclass
class Window:
    """In-process attention window (ephemeral; not yet persisted)."""

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


def add_window(
    label: str,
    start_ts: float | None = None,
    end_ts: float | None = None,
) -> Window:
    w = Window(
        label=label,
        start_ts=start_ts if start_ts is not None else time(),
        end_ts=end_ts,
    )
    _windows.append(w)
    return w


def open_windows() -> list[Window]:
    return [w for w in _windows if w.open()]


def parse(args: list[str] | str) -> ParsedSchedule:
    """Parse schedule args via schedule_parse (raises ScheduleParseError)."""
    return parse_schedule_args(args)


def attach_to_desk(args: list[str] | str, *, desk_id: str | None = None) -> dict[str, Any]:
    """Attach a parsed schedule to a desk through the desks registry."""
    from . import desks

    return desks.schedule(args, desk_id=desk_id)


def _next_fire_from_payload(sched: dict[str, Any] | None, *, now: float | None = None) -> dict[str, Any] | None:
    """Best-effort next fire estimate from a desk.schedule payload."""
    if not isinstance(sched, dict):
        return None
    now = time() if now is None else now
    every = sched.get("every_seconds")
    describe_txt = sched.get("describe") or sched.get("raw") or ""
    if every is None:
        # calendar named schedules — no fixed seconds; surface as attention hint
        return {
            "kind": sched.get("kind") or sched.get("name") or "calendar",
            "describe": describe_txt or describe_from_payload(sched),
            "every_seconds": None,
            "next_ts": None,
            "attention_window_next": True,
            "note": "Calendar / named schedule — attention-window next fire TBD",
        }
    try:
        secs = float(every)
    except (TypeError, ValueError):
        return None
    if secs <= 0:
        return None
    # If last_fire_ts present, add interval; else next is now+interval from attach.
    base = sched.get("last_fire_ts") or sched.get("attached_at") or now
    try:
        base_f = float(base)
    except (TypeError, ValueError):
        base_f = now
    next_ts = base_f + secs
    while next_ts <= now:
        next_ts += secs
    return {
        "kind": sched.get("kind") or "interval",
        "describe": describe_txt or f"every {secs:g}s",
        "every_seconds": secs,
        "next_ts": next_ts,
        "in_seconds": max(0.0, next_ts - now),
        "attention_window_next": False,
    }


def describe_from_payload(sched: dict[str, Any]) -> str:
    try:
        # Rebuild a ParsedSchedule-like describe when possible
        raw = sched.get("raw") or sched.get("name") or ""
        if raw:
            return describe(parse_schedule_args(str(raw)))
    except ScheduleParseError:
        pass
    return str(sched.get("describe") or sched.get("name") or "schedule")


def desk_schedule_summaries() -> list[dict[str, Any]]:
    """Summaries of schedules attached to standing desks."""
    try:
        from . import desks as desks_mod

        reg = desks_mod.default_registry()
    except Exception:  # noqa: BLE001
        from .logutil import get_logger

        get_logger(__name__).warning("desk_schedule_summaries: registry unavailable", exc_info=True)
        return []
    now = time()
    out: list[dict[str, Any]] = []
    for d in reg.standing():
        if not d.schedule:
            continue
        nxt = _next_fire_from_payload(d.schedule, now=now)
        out.append(
            {
                "desk_id": d.id,
                "kind": d.kind,
                "objective": d.objective,
                "schedule": d.schedule,
                "next_fire": nxt,
            }
        )
    return out


def next_fire() -> dict[str, Any] | None:
    """Soonest next_fire across standing desks with schedules."""
    soonest: dict[str, Any] | None = None
    soonest_ts = None
    for row in desk_schedule_summaries():
        nxt = row.get("next_fire") or {}
        ts = nxt.get("next_ts")
        if ts is None:
            if soonest is None:
                soonest = {**nxt, "desk_id": row["desk_id"], "desk_kind": row["kind"]}
            continue
        if soonest_ts is None or ts < soonest_ts:
            soonest_ts = ts
            soonest = {**nxt, "desk_id": row["desk_id"], "desk_kind": row["kind"]}
    return soonest


def summary() -> dict[str, Any]:
    """Status.json schedule block: windows + desk schedule next fire."""
    desks_sched = desk_schedule_summaries()
    nxt = next_fire()
    return {
        "windows": len(_windows),
        "open": [w.label for w in open_windows()],
        "desk_schedules": len(desks_sched),
        "desks": desks_sched,
        "next_fire": nxt,
        "attention_window_next": True,  # full attention-window UI is follow-up
        "note": (
            "Schedule parse + desk attach are live; attention-window next-fire "
            "UI is next."
        ),
    }
