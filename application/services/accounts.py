from __future__ import annotations

from application.repositories import PinglyRepository


class AccountService:
    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def get_user(self, user_id: str) -> dict | None:
        return await self.repo.get_user_by_id(user_id)

    async def get_by_tg_id(self, tg_id: int) -> dict | None:
        return await self.repo.get_user_by_tg_id(tg_id)
