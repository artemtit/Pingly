from __future__ import annotations

from datetime import datetime, timedelta, timezone

from application.services.lessons import package_status


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def test_package_status_none_without_size():
    assert package_status({"package_size": None, "package_started_at": None}, []) is None


def test_package_status_counts_completed_and_confirmed_past():
    now = datetime.now(timezone.utc)
    lessons = [
        {"status": "completed", "starts_at": _iso(now - timedelta(days=3))},
        {"status": "confirmed", "starts_at": _iso(now - timedelta(days=1))},  # in the past -> consumed
        {"status": "confirmed", "starts_at": _iso(now + timedelta(days=1))},  # future -> not consumed
        {"status": "cancelled", "starts_at": _iso(now - timedelta(days=2))},  # never consumes
    ]
    status = package_status({"package_size": 5, "package_started_at": None}, lessons)
    assert status == {
        "size": 5,
        "started_at": None,
        "consumed": 2,
        "remaining": 3,
    }


def test_package_status_ignores_lessons_before_cycle_start():
    now = datetime.now(timezone.utc)
    started_at = _iso(now - timedelta(days=1))
    lessons = [
        {"status": "completed", "starts_at": _iso(now - timedelta(days=10))},  # before new cycle
        {"status": "completed", "starts_at": _iso(now)},  # within new cycle
    ]
    status = package_status({"package_size": 4, "package_started_at": started_at}, lessons)
    assert status["consumed"] == 1
    assert status["remaining"] == 3


def test_package_status_remaining_never_negative():
    now = datetime.now(timezone.utc)
    lessons = [{"status": "completed", "starts_at": _iso(now)} for _ in range(5)]
    status = package_status({"package_size": 2, "package_started_at": None}, lessons)
    assert status["consumed"] == 5
    assert status["remaining"] == 0
