from __future__ import annotations

from datetime import datetime, timedelta, timezone

from application.repositories import PinglyRepository
from domain import NotificationType


class NotificationService:
    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def list_for_user(self, user_id: str) -> list[dict]:
        return await self.repo.list_notifications_for_user(user_id)

    async def schedule_lesson_notifications(self, lesson: dict) -> None:
        student_user_id = lesson.get("student_user_id")
        starts_at_raw = lesson.get("starts_at")
        if not student_user_id or not starts_at_raw:
            return
        starts_at = datetime.fromisoformat(starts_at_raw.replace("Z", "+00:00")) if isinstance(starts_at_raw, str) else starts_at_raw
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

    async def due_notifications(self) -> list[dict]:
        return await self.repo.list_due_notifications(datetime.now(timezone.utc))

    async def mark_sent(self, notification_id: str) -> None:
        await self.repo.mark_notification_sent(notification_id)
