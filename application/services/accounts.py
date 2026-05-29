from __future__ import annotations

from application.repositories import PinglyRepository


class AccountService:
    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def get_user(self, user_id: str) -> dict | None:
        return await self.repo.get_user_by_id(user_id)

    async def get_by_tg_id(self, tg_id: int) -> dict | None:
        return await self.repo.get_user_by_tg_id(tg_id)

    async def choose_role(self, role: str, tg_id: int, full_name: str, tg_username: str | None) -> dict:
        if role not in {"student", "tutor"}:
            raise ValueError("Invalid role")
        return await self.repo.upsert_user(role, tg_id, full_name, tg_username)

    async def change_role(self, tg_id: int, role: str) -> dict | None:
        user = await self.repo.get_user_by_tg_id(tg_id)
        if not user:
            return None
        return await self.repo.update_user_profile(user["id"], role=role)

    async def update_name(self, tg_id: int, full_name: str) -> dict | None:
        user = await self.repo.get_user_by_tg_id(tg_id)
        if not user:
            return None
        return await self.repo.update_user_profile(user["id"], full_name=full_name)
