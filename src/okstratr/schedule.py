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


def _schedule_id_for(desk_id: str, sched: dict[str, Any]) -> str:
    """Stable-ish schedule id for notify envelopes."""
    existing = sched.get("schedule_id") or sched.get("id")
    if existing:
        return str(existing)
    attached = sched.get("attached_at") or ""
    return f"{desk_id}:{attached}"


def due_desks(*, now: float | None = None) -> list[dict[str, Any]]:
    """Standing desks whose interval schedule is due.

    ``_next_fire_from_payload`` always returns a *future* next_ts, so due is
    computed from ``last_fire_ts|attached_at`` + ``every_seconds`` vs now.
    """
    now = time() if now is None else now
    due: list[dict[str, Any]] = []
    for row in desk_schedule_summaries():
        sched = row.get("schedule") or {}
        if not isinstance(sched, dict):
            continue
        every = sched.get("every_seconds")
        if every is None:
            continue
        try:
            secs = float(every)
        except (TypeError, ValueError):
            continue
        if secs <= 0:
            continue
        base = sched.get("last_fire_ts") or sched.get("attached_at")
        if base is None:
            continue
        try:
            base_f = float(base)
        except (TypeError, ValueError):
            continue
        if now >= base_f + secs:
            due.append(row)
    return due


def fire_due(
    *,
    now: float | None = None,
    emit_notify: bool = True,
    limit: int = 32,
) -> dict[str, Any]:
    """Fire due interval schedules on the existing desk-schedule path.

    Updates ``last_fire_ts`` on each due desk schedule (no second scheduler).
    Emits ``schedule.start`` via host_notify when ``emit_notify``.
    Called from status.write_status reconcile — same tick as auto-quiet.
    """
    now = time() if now is None else now
    fired: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        from . import desks as desks_mod

        reg = desks_mod.default_registry()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "fired": [], "error": f"registry: {e}"}

    for row in due_desks(now=now)[: max(0, int(limit))]:
        desk_id = str(row.get("desk_id") or "")
        desk = reg.desks.get(desk_id) if desk_id else None
        if desk is None or not isinstance(desk.schedule, dict):
            continue
        sched = dict(desk.schedule)
        sid = _schedule_id_for(desk_id, sched)
        sched["schedule_id"] = sid
        sched["last_fire_ts"] = now
        sched["last_fire_at"] = now
        desk.schedule = sched
        desk.updated_at = now
        entry: dict[str, Any] = {
            "desk_id": desk_id,
            "kind": desk.kind,
            "schedule_id": sid,
            "objective": desk.objective,
            "every_seconds": sched.get("every_seconds"),
        }
        if emit_notify:
            try:
                from . import host_notify

                title = f"Schedule fire · {desk.kind or 'desk'}"
                body = (desk.objective or "").strip() or (
                    sched.get("describe") or sched.get("raw") or sid
                )
                result = host_notify.emit(
                    "schedule.start",
                    title=title,
                    body=str(body)[:500],
                    schedule_id=sid,
                    desk=desk.kind,
                    progress={"pct": None, "phase": "start", "detail": "schedule fire"},
                )
                entry["notify"] = {
                    "ok": bool(result.get("ok")),
                    "path": result.get("path"),
                    "mode": result.get("mode"),
                }
            except Exception as e:  # noqa: BLE001
                errors.append(f"{desk_id}: {e}")
                entry["notify_error"] = str(e)
        fired.append(entry)

    if fired:
        try:
            reg.save()
        except Exception as e:  # noqa: BLE001
            errors.append(f"save: {e}")

    return {
        "ok": not errors,
        "fired": fired,
        "count": len(fired),
        "errors": errors,
        "ts": now,
    }


def notify_schedule(
    kind: str,
    *,
    desk_id: str | None = None,
    schedule_id: str | None = None,
    title: str = "",
    body: str = "",
    desk_kind: str | None = None,
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit a schedule.* host_notify (helper for progress/done/failed)."""
    from . import host_notify

    return host_notify.emit(
        kind,
        title=title or kind,
        body=body,
        schedule_id=schedule_id,
        desk=desk_kind,
        progress=progress,
        extra={"desk_id": desk_id} if desk_id else None,
    )
