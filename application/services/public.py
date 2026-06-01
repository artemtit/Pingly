from __future__ import annotations

import re

from application.repositories import PinglyRepository
from domain import NotificationType

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def normalize_slug(raw: str) -> str:
    slug = (raw or "").strip().lower().replace(" ", "-")
    slug = _SLUG_RE.sub("", slug).strip("-")
    return slug[:32]


class PublicService:
    """Tutor public booking page (/u/<slug>) and the leads it produces."""

    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def get_profile(self, tutor_user_id: str) -> dict | None:
        return await self.repo.get_tutor_profile(tutor_user_id)

    async def get_public_profile(self, slug: str) -> dict | None:
        profile = await self.repo.get_tutor_profile_by_slug((slug or "").strip())
        if not profile or not profile.get("public_enabled"):
            return None
        return profile

    async def update_profile(self, tutor_user_id: str, slug: str, bio: str, subjects: str, public_enabled: bool) -> tuple[dict | None, str | None]:
        slug = normalize_slug(slug)
        if public_enabled and len(slug) < 3:
            return None, "Адрес страницы — минимум 3 символа (латиница, цифры, дефис)"
        if slug:
            existing = await self.repo.get_tutor_profile_by_slug(slug)
            if existing and existing.get("user_id") != tutor_user_id:
                return None, "Этот адрес уже занят — выбери другой"
        patch = {
            "slug": slug or None,
            "bio": (bio or "").strip() or None,
            "subjects": (subjects or "").strip() or None,
            "public_enabled": public_enabled,
        }
        # update_tutor_profile drops None values, so push booleans/empties explicitly
        profile = await self.repo.update_tutor_profile(tutor_user_id, {
            **{k: v for k, v in patch.items() if v is not None},
            "public_enabled": public_enabled,
        })
        return profile, None

    async def create_booking(self, slug: str, name: str, contact: str, preferred_time: str, comment: str) -> dict | None:
        profile = await self.get_public_profile(slug)
        if not profile:
            return None
        name = (name or "").strip()
        contact = (contact or "").strip()
        if not name or not contact:
            return None
        tutor_user_id = profile["user_id"]
        request = await self.repo.create_booking_request(
            tutor_user_id, name, contact,
            (preferred_time or "").strip() or None,
            (comment or "").strip() or None,
        )
        await self.repo.create_notification(
            tutor_user_id,
            NotificationType.BOOKING_REQUEST.value,
            "🎓 Новая заявка на занятие",
            f"{name} ({contact}) хочет записаться. Открой кабинет → Заявки.",
            {"request_id": request["id"]},
        )
        return request

    async def list_requests(self, tutor_user_id: str) -> list[dict]:
        return await self.repo.list_booking_requests(tutor_user_id)

    async def mark_request(self, tutor_user_id: str, request_id: str, status: str) -> None:
        if status not in {"new", "done", "archived"}:
            return
        await self.repo.update_booking_request_status(tutor_user_id, request_id, status)

    async def booking_push_target(self, tutor_user_id: str, name: str, contact: str) -> tuple[int, str] | None:
        tutor = await self.repo.get_user_by_id(tutor_user_id)
        tg_id = (tutor or {}).get("tg_id")
        if not tg_id:
            return None
        return tg_id, f"🎓 Новая заявка на занятие!\n\n{name} ({contact}) хочет записаться.\nОткрой кабинет → Заявки."
