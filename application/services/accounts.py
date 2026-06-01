from __future__ import annotations

from datetime import datetime, timezone

from application.repositories import PinglyRepository


def subscription_info(user: dict) -> dict:
    """Lightweight trial state for display (no hard paywall yet)."""
    status = user.get("subscription_status") or "trial"
    raw = user.get("trial_ends_at")
    days_left = None
    if raw:
        try:
            ends = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            seconds = (ends - datetime.now(timezone.utc)).total_seconds()
            days_left = max(0, -(-int(seconds) // 86400)) if seconds > 0 else 0
        except (ValueError, TypeError):
            days_left = None
    return {
        "status": status,
        "days_left": days_left,
        "active": status == "active" or (days_left is not None and days_left > 0),
        "trial_ends_at": raw,
    }


class AccountService:
    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def apply_referral(self, new_user_id: str, ref_code: str) -> bool:
        """Link a freshly registered tutor to a referrer and reward both with
        +30 trial days. Idempotent: skips if the new user is already referred."""
        code = (ref_code or "").strip()
        if not code:
            return False
        new_user = await self.repo.get_user_by_id(new_user_id)
        if not new_user or new_user.get("referred_by"):
            return False
        referrer = await self.repo.get_user_by_referral_code(code)
        if not referrer or referrer["id"] == new_user_id:
            return False
        await self.repo.set_referred_by(new_user_id, referrer["id"])
        await self.repo.extend_trial(referrer["id"], 30)
        await self.repo.extend_trial(new_user_id, 30)
        return True

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

    async def update_name_by_user_id(self, user_id: str, full_name: str) -> dict | None:
        full_name = (full_name or "").strip()
        if not full_name:
            return None
        return await self.repo.update_user_profile(user_id, full_name=full_name)
