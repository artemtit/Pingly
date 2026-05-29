"""Builds day / week / month calendar structures from a flat list of lessons."""
from __future__ import annotations

from datetime import date, datetime, timedelta

WEEKDAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTH_NAMES = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
STATUS_LABELS = {
    "scheduled": "🟢 Запланировано",
    "completed": "🔵 Проведено",
    "rescheduled": "🟡 Перенесено",
    "cancelled": "🔴 Отменено",
}


def _parse(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _student_name(lesson: dict) -> str:
    profile = lesson.get("student_profiles") or {}
    return profile.get("name") or "Занятие"


def _normalize(lessons: list[dict]) -> list[dict]:
    out = []
    for lesson in lessons:
        dt = _parse(lesson.get("starts_at"))
        if not dt:
            continue
        out.append({
            "id": lesson.get("id"),
            "dt": dt,
            "date": dt.date(),
            "time": dt.strftime("%H:%M"),
            "status": lesson.get("status", "scheduled"),
            "student": _student_name(lesson),
            "rule_id": lesson.get("schedule_rule_id"),
        })
    return sorted(out, key=lambda x: x["dt"])


def parse_anchor(raw: str | None) -> date:
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date.today()


def build_calendar(lessons: list[dict], view: str, anchor: date) -> dict:
    items = _normalize(lessons)
    by_day: dict[date, list[dict]] = {}
    for item in items:
        by_day.setdefault(item["date"], []).append(item)

    today = date.today()

    if view == "day":
        prev_a, next_a = anchor - timedelta(days=1), anchor + timedelta(days=1)
        title = f"{anchor.day} {MONTH_NAMES[anchor.month]} {anchor.year}"
        return {
            "view": "day", "anchor": anchor.isoformat(), "title": title,
            "prev": prev_a.isoformat(), "next": next_a.isoformat(), "today": today.isoformat(),
            "days": [{
                "date": anchor.isoformat(),
                "weekday": WEEKDAY_NAMES[anchor.weekday()],
                "day": anchor.day,
                "is_today": anchor == today,
                "lessons": by_day.get(anchor, []),
            }],
        }

    if view == "week":
        start = anchor - timedelta(days=anchor.weekday())
        days = []
        for i in range(7):
            d = start + timedelta(days=i)
            days.append({
                "date": d.isoformat(),
                "weekday": WEEKDAY_NAMES[i],
                "day": d.day,
                "is_today": d == today,
                "in_month": True,
                "lessons": by_day.get(d, []),
            })
        end = start + timedelta(days=6)
        title = f"{start.day} {MONTH_NAMES[start.month]} — {end.day} {MONTH_NAMES[end.month]}"
        return {
            "view": "week", "anchor": anchor.isoformat(), "title": title,
            "prev": (start - timedelta(days=7)).isoformat(),
            "next": (start + timedelta(days=7)).isoformat(),
            "today": today.isoformat(), "weekday_names": WEEKDAY_NAMES, "days": days,
        }

    # month
    first = anchor.replace(day=1)
    grid_start = first - timedelta(days=first.weekday())
    if first.month == 12:
        next_month = first.replace(year=first.year + 1, month=1)
    else:
        next_month = first.replace(month=first.month + 1)
    days = []
    cursor = grid_start
    while cursor < next_month or cursor.weekday() != 0:
        days.append({
            "date": cursor.isoformat(),
            "weekday": WEEKDAY_NAMES[cursor.weekday()],
            "day": cursor.day,
            "is_today": cursor == today,
            "in_month": cursor.month == first.month,
            "lessons": by_day.get(cursor, []),
        })
        cursor += timedelta(days=1)
        if len(days) >= 42:
            break
    prev_month = (first - timedelta(days=1)).replace(day=1)
    return {
        "view": "month", "anchor": anchor.isoformat(),
        "title": f"{MONTH_NAMES[first.month]} {first.year}",
        "prev": prev_month.isoformat(), "next": next_month.isoformat(),
        "today": today.isoformat(), "weekday_names": WEEKDAY_NAMES, "days": days,
    }
