from __future__ import annotations

import re

from application.repositories import PinglyRepository

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

    async def list_public_slugs(self) -> list[str]:
        """Enabled public-profile slugs — for the sitemap."""
        return await self.repo.list_public_slugs()

    @staticmethod
    def parse_badges(raw: str | None) -> list[dict]:
        """Badges stored one per line as "icon|text". Returns [{icon, text}], max 4,
        text capped at 40 chars. Legacy plain-text lines default to the check icon."""
        out: list[dict] = []
        for line in (raw or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                icon, text = line.split("|", 1)
                icon, text = icon.strip() or "check", text.strip()[:40]
            else:
                icon, text = "check", line[:40]
            if text:
                out.append({"icon": icon, "text": text})
            if len(out) >= 4:
                break
        return out

    async def update_profile(self, tutor_user_id: str, slug: str, bio: str, subjects: str, public_enabled: bool, badges: str = "", page_theme: str = "auto") -> tuple[dict | None, str | None]:
        slug = normalize_slug(slug)
        if public_enabled and len(slug) < 3:
            return None, "Адрес страницы — минимум 3 символа (латиница, цифры, дефис)"
        if slug:
            existing = await self.repo.get_tutor_profile_by_slug(slug)
            if existing and existing.get("user_id") != tutor_user_id:
                return None, "Этот адрес уже занят — выбери другой"
        # update_tutor_profile drops only None values (keeps empty strings), so we
        # push bio/subjects as plain strings — an empty one must actually CLEAR the
        # field, not be silently ignored. slug stays opt-in (None never clobbers it).
        theme = page_theme if page_theme in ("auto", "light", "dark") else "auto"
        profile = await self.repo.update_tutor_profile(tutor_user_id, {
            **({"slug": slug} if slug else {}),
            "bio": (bio or "").strip(),
            "subjects": (subjects or "").strip(),
            "public_enabled": public_enabled,
            "badges": "\n".join(f"{b['icon']}|{b['text']}" for b in self.parse_badges(badges)),
            "page_theme": theme,
        })
        return profile, None

    async def create_booking(self, slug: str, name: str, contact: str, preferred_time: str, comment: str) -> dict | None:
        profile = await self.get_public_profile(slug)
        if not profile:
            return None
        # Cap every field before insert — this endpoint is unauthenticated, so we
        # don't let a request bloat the DB or a Telegram push with arbitrary length.
        name = (name or "").strip()[:100]
        contact = (contact or "").strip()[:100]
        if not name or not contact:
            return None
        preferred_time = (preferred_time or "").strip()[:100] or None
        comment = (comment or "").strip()[:1000] or None
        tutor_user_id = profile["user_id"]
        request = await self.repo.create_booking_request(
            tutor_user_id, name, contact, preferred_time, comment,
        )
        # The tutor is pushed immediately by the route via _send_telegram, so we
        # don't also enqueue a notification row here (would double-send).
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
