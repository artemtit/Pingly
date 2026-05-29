from __future__ import annotations

from datetime import date, datetime, timezone

# XP awarded per real event.
XP_COMPLETED_LESSON = 50
XP_REVIEWED_HOMEWORK = 40
XP_SUBMITTED_HOMEWORK = 15

RANK_TITLES = [
    (1, "Новичок"),
    (3, "Ученик"),
    (5, "Знаток"),
    (7, "Мастер"),
    (9, "Гуру"),
    (12, "Легенда"),
]


def _parse_dt(raw: object) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _level_for_xp(xp: int) -> tuple[int, int, int]:
    """Return (level, level_start_xp, next_level_xp). Each level needs 50 XP more than the last."""
    level = 1
    start = 0
    step = 100
    while xp >= start + step:
        start += step
        step += 50
        level += 1
    return level, start, start + step


def _rank_title(level: int) -> str:
    title = "Новичок"
    for threshold, name in RANK_TITLES:
        if level >= threshold:
            title = name
    return title


def _streak(activity_dates: set[date]) -> int:
    if not activity_dates:
        return 0
    today = datetime.now(timezone.utc).date()
    ordered = sorted(activity_dates, reverse=True)
    most_recent = ordered[0]
    # Streak is only "alive" if there was activity today or yesterday.
    if (today - most_recent).days > 1:
        return 0
    streak = 1
    cursor = most_recent
    for day in ordered[1:]:
        if (cursor - day).days == 1:
            streak += 1
            cursor = day
        elif (cursor - day).days == 0:
            continue
        else:
            break
    return streak


class GamificationService:
    """XP, levels, streaks and achievements — all derived from real lessons + homework."""

    def compute(self, lessons: list[dict], homework: list[dict]) -> dict:
        completed = [l for l in lessons if l.get("status") == "completed"]
        reviewed = [h for h in homework if h.get("status") == "reviewed"]
        submitted = [h for h in homework if h.get("status") in ("submitted", "reviewed")]

        xp = (
            len(completed) * XP_COMPLETED_LESSON
            + len(reviewed) * XP_REVIEWED_HOMEWORK
            + len(submitted) * XP_SUBMITTED_HOMEWORK
        )

        level, level_start, next_level_xp = _level_for_xp(xp)
        xp_into_level = xp - level_start
        xp_for_level = next_level_xp - level_start
        level_progress = round(xp_into_level / xp_for_level * 100) if xp_for_level else 0

        activity_dates: set[date] = set()
        for lesson in completed:
            dt = _parse_dt(lesson.get("starts_at"))
            if dt:
                activity_dates.add(dt.date())
        for hw in homework:
            if hw.get("status") in ("submitted", "reviewed"):
                dt = _parse_dt(hw.get("updated_at") or hw.get("created_at"))
                if dt:
                    activity_dates.add(dt.date())
        streak = _streak(activity_dates)

        achievements = self._achievements(len(completed), len(reviewed), streak, level)
        unlocked = [a for a in achievements if a["unlocked"]]

        return {
            "xp": xp,
            "level": level,
            "rank": _rank_title(level),
            "level_start": level_start,
            "next_level_xp": next_level_xp,
            "xp_into_level": xp_into_level,
            "xp_for_level": xp_for_level,
            "xp_to_next": max(next_level_xp - xp, 0),
            "level_progress_percent": min(level_progress, 100),
            "streak": streak,
            "achievements": achievements,
            "unlocked_count": len(unlocked),
            "total_achievements": len(achievements),
        }

    @staticmethod
    def _achievements(completed: int, reviewed: int, streak: int, level: int) -> list[dict]:
        defs = [
            ("first_lesson", "🎯", "Первый шаг", "Проведено первое занятие", completed >= 1),
            ("five_lessons", "🔥", "В ритме", "5 занятий проведено", completed >= 5),
            ("ten_lessons", "🏅", "Постоянство", "10 занятий проведено", completed >= 10),
            ("twenty_five_lessons", "💎", "Марафонец", "25 занятий проведено", completed >= 25),
            ("first_homework", "📝", "Старательный", "Первое ДЗ выполнено", reviewed >= 1),
            ("homework_master", "⭐", "Отличник", "10 ДЗ выполнено", reviewed >= 10),
            ("streak_3", "⚡", "Серия 3", "3 дня активности подряд", streak >= 3),
            ("streak_7", "🚀", "Неделя огня", "7 дней активности подряд", streak >= 7),
            ("level_5", "👑", "Знаток", "Достигнут 5 уровень", level >= 5),
        ]
        return [
            {"code": c, "emoji": e, "title": t, "description": d, "unlocked": bool(u)}
            for c, e, t, d, u in defs
        ]
