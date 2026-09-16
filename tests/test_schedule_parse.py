"""Exhaustive tests for schedule_parse (named + interval forms)."""

from __future__ import annotations

import pytest

from okstratr.schedule_parse import (
    ScheduleParseError,
    describe,
    parse_schedule,
    parse_schedule_args,
)


@pytest.mark.parametrize(
    "args,name,seconds,calendar",
    [
        (["hourly"], "hourly", 3600.0, None),
        (["daily"], "daily", 86400.0, None),
        (["weekly"], "weekly", 604800.0, None),
        (["monthly"], "monthly", None, "month"),
        (["yearly"], "yearly", None, "year"),
        (["annually"], "yearly", None, "year"),
        ("hourly", "hourly", 3600.0, None),
    ],
)
def test_named_cadences(args, name, seconds, calendar):
    p = parse_schedule_args(args)
    assert p.kind == "named"
    assert p.name == name
    assert p.every_seconds == seconds
    assert p.calendar == calendar


@pytest.mark.parametrize(
    "raw,seconds",
    [
        ("90", 90 * 3600),  # bare number ⇒ hours
        ("1", 3600),
        ("1.5", 1.5 * 3600),
        ("30m", 30 * 60),
        ("30min", 30 * 60),
        ("45 s", 45),
        ("2h", 2 * 3600),
        ("1h30m", 90 * 60),
        ("1h 30m", 90 * 60),
        ("1 h 30 m", 90 * 60),
        ("2d", 2 * 86400),
        ("1w", 604800),
        ("2wks", 2 * 604800),
        ("1w 2d", 604800 + 2 * 86400),
        ("90s", 90),
        ("10min", 600),
    ],
)
def test_intervals(raw, seconds):
    p = parse_schedule_args(raw)
    assert p.kind == "interval"
    assert p.every_seconds == pytest.approx(seconds)


def test_interval_token_list():
    p = parse_schedule("1h", "30m")
    assert p.every_seconds == pytest.approx(90 * 60)
    p2 = parse_schedule_args(["2", "wks"])
    assert p2.every_seconds == pytest.approx(2 * 604800)


def test_describe_and_dict():
    p = parse_schedule_args("1h30m")
    d = p.to_dict()
    assert d["kind"] == "interval"
    assert d["every_seconds"] == pytest.approx(5400)
    assert "1h30m" in describe(p) or "5400" in describe(p)


def test_errors():
    with pytest.raises(ScheduleParseError):
        parse_schedule_args([])
    with pytest.raises(ScheduleParseError):
        parse_schedule_args("")
    with pytest.raises(ScheduleParseError):
        parse_schedule_args("not-a-schedule")
    with pytest.raises(ScheduleParseError):
        parse_schedule_args("1x")  # unknown unit


def test_hourly_case_insensitive():
    assert parse_schedule_args("HOURLY").name == "hourly"


def test_schedule_module_summary_next_fire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKSTRATR_STATE_DIR", str(tmp_path / "st"))
    monkeypatch.setenv("OKSTRATR_HERDR_DRY_RUN", "1")
    import okstratr.desks as desks
    import okstratr.status as status
    import okstratr.dag as dag
    import okstratr.blackboard as bb

    desks._DEFAULT = None
    desks._DEFAULT_PATH = None
    status._loaded = False
    status._seated_objective = ""
    dag._DEFAULT = None
    bb._DEFAULT = None

    from okstratr import schedule

    desks.start("Scheduled", kind="work")
    desks.schedule("1h")
    summary = schedule.summary()
    assert summary["desk_schedules"] >= 1
    assert summary["next_fire"] is not None
    assert summary["next_fire"]["every_seconds"] == 3600.0
    assert summary["attention_window_next"] is True
