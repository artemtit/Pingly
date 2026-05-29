from __future__ import annotations

from datetime import datetime
from typing import Any

import db


def _one(result: Any) -> dict[str, Any] | None:
    return result.data[0] if result.data else None


class SupabasePinglyRepository:
    def _db(self):
        return db.client()

    async def get_user_by_tg_id(self, tg_id: int) -> dict[str, Any] | None:
        result = await self._db().table("users").select("*").eq("tg_id", tg_id).execute()
        return _one(result)

    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        result = await self._db().table("users").select("*").eq("id", user_id).execute()
        return _one(result)

    async def upsert_user(self, role: str, tg_id: int, full_name: str, tg_username: str | None) -> dict[str, Any]:
        existing = await self.get_user_by_tg_id(tg_id)
        if existing:
            if existing["role"] != role:
                updated = await self.update_user_profile(existing["id"], role=role)
                return updated or existing
            return existing

        result = await self._db().table("users").insert({
            "role": role,
            "tg_id": tg_id,
            "tg_username": tg_username,
            "full_name": full_name,
        }).execute()
        user = result.data[0]
        if role == "tutor":
            await self._db().table("tutor_profiles").insert({
                "user_id": user["id"],
                "display_name": full_name,
            }).execute()
        else:
            await self._db().table("student_profiles").insert({
                "user_id": user["id"],
                "name": full_name,
                "tg_username": tg_username,
                "invite_token": f"self_{user['id']}",
                "status": "active",
            }).execute()
        return user

    async def update_user_profile(self, user_id: str, full_name: str | None = None, role: str | None = None) -> dict[str, Any] | None:
        patch: dict[str, Any] = {}
        if full_name:
            patch["full_name"] = full_name
        if role:
            patch["role"] = role
        if not patch:
            return await self.get_user_by_id(user_id)
        result = await self._db().table("users").update(patch).eq("id", user_id).execute()
        user = _one(result)
        if not user:
            return None
        if full_name:
            if user["role"] == "tutor":
                await self._db().table("tutor_profiles").update({"display_name": full_name}).eq("user_id", user_id).execute()
            else:
                await self._db().table("student_profiles").update({"name": full_name}).eq("user_id", user_id).execute()
        if role == "tutor":
            profile = await self._db().table("tutor_profiles").select("id").eq("user_id", user_id).execute()
            if not profile.data:
                await self._db().table("tutor_profiles").insert({"user_id": user_id, "display_name": user["full_name"]}).execute()
        if role == "student":
            profile = await self._db().table("student_profiles").select("id").eq("user_id", user_id).execute()
            if not profile.data:
                await self._db().table("student_profiles").insert({
                    "user_id": user_id,
                    "name": user["full_name"],
                    "tg_username": user.get("tg_username"),
                    "invite_token": f"self_{user_id}",
                    "status": "active",
                }).execute()
        return user

    async def upsert_tutor_user(self, tg_id: int, full_name: str, tg_username: str | None) -> dict[str, Any]:
        return await self.upsert_user("tutor", tg_id, full_name, tg_username)

    async def create_invited_student(self, tutor_user_id: str, name: str, tg_username: str, invite_token: str) -> dict[str, Any]:
        result = await self._db().table("student_profiles").insert({
            "name": name,
            "tg_username": tg_username,
            "invite_token": invite_token,
            "status": "active",
        }).execute()
        student = result.data[0]
        await self._db().table("tutor_students").insert({
            "tutor_user_id": tutor_user_id,
            "student_id": student["id"],
            "status": "active",
        }).execute()
        return student

    async def get_student_by_invite_token(self, invite_token: str) -> dict[str, Any] | None:
        result = await self._db().table("student_profiles").select("*").eq("invite_token", invite_token).execute()
        return _one(result)

    async def link_student_to_tg(self, invite_token: str, tg_id: int, full_name: str, tg_username: str | None) -> dict[str, Any] | None:
        student = await self.get_student_by_invite_token(invite_token)
        if not student:
            return None
        user = await self.get_user_by_tg_id(tg_id)
        if not user:
            result = await self._db().table("users").insert({
                "role": "student",
                "tg_id": tg_id,
                "tg_username": tg_username or student.get("tg_username"),
                "full_name": full_name or student["name"],
            }).execute()
            user = result.data[0]
        await self._db().table("student_profiles").update({
            "user_id": user["id"],
            "tg_username": tg_username or student.get("tg_username"),
        }).eq("id", student["id"]).execute()
        student["user_id"] = user["id"]
        return student

    async def list_tutor_students(self, tutor_user_id: str, search: str | None = None) -> list[dict[str, Any]]:
        query = (
            self._db().table("tutor_students")
            .select("student_id, status, student_profiles(*)")
            .eq("tutor_user_id", tutor_user_id)
            .order("created_at", desc=True)
        )
        result = await query.execute()
        students = [{**row["student_profiles"], "relation_status": row["status"]} for row in result.data]
        if search:
            needle = search.lower()
            students = [s for s in students if needle in s.get("name", "").lower() or needle in (s.get("tg_username") or "").lower()]
        return students

    async def get_student_for_tutor(self, tutor_user_id: str, student_id: str) -> dict[str, Any] | None:
        result = await (
            self._db().table("tutor_students")
            .select("student_profiles(*)")
            .eq("tutor_user_id", tutor_user_id)
            .eq("student_id", student_id)
            .execute()
        )
        row = _one(result)
        return row["student_profiles"] if row else None

    async def get_student_for_user(self, student_user_id: str) -> dict[str, Any] | None:
        result = await self._db().table("student_profiles").select("*").eq("user_id", student_user_id).execute()
        return _one(result)

    async def update_student_profile(self, student_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        clean = {k: v for k, v in patch.items() if v is not None}
        if not clean:
            result = await self._db().table("student_profiles").select("*").eq("id", student_id).execute()
            return _one(result)
        result = await self._db().table("student_profiles").update(clean).eq("id", student_id).execute()
        return _one(result)

    async def get_tutor_student_relation(self, tutor_user_id: str, student_id: str) -> dict[str, Any] | None:
        result = await (
            self._db().table("tutor_students")
            .select("*")
            .eq("tutor_user_id", tutor_user_id)
            .eq("student_id", student_id)
            .execute()
        )
        return _one(result)

    async def set_tutor_student_note(self, tutor_user_id: str, student_id: str, note: str | None) -> None:
        await (
            self._db().table("tutor_students")
            .update({"private_tutor_note": note})
            .eq("tutor_user_id", tutor_user_id)
            .eq("student_id", student_id)
            .execute()
        )

    async def create_schedule_rule(
        self,
        tutor_user_id: str,
        student_id: str,
        day_of_week: int,
        lesson_time: str,
        duration_minutes: int,
        recurrence: str = "weekly",
        interval_n: int = 1,
        weekdays: list[int] | None = None,
        start_date: str | None = None,
    ) -> dict[str, Any]:
        result = await self._db().table("schedule_rules").insert({
            "tutor_user_id": tutor_user_id,
            "student_id": student_id,
            "day_of_week": day_of_week,
            "lesson_time": lesson_time,
            "duration_minutes": duration_minutes,
            "recurrence": recurrence,
            "interval_n": interval_n,
            "weekdays": weekdays if weekdays is not None else [day_of_week],
            "start_date": start_date,
            "is_active": True,
        }).execute()
        return result.data[0]

    async def get_schedule_rule(self, tutor_user_id: str, rule_id: str) -> dict[str, Any] | None:
        result = await (
            self._db().table("schedule_rules")
            .select("*")
            .eq("id", rule_id)
            .eq("tutor_user_id", tutor_user_id)
            .execute()
        )
        return _one(result)

    async def update_schedule_rule(self, rule_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        result = await self._db().table("schedule_rules").update(patch).eq("id", rule_id).execute()
        return _one(result)

    async def list_future_lessons_for_rule(self, rule_id: str, after: datetime) -> list[dict[str, Any]]:
        result = await (
            self._db().table("lessons_v2")
            .select("*")
            .eq("schedule_rule_id", rule_id)
            .eq("status", "scheduled")
            .gte("starts_at", after.isoformat())
            .order("starts_at")
            .execute()
        )
        return result.data

    async def get_lesson_for_tutor(self, tutor_user_id: str, lesson_id: str) -> dict[str, Any] | None:
        result = await (
            self._db().table("lessons_v2")
            .select("*, student_profiles(name, tg_username)")
            .eq("id", lesson_id)
            .eq("tutor_user_id", tutor_user_id)
            .execute()
        )
        return _one(result)

    async def update_lesson_fields(self, lesson_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        result = await self._db().table("lessons_v2").update(patch).eq("id", lesson_id).execute()
        return _one(result)

    async def create_lesson(self, tutor_user_id: str, student_id: str, starts_at: datetime, subject_id: str | None = None, schedule_rule_id: str | None = None) -> dict[str, Any]:
        student = await self.get_student_for_tutor(tutor_user_id, student_id)
        result = await self._db().table("lessons_v2").insert({
            "tutor_user_id": tutor_user_id,
            "student_id": student_id,
            "student_user_id": student.get("user_id") if student else None,
            "subject_id": subject_id,
            "schedule_rule_id": schedule_rule_id,
            "starts_at": starts_at.isoformat(),
            "status": "scheduled",
        }).execute()
        return result.data[0]

    async def list_lessons_for_tutor(self, tutor_user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        result = await (
            self._db().table("lessons_v2")
            .select("*, student_profiles(name, tg_username)")
            .eq("tutor_user_id", tutor_user_id)
            .order("starts_at")
            .limit(limit)
            .execute()
        )
        return result.data

    async def list_lessons_for_student_user(self, student_user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        result = await (
            self._db().table("lessons_v2")
            .select("*")
            .eq("student_user_id", student_user_id)
            .order("starts_at")
            .limit(limit)
            .execute()
        )
        return result.data

    async def get_next_lesson_for_student_user(self, student_user_id: str) -> dict[str, Any] | None:
        result = await (
            self._db().table("lessons_v2")
            .select("*")
            .eq("student_user_id", student_user_id)
            .eq("status", "scheduled")
            .gte("starts_at", datetime.utcnow().isoformat())
            .order("starts_at")
            .limit(1)
            .execute()
        )
        return _one(result)

    async def update_lesson_status(self, tutor_user_id: str, lesson_id: str, status: str, starts_at: datetime | None = None) -> dict[str, Any] | None:
        patch: dict[str, Any] = {"status": status}
        if starts_at:
            patch["starts_at"] = starts_at.isoformat()
        result = await (
            self._db().table("lessons_v2")
            .update(patch)
            .eq("id", lesson_id)
            .eq("tutor_user_id", tutor_user_id)
            .execute()
        )
        return _one(result)

    async def create_homework(self, tutor_user_id: str, student_id: str, title: str, description: str | None, due_at: datetime | None) -> dict[str, Any]:
        student = await self.get_student_for_tutor(tutor_user_id, student_id)
        result = await self._db().table("homeworks").insert({
            "tutor_user_id": tutor_user_id,
            "student_id": student_id,
            "student_user_id": student.get("user_id") if student else None,
            "title": title,
            "description": description,
            "due_at": due_at.isoformat() if due_at else None,
            "status": "new",
        }).execute()
        return result.data[0]

    async def list_homework_for_tutor(self, tutor_user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        result = await (
            self._db().table("homeworks")
            .select("*, student_profiles(name, tg_username)")
            .eq("tutor_user_id", tutor_user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data

    async def list_homework_for_student_user(self, student_user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        result = await (
            self._db().table("homeworks")
            .select("*")
            .eq("student_user_id", student_user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data

    async def update_homework_status(self, user_id: str, homework_id: str, status: str, tutor_comment: str | None = None) -> dict[str, Any] | None:
        user = await self.get_user_by_id(user_id)
        if not user:
            return None
        patch: dict[str, Any] = {"status": status}
        if tutor_comment is not None:
            patch["tutor_comment"] = tutor_comment
        query = self._db().table("homeworks").update(patch).eq("id", homework_id)
        if user["role"] == "tutor":
            query = query.eq("tutor_user_id", user_id)
        else:
            query = query.eq("student_user_id", user_id)
            if status not in {"in_progress", "submitted"}:
                return None
        result = await query.execute()
        return _one(result)

    async def create_notification(self, user_id: str, ntype: str, title: str, body: str, payload: dict[str, Any] | None = None, scheduled_for: datetime | None = None) -> dict[str, Any]:
        result = await self._db().table("notifications").insert({
            "user_id": user_id,
            "type": ntype,
            "title": title,
            "body": body,
            "payload": payload or {},
            "channel": "telegram",
            "status": "pending",
            "scheduled_for": (scheduled_for or datetime.utcnow()).isoformat(),
        }).execute()
        return result.data[0]

    async def list_notifications_for_user(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        result = await (
            self._db().table("notifications")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data

    async def list_due_notifications(self, now: datetime, limit: int = 100) -> list[dict[str, Any]]:
        result = await (
            self._db().table("notifications")
            .select("*, users(tg_id)")
            .eq("status", "pending")
            .lte("scheduled_for", now.isoformat())
            .limit(limit)
            .execute()
        )
        return result.data

    async def mark_notification_sent(self, notification_id: str) -> None:
        await self._db().table("notifications").update({"status": "sent"}).eq("id", notification_id).execute()

    async def analytics_for_tutor(self, tutor_user_id: str) -> dict[str, Any]:
        students = await self.list_tutor_students(tutor_user_id)
        lessons = await self.list_lessons_for_tutor(tutor_user_id, 1000)
        homework = await self.list_homework_for_tutor(tutor_user_id, 1000)
        completed_lessons = [l for l in lessons if l.get("status") == "completed"]
        active_hw = [h for h in homework if h.get("status") in ("new", "in_progress", "submitted")]
        reviewed_hw = [h for h in homework if h.get("status") == "reviewed"]
        cancelled = [l for l in lessons if l.get("status") == "cancelled"]
        total_finished = len(completed_lessons) + len(cancelled)
        return {
            "students_count": len(students),
            "completed_lessons": len(completed_lessons),
            "active_homework": len(active_hw),
            "homework_completion_percent": round(len(reviewed_hw) / len(homework) * 100) if homework else 0,
            "attendance_percent": round(len(completed_lessons) / total_finished * 100) if total_finished else 100,
        }

    async def create_web_token(self, user_id: str, token_hash: str, expires_at: datetime) -> None:
        await self._db().table("web_login_tokens").insert({
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at.isoformat(),
            "used_at": None,
        }).execute()

    async def consume_web_token(self, token_hash: str, now: datetime) -> dict[str, Any] | None:
        result = await (
            self._db().table("web_login_tokens")
            .select("*, users(*)")
            .eq("token_hash", token_hash)
            .is_("used_at", "null")
            .gte("expires_at", now.isoformat())
            .limit(1)
            .execute()
        )
        row = _one(result)
        if not row:
            return None
        await self._db().table("web_login_tokens").update({"used_at": now.isoformat()}).eq("id", row["id"]).execute()
        return row["users"]
