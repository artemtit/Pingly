from __future__ import annotations

import secrets
from datetime import datetime, timezone

from application.repositories import PinglyRepository

PROFILE_FIELDS = ("name", "subject_summary", "grade", "level", "goal", "started_at", "progress_note", "status", "default_price")


def _parse_dt(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


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

    async def create_student_for_user(
        self, tutor_user_id: str, name: str, tg_username: str = "", subject_summary: str | None = None,
    ) -> dict:
        token = secrets.token_urlsafe(12)
        username = (tg_username or "").strip().lstrip("@")
        student = await self.repo.create_invited_student(tutor_user_id, name.strip(), username, token)
        subject = (subject_summary or "").strip()
        if subject:
            await self.repo.update_student_profile(student["id"], {"subject_summary": subject})
            student["subject_summary"] = subject
        return student

    async def link_student_from_invite(self, token: str, tg_id: int, full_name: str, tg_username: str | None) -> dict | None:
        return await self.repo.link_student_to_tg(token, tg_id, full_name, tg_username)

    async def list_students(self, tutor_tg_id: int, search: str | None = None) -> list[dict]:
        tutor = await self.repo.get_user_by_tg_id(tutor_tg_id)
        if not tutor or tutor["role"] != "tutor":
            return []
        return await self.repo.list_tutor_students(tutor["id"], search)

    async def list_students_by_user(self, tutor_user_id: str, search: str | None = None) -> list[dict]:
        return await self.repo.list_tutor_students(tutor_user_id, search)

    async def update_profile(self, tutor_user_id: str, student_id: str, fields: dict) -> dict | None:
        relation = await self.repo.get_tutor_student_relation(tutor_user_id, student_id)
        if not relation:
            raise PermissionError("Student does not belong to tutor")
        patch = {k: v for k, v in fields.items() if k in PROFILE_FIELDS}
        return await self.repo.update_student_profile(student_id, patch)

    async def set_note(self, tutor_user_id: str, student_id: str, note: str | None) -> None:
        relation = await self.repo.get_tutor_student_relation(tutor_user_id, student_id)
        if not relation:
            raise PermissionError("Student does not belong to tutor")
        await self.repo.set_tutor_student_note(tutor_user_id, student_id, note)

    async def delete_student(self, tutor_user_id: str, student_id: str) -> dict:
        """Remove a student. If this was their only tutor, the profile and the
        connected Telegram account are deleted (which invalidates the invite link
        and removes all their lessons/homework). Returns info so the caller can
        send a goodbye message to the student.
        """
        relation = await self.repo.get_tutor_student_relation(tutor_user_id, student_id)
        if not relation:
            raise PermissionError("Student does not belong to tutor")

        profile = await self.repo.get_student_for_tutor(tutor_user_id, student_id)
        student_name = (profile or {}).get("name") or "Ученик"
        linked_user_id = (profile or {}).get("user_id")

        other_tutors = [t for t in await self.repo.list_tutor_ids_for_student(student_id) if t != tutor_user_id]
        if other_tutors:
            # Student is shared with another tutor — only detach this tutor.
            await self.repo.delete_tutor_student(tutor_user_id, student_id)
            return {"removed_account": False, "notify_tg_id": None, "student_name": student_name}

        notify_tg_id = None
        if linked_user_id:
            linked_user = await self.repo.get_user_by_id(linked_user_id)
            notify_tg_id = (linked_user or {}).get("tg_id")

        # Deleting the profile cascades lessons/homework/schedule_rules/relation
        # and frees the invite_token, so the invite link stops working.
        await self.repo.delete_student_profile(student_id)
        if linked_user_id:
            await self.repo.delete_user(linked_user_id)

        return {"removed_account": bool(linked_user_id), "notify_tg_id": notify_tg_id, "student_name": student_name}

    async def has_student_profile(self, tg_id: int) -> bool:
        user = await self.repo.get_user_by_tg_id(tg_id)
        if not user:
            return False
        student = await self.repo.get_student_for_user(user["id"])
        return student is not None

    async def student_card(self, tutor_user_id: str, student_id: str) -> dict:
        student = await self.repo.get_student_for_tutor(tutor_user_id, student_id)
        if not student:
            raise PermissionError("Student does not belong to tutor")
        relation = await self.repo.get_tutor_student_relation(tutor_user_id, student_id)
        lessons = [l for l in await self.repo.list_lessons_for_tutor(tutor_user_id, 1000) if l.get("student_id") == student_id]
        homework = [h for h in await self.repo.list_homework_for_tutor(tutor_user_id, 1000) if h.get("student_id") == student_id]
        completed = len([l for l in lessons if l.get("status") == "completed"])
        cancelled = len([l for l in lessons if l.get("status") == "cancelled"])
        reviewed = len([h for h in homework if h.get("status") == "reviewed"])

        now = datetime.now(timezone.utc)
        future = sorted(
            [l for l in lessons if l.get("status") == "scheduled" and (_parse_dt(l.get("starts_at")) or now) >= now],
            key=lambda l: l.get("starts_at") or "",
        )
        next_lesson = future[0] if future else None

        activity_dates = [
            _parse_dt(l.get("starts_at")) for l in lessons if l.get("status") == "completed"
        ] + [
            _parse_dt(h.get("updated_at") or h.get("created_at")) for h in homework if h.get("status") in ("submitted", "reviewed")
        ]
        activity_dates = [d for d in activity_dates if d]
        last_activity = max(activity_dates) if activity_dates else None

        return {
            "student": student,
            "note": (relation or {}).get("private_tutor_note") or "",
            "lessons": sorted(lessons, key=lambda l: l.get("starts_at") or "", reverse=True),
            "homework": homework,
            "next_lesson": next_lesson,
            "last_activity": last_activity.isoformat() if last_activity else None,
            "progress": {
                "completed_lessons": completed,
                "attendance_percent": round(completed / (completed + cancelled) * 100) if completed + cancelled else 100,
                "homework_completion_percent": round(reviewed / len(homework) * 100) if homework else 0,
            },
        }
