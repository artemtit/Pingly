from __future__ import annotations

from datetime import datetime, timedelta, timezone

from application.repositories import PinglyRepository
from application.services.lessons import _fmt_dt_local
from application.services.timezones import DEFAULT_TZ_OFFSET
from domain import HomeworkStatus, NotificationType


class HomeworkService:
    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def create_homework(self, tutor_user_id: str, student_id: str, title: str, description: str | None = None, due_at: datetime | None = None) -> dict:
        student = await self.repo.get_student_for_tutor(tutor_user_id, student_id)
        if not student:
            raise PermissionError("Student does not belong to tutor")
        homework = await self.repo.create_homework(tutor_user_id, student_id, title, description, due_at)
        if student.get("user_id"):
            await self.repo.create_notification(
                student["user_id"],
                NotificationType.HOMEWORK_CREATED.value,
                "Новое домашнее задание",
                title,
                {"homework_id": homework["id"]},
            )
            # F7: remind the student ~1 day before the deadline (if the tutor set
            # one and it's far enough away that a "срок завтра" nudge makes sense).
            tutor = await self.repo.get_user_by_id(tutor_user_id)
            offset = int((tutor or {}).get("tz_offset_minutes") or DEFAULT_TZ_OFFSET)
            await self._schedule_due_reminder(student["user_id"], homework, due_at, offset)
        return homework

    async def _schedule_due_reminder(self, student_user_id: str, homework: dict, due_at: datetime | None, offset: int = DEFAULT_TZ_OFFSET) -> None:
        if not due_at:
            return
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        send_at = due_at - timedelta(days=1)
        if send_at <= datetime.now(timezone.utc):
            return
        await self.repo.create_notification(
            student_user_id,
            NotificationType.HOMEWORK_DUE_SOON.value,
            "📚 Скоро дедлайн по домашке",
            f"Не забудь про «{homework['title']}» — сдать до {_fmt_dt_local(due_at, offset)}.",
            {"homework_id": homework["id"]},
            send_at,
        )

    async def list_for_tutor(self, tutor_user_id: str) -> list[dict]:
        return await self.repo.list_homework_for_tutor(tutor_user_id)

    async def list_for_student(self, student_user_id: str) -> list[dict]:
        return await self.repo.list_homework_for_student_user(student_user_id)

    async def mark_submitted(self, student_user_id: str, homework_id: str) -> dict | None:
        homework = await self.repo.update_homework_status(student_user_id, homework_id, HomeworkStatus.SUBMITTED.value)
        if homework:
            await self.repo.create_notification(
                homework["tutor_user_id"],
                NotificationType.HOMEWORK_SUBMITTED.value,
                "Ученик сдал домашнее задание",
                homework["title"],
                {"homework_id": homework_id, "student_id": homework.get("student_id")},
            )
        return homework

    async def mark_in_progress(self, student_user_id: str, homework_id: str) -> dict | None:
        return await self.repo.update_homework_status(student_user_id, homework_id, HomeworkStatus.IN_PROGRESS.value)

    # ---- templates ----
    async def list_templates(self, tutor_user_id: str) -> list[dict]:
        return await self.repo.list_homework_templates(tutor_user_id)

    async def create_template(self, tutor_user_id: str, title: str, description: str | None = None) -> dict | None:
        title = (title or "").strip()
        if not title:
            return None
        return await self.repo.create_homework_template(tutor_user_id, title, (description or "").strip() or None)

    async def delete_template(self, tutor_user_id: str, template_id: str) -> None:
        await self.repo.delete_homework_template(tutor_user_id, template_id)

    async def review(self, tutor_user_id: str, homework_id: str, comment: str | None = None) -> dict | None:
        homework = await self.repo.update_homework_status(tutor_user_id, homework_id, HomeworkStatus.REVIEWED.value, comment)
        if homework and homework.get("student_user_id"):
            await self.repo.create_notification(
                homework["student_user_id"],
                NotificationType.HOMEWORK_REVIEWED.value,
                "Домашнее задание проверено",
                homework["title"],
                {"homework_id": homework_id},
            )
        return homework
