from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from application.repositories import PinglyRepository
from domain import LessonStatus, NotificationType


class LessonService:
    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def create_recurring_lesson(self, tutor_tg_id: int, student_id: str, day_of_week: int, lesson_time: str, duration_minutes: int = 60) -> dict:
        tutor = await self.repo.get_user_by_tg_id(tutor_tg_id)
        if not tutor or tutor["role"] != "tutor":
            raise PermissionError("Only tutors can create lessons")
        return await self.create_recurring_lesson_for_user(tutor["id"], student_id, day_of_week, lesson_time, duration_minutes)

    async def create_recurring_lesson_for_user(self, tutor_user_id: str, student_id: str, day_of_week: int, lesson_time: str, duration_minutes: int = 60) -> dict:
        tutor = await self.repo.get_user_by_id(tutor_user_id)
        if not tutor or tutor["role"] != "tutor":
            raise PermissionError("Only tutors can create lessons")
        student = await self.repo.get_student_for_tutor(tutor["id"], student_id)
        if not student:
            raise PermissionError("Student does not belong to tutor")
        rule = await self.repo.create_schedule_rule(tutor_user_id, student_id, day_of_week, lesson_time, duration_minutes)
        await self.generate_future_lessons_for_rule(tutor_user_id, student_id, rule["id"], day_of_week, lesson_time, weeks=4)
        return rule

    async def generate_future_lessons_for_rule(self, tutor_user_id: str, student_id: str, rule_id: str, day_of_week: int, lesson_time: str, weeks: int = 4) -> list[dict]:
        now = datetime.now(timezone.utc)
        hour, minute = map(int, lesson_time[:5].split(":"))
        days_ahead = (day_of_week - now.weekday()) % 7
        first_date = now + timedelta(days=days_ahead)
        lessons = []
        for week in range(weeks):
            starts_at = first_date + timedelta(days=week * 7)
            starts_at = starts_at.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if starts_at <= now:
                starts_at += timedelta(days=7)
            lesson = await self.repo.create_lesson(tutor_user_id, student_id, starts_at, schedule_rule_id=rule_id)
            lessons.append(lesson)
            student_user_id = lesson.get("student_user_id")
            if student_user_id:
                for ntype, delta, title in (
                    (NotificationType.LESSON_DAY_BEFORE, timedelta(days=1), "Занятие завтра"),
                    (NotificationType.LESSON_HOUR_BEFORE, timedelta(hours=1), "Занятие через час"),
                ):
                    await self.repo.create_notification(
                        student_user_id,
                        ntype.value,
                        title,
                        f"Занятие начнётся {starts_at.strftime('%d.%m в %H:%M')}",
                        {"lesson_id": lesson["id"]},
                        starts_at - delta,
                    )
        return lessons

    async def list_tutor_calendar(self, tutor_user_id: str) -> list[dict]:
        return await self.repo.list_lessons_for_tutor(tutor_user_id)

    async def list_student_calendar(self, student_user_id: str) -> list[dict]:
        return await self.repo.list_lessons_for_student_user(student_user_id)

    async def next_lesson_for_student(self, student_user_id: str) -> dict | None:
        return await self.repo.get_next_lesson_for_student_user(student_user_id)

    async def change_lesson_status(self, tutor_user_id: str, lesson_id: str, status: LessonStatus, starts_at: datetime | None = None) -> dict | None:
        lesson = await self.repo.update_lesson_status(tutor_user_id, lesson_id, status.value, starts_at)
        if lesson and status == LessonStatus.RESCHEDULED:
            student_user_id = lesson.get("student_user_id")
            if student_user_id:
                await self.repo.create_notification(
                    student_user_id,
                    NotificationType.LESSON_RESCHEDULED.value,
                    "Занятие перенесено",
                    "Репетитор изменил время занятия.",
                    {"lesson_id": lesson_id},
                )
        return lesson
