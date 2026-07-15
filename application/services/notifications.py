from __future__ import annotations

from datetime import datetime, timezone

from application.repositories import PinglyRepository


class NotificationService:
    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def list_for_user(self, user_id: str) -> list[dict]:
        return await self.repo.list_notifications_for_user(user_id)

    async def due_notifications(self) -> list[dict]:
        return await self.repo.list_due_notifications(datetime.now(timezone.utc))

    async def mark_sent(self, notification_id: str) -> None:
        await self.repo.mark_notification_sent(notification_id)
