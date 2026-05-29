from __future__ import annotations

from application.repositories import PinglyRepository


class AnalyticsService:
    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def tutor_dashboard(self, tutor_user_id: str) -> dict:
        return await self.repo.analytics_for_tutor(tutor_user_id)
