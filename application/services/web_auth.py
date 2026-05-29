from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from application.repositories import PinglyRepository


class WebAuthService:
    def __init__(self, repo: PinglyRepository, base_url: str) -> None:
        self.repo = repo
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def create_login_link_for_tg(self, tg_id: int) -> str | None:
        user = await self.repo.get_user_by_tg_id(tg_id)
        if not user:
            return None
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        await self.repo.create_web_token(user["id"], self._hash(token), expires_at)
        return f"{self.base_url}/auth/telegram?token={token}"

    async def consume_login_token(self, token: str) -> dict | None:
        return await self.repo.consume_web_token(self._hash(token), datetime.now(timezone.utc))
