from __future__ import annotations

import secrets

from application.repositories import PinglyRepository


class StudentService:
    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def ensure_tutor(self, tg_id: int, full_name: str, tg_username: str | None) -> dict:
        return await self.repo.upsert_tutor_user(tg_id, full_name, tg_username)

    async def create_student_invite(self, tutor_tg_id: int, name: str, tg_username: str) -> dict:
        tutor = await self.repo.get_user_by_tg_id(tutor_tg_id)
        if not tutor or tutor["role"] != "tutor":
            raise PermissionError("Only tutors can add students")
        token = secrets.token_urlsafe(12)
        return await self.repo.create_invited_student(tutor["id"], name.strip(), tg_username.strip().lstrip("@"), token)

    async def link_student_from_invite(self, token: str, tg_id: int, full_name: str, tg_username: str | None) -> dict | None:
        return await self.repo.link_student_to_tg(token, tg_id, full_name, tg_username)

    async def list_students(self, tutor_tg_id: int, search: str | None = None) -> list[dict]:
        tutor = await self.repo.get_user_by_tg_id(tutor_tg_id)
        if not tutor or tutor["role"] != "tutor":
            return []
        return await self.repo.list_tutor_students(tutor["id"], search)

    async def list_students_by_user(self, tutor_user_id: str, search: str | None = None) -> list[dict]:
        return await self.repo.list_tutor_students(tutor_user_id, search)

    async def student_card(self, tutor_user_id: str, student_id: str) -> dict:
        student = await self.repo.get_student_for_tutor(tutor_user_id, student_id)
        if not student:
            raise PermissionError("Student does not belong to tutor")
        lessons = [l for l in await self.repo.list_lessons_for_tutor(tutor_user_id, 1000) if l.get("student_id") == student_id]
        homework = [h for h in await self.repo.list_homework_for_tutor(tutor_user_id, 1000) if h.get("student_id") == student_id]
        completed = len([l for l in lessons if l.get("status") == "completed"])
        cancelled = len([l for l in lessons if l.get("status") == "cancelled"])
        reviewed = len([h for h in homework if h.get("status") == "reviewed"])
        return {
            "student": student,
            "lessons": lessons,
            "homework": homework,
            "progress": {
                "completed_lessons": completed,
                "attendance_percent": round(completed / (completed + cancelled) * 100) if completed + cancelled else 100,
                "homework_completion_percent": round(reviewed / len(homework) * 100) if homework else 0,
            },
        }
