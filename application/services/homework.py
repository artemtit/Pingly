from __future__ import annotations

from datetime import datetime

from application.repositories import PinglyRepository
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
        return homework

    async def list_for_tutor(self, tutor_user_id: str) -> list[dict]:
        return await self.repo.list_homework_for_tutor(tutor_user_id)

    async def list_for_student(self, student_user_id: str) -> list[dict]:
        return await self.repo.list_homework_for_student_user(student_user_id)

    async def mark_submitted(self, student_user_id: str, homework_id: str) -> dict | None:
        return await self.repo.update_homework_status(student_user_id, homework_id, HomeworkStatus.SUBMITTED.value)

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
