from __future__ import annotations

from web.app import _series_view


def test_weekly_single_day():
    rule = {"id": "r1", "student_id": "s1", "weekdays": [0], "lesson_time": "15:00:00", "recurrence": "weekly"}
    view = _series_view(rule, {"s1": "Вася"})
    assert view == {
        "id": "r1",
        "student_name": "Вася",
        "schedule_text": "Пн · каждую неделю · 15:00",
        "time_hhmm": "15:00",
    }


def test_multiple_weekly_renders_identically_to_weekly():
    """'weekly' and 'multiple_weekly' share the same branch in _series_view, so a
    multi-day rule under either recurrence value produces the same text — the two
    options are not visually distinguishable to the tutor."""
    common = {"id": "r1", "student_id": "s1", "weekdays": [0, 2], "lesson_time": "15:00:00"}
    weekly = _series_view({**common, "recurrence": "weekly"}, {})
    multiple = _series_view({**common, "recurrence": "multiple_weekly"}, {})
    assert weekly["schedule_text"] == multiple["schedule_text"] == "Пн, Ср · каждую неделю · 15:00"


def test_daily_ignores_weekdays():
    rule = {"id": "r1", "student_id": "s1", "weekdays": [1, 3], "lesson_time": "09:00:00", "recurrence": "daily"}
    view = _series_view(rule, {})
    assert view["schedule_text"] == "каждый день · 09:00"


def test_every_n_days():
    rule = {"id": "r1", "student_id": "s1", "lesson_time": "10:00:00", "recurrence": "every_n_days", "interval_n": 3}
    view = _series_view(rule, {})
    assert view["schedule_text"] == "каждые 3 дн. · 10:00"


def test_every_n_weeks():
    rule = {"id": "r1", "student_id": "s1", "weekdays": [4], "lesson_time": "18:30:00", "recurrence": "every_n_weeks", "interval_n": 2}
    view = _series_view(rule, {})
    assert view["schedule_text"] == "Пт · каждые 2 нед. · 18:30"


def test_weekdays_as_json_string():
    rule = {"id": "r1", "student_id": "s1", "weekdays": "[0, 1]", "lesson_time": "12:00:00", "recurrence": "weekly"}
    view = _series_view(rule, {})
    assert view["schedule_text"] == "Пн, Вт · каждую неделю · 12:00"


def test_malformed_weekdays_json_falls_back_to_day_of_week():
    rule = {"id": "r1", "student_id": "s1", "weekdays": "not-json", "day_of_week": 2, "lesson_time": "12:00:00", "recurrence": "weekly"}
    view = _series_view(rule, {})
    assert view["schedule_text"] == "Ср · каждую неделю · 12:00"


def test_unknown_student_falls_back_to_default_name():
    rule = {"id": "r1", "student_id": "missing", "weekdays": [0], "lesson_time": "10:00:00", "recurrence": "weekly"}
    view = _series_view(rule, {"other": "Петя"})
    assert view["student_name"] == "Ученик"


def test_missing_lesson_time_omits_time_suffix():
    rule = {"id": "r1", "student_id": "s1", "weekdays": [0], "lesson_time": "", "recurrence": "weekly"}
    view = _series_view(rule, {})
    assert view["schedule_text"] == "Пн · каждую неделю"
    assert view["time_hhmm"] == ""
