"""Parse desk schedule arguments: named cadences and interval expressions.

Supported forms (Ben):
  - named: hourly, daily, weekly, monthly, yearly|annually
  - intervals: number + optional unit; space optional; bare number ⇒ hours
  - units: s, m|min, h, d, w|wks
  - combinations: e.g. 1h30m = 90 minutes
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

# Seconds per unit (canonical).
_UNIT_SECONDS: dict[str, float] = {
    "s": 1.0,
    "sec": 1.0,
    "secs": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "m": 60.0,
    "min": 60.0,
    "mins": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hrs": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "d": 86400.0,
    "day": 86400.0,
    "days": 86400.0,
    "w": 604800.0,
    "wk": 604800.0,
    "wks": 604800.0,
    "week": 604800.0,
    "weeks": 604800.0,
}

_NAMED: dict[str, dict[str, Any]] = {
    "hourly": {"kind": "named", "name": "hourly", "every_seconds": 3600.0},
    "daily": {"kind": "named", "name": "daily", "every_seconds": 86400.0},
    "weekly": {"kind": "named", "name": "weekly", "every_seconds": 604800.0},
    "monthly": {
        "kind": "named",
        "name": "monthly",
        "every_seconds": None,  # calendar month; not a fixed second count
        "calendar": "month",
    },
    "yearly": {
        "kind": "named",
        "name": "yearly",
        "every_seconds": None,
        "calendar": "year",
    },
    "annually": {
        "kind": "named",
        "name": "yearly",
        "every_seconds": None,
        "calendar": "year",
    },
}

# One segment: number + optional unit token (unit may be glued or separate).
_SEGMENT_RE = re.compile(
    r"""
    (?P<num>\d+(?:\.\d+)?)
    \s*
    (?P<unit>
        seconds?|secs?|s|
        minutes?|mins?|m|
        hours?|hrs?|hr|h|
        days?|d|
        weeks?|wks?|wk|w
    )?
    """,
    re.IGNORECASE | re.VERBOSE,
)

_BARE_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")


class ScheduleParseError(ValueError):
    """Raised when schedule args cannot be parsed."""


@dataclass(frozen=True)
class ParsedSchedule:
    """Normalized schedule description."""

    kind: str  # "named" | "interval"
    raw: str
    every_seconds: float | None = None
    name: str | None = None
    calendar: str | None = None  # "month" | "year" when not fixed-length
    parts: tuple[tuple[float, str], ...] = ()  # (amount, canonical_unit)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["parts"] = [{"amount": a, "unit": u} for a, u in self.parts]
        return d


def _canon_unit(unit: str | None, *, default_hours: bool) -> str:
    if not unit:
        if default_hours:
            return "h"
        raise ScheduleParseError("missing unit")
    u = unit.lower()
    if u not in _UNIT_SECONDS:
        raise ScheduleParseError(f"unknown unit: {unit}")
    # Canonical short form
    sec = _UNIT_SECONDS[u]
    for short, s in (("s", 1.0), ("m", 60.0), ("h", 3600.0), ("d", 86400.0), ("w", 604800.0)):
        if s == sec:
            return short
    return u


def _parse_interval_body(body: str) -> ParsedSchedule:
    text = body.strip()
    if not text:
        raise ScheduleParseError("empty interval")

    # Bare number ⇒ hours
    if _BARE_NUMBER_RE.match(text):
        amount = float(text)
        seconds = amount * 3600.0
        return ParsedSchedule(
            kind="interval",
            raw=text,
            every_seconds=seconds,
            parts=((amount, "h"),),
        )

    # Allow spaces between segments: "1h 30m", "1 h 30 m", "1h30m"
    compacted = text
    parts: list[tuple[float, str]] = []
    total = 0.0
    pos = 0
    length = len(compacted)
    while pos < length:
        while pos < length and compacted[pos].isspace():
            pos += 1
        if pos >= length:
            break
        m = _SEGMENT_RE.match(compacted, pos)
        if not m:
            raise ScheduleParseError(f"unparsed schedule fragment at {compacted[pos:]!r}")
        num = float(m.group("num"))
        raw_unit = m.group("unit")
        # If unit missing mid-stream, only bare-number rule applies to whole string
        if raw_unit is None:
            # Trailing bare number without unit is illegal in multi-segment;
            # single bare already handled above.
            raise ScheduleParseError(
                f"missing unit after {num} (default hours only for a bare number alone)"
            )
        unit = _canon_unit(raw_unit, default_hours=False)
        parts.append((num, unit))
        total += num * _UNIT_SECONDS[unit]
        pos = m.end()

    if not parts:
        raise ScheduleParseError(f"could not parse interval: {text!r}")

    return ParsedSchedule(
        kind="interval",
        raw=text,
        every_seconds=total,
        parts=tuple(parts),
    )


def parse_schedule_args(args: list[str] | str | None) -> ParsedSchedule:
    """
    Parse schedule CLI/HTTP args into a ParsedSchedule.

    Accepts a list of tokens (as from argparse) or a single string.
    """
    if args is None:
        raise ScheduleParseError("no schedule arguments")
    if isinstance(args, str):
        tokens = args.strip().split()
        raw = args.strip()
    else:
        tokens = [str(a).strip() for a in args if str(a).strip()]
        raw = " ".join(tokens)

    if not tokens:
        raise ScheduleParseError("no schedule arguments")

    # Single named cadence
    if len(tokens) == 1:
        key = tokens[0].lower()
        if key in _NAMED:
            meta = _NAMED[key]
            return ParsedSchedule(
                kind="named",
                raw=raw,
                every_seconds=meta.get("every_seconds"),
                name=str(meta["name"]),
                calendar=meta.get("calendar"),
            )

    # Interval: join tokens so "1 h 30 m" and "1h30m" both work
    body = "".join(tokens) if all(_is_interval_token(t) for t in tokens) else " ".join(tokens)
    # Prefer glued form when tokens look like interval pieces; else use spaced join
    # for the parser which tolerates spaces.
    try:
        return _parse_interval_body(" ".join(tokens))
    except ScheduleParseError:
        # Retry with no spaces (e.g. user passed 1h 30m already fine; 1h30m as one token)
        if body != " ".join(tokens):
            return _parse_interval_body(body)
        raise


def _is_interval_token(tok: str) -> bool:
    t = tok.lower()
    if _BARE_NUMBER_RE.match(t):
        return True
    if t in _NAMED:
        return False
    return bool(_SEGMENT_RE.fullmatch(t))


def parse_schedule(*args: str) -> ParsedSchedule:
    """Vararg convenience wrapper."""
    return parse_schedule_args(list(args))


def describe(parsed: ParsedSchedule) -> str:
    """Human-readable one-liner."""
    if parsed.kind == "named":
        if parsed.calendar:
            return f"every {parsed.name} (calendar {parsed.calendar})"
        secs = parsed.every_seconds or 0
        return f"every {parsed.name} ({secs:g}s)"
    if parsed.parts:
        bits = "".join(f"{int(a) if a == int(a) else a}{u}" for a, u in parsed.parts)
        return f"every {bits} ({parsed.every_seconds:g}s)"
    return f"every {parsed.every_seconds:g}s"
