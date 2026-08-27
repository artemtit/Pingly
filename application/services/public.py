from __future__ import annotations

import re
from typing import Any

from application.repositories import PinglyRepository
from domain.slug import SLUG_MAX_LEN, SLUG_MIN_LEN, normalize_slug, slug_error

# Публичный API модуля не меняется: normalize_slug раньше жил здесь, теперь
# переехал в domain/slug.py (нужен ещё и репозиторию при регистрации).
__all__ = ["PublicService", "normalize_slug"]

MAX_REVIEWS = 10
REVIEW_AUTHOR_MAX = 60
REVIEW_TEXT_MAX = 500
PRICE_NOTE_MAX = 120
PRICE_MIN = 1
PRICE_MAX = 99999
DURATION_MIN = 5
DURATION_MAX = 600
DEFAULT_DURATION = 60

# Сентинел «поле не пришло — не трогать его». Отличает «репетитор очистил цену»
# (пустая строка → NULL) от «форма это поле вообще не отправляла» (старый роут,
# частичное сохранение). Без него любое сохранение из формы, не знающей про новые
# поля, молча стирало бы цену, отзывы и telegram.
_KEEP: Any = object()

_DIGITS = re.compile(r"[0-9]+")
# \s ловит и неразрывный пробел — разделитель тысяч из Word/Excel.
_PRICE_JUNK = re.compile(r"[\s₽]")
_TG_USERNAME = re.compile(r"[A-Za-z0-9_]{5,32}")
_TG_URL_PREFIX = re.compile(r"^(https?://)?(www\.)?t(elegram)?\.me/", re.IGNORECASE)


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

    # ---------------- Цена ----------------
    @staticmethod
    def parse_price(raw: str | int | None) -> tuple[int | None, str | None]:
        """Цена за занятие. Возвращает (цена|None, ошибка|None).

        Пустое поле — это осознанная «цена не указана» (блок скрыт), а не ошибка.
        А вот мусор («дорого», «1200 руб», «-5») обязан отвалиться с ошибкой,
        а не сохраниться молча.
        """
        if raw is None:
            return None, None
        # Разделители тысяч (в т.ч. неразрывный пробел) и знак рубля — нормальный
        # ввод: «1 200 ₽» должно сохраниться как 1200, а не упасть с ошибкой.
        value = _PRICE_JUNK.sub("", str(raw))
        if not value:
            return None, None
        if not _DIGITS.fullmatch(value):
            return None, f"Цена — целое число от {PRICE_MIN} до {PRICE_MAX} ₽ (без пробелов и букв)"
        price = int(value)
        if not (PRICE_MIN <= price <= PRICE_MAX):
            return None, f"Цена — целое число от {PRICE_MIN} до {PRICE_MAX} ₽"
        return price, None

    @staticmethod
    def parse_duration(raw: str | int | None) -> tuple[int, str | None]:
        """Длительность, к которой относится цена. Пусто → 60 мин."""
        if raw is None:
            return DEFAULT_DURATION, None
        value = str(raw).strip()
        if not value:
            return DEFAULT_DURATION, None
        if not _DIGITS.fullmatch(value):
            return DEFAULT_DURATION, f"Длительность занятия — целое число минут от {DURATION_MIN} до {DURATION_MAX}"
        minutes = int(value)
        if not (DURATION_MIN <= minutes <= DURATION_MAX):
            return DEFAULT_DURATION, f"Длительность занятия — от {DURATION_MIN} до {DURATION_MAX} минут"
        return minutes, None

    # ---------------- Telegram ----------------
    @staticmethod
    def normalize_telegram(raw: str | None) -> tuple[str | None, str | None]:
        """@ivan_math / https://t.me/ivan_math / ivan_math → ivan_math."""
        value = (raw or "").strip()
        if not value:
            return None, None
        value = _TG_URL_PREFIX.sub("", value).lstrip("@").rstrip("/").strip()
        if not _TG_USERNAME.fullmatch(value):
            return None, "Telegram-логин — 5–32 символа: латиница, цифры и «_» (например @ivan_math)"
        return value, None

    # ---------------- Отзывы ----------------
    @staticmethod
    def parse_reviews(raw: object) -> list[dict]:
        """Отзывы из jsonb-колонки → [{author, text, position}], отсортированные.

        Санитизируем на чтении тоже: колонка jsonb, в неё теоретически может
        лечь что угодно (ручная правка в Supabase), а страница публичная —
        падать 500-й из-за кривой строки она не должна.
        """
        if not isinstance(raw, list):
            return []
        items: list[dict] = []
        for i, row in enumerate(raw):
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()[:REVIEW_TEXT_MAX]
            if not text:
                continue
            author = str(row.get("author") or "").strip()[:REVIEW_AUTHOR_MAX] or "Ученик"
            try:
                position = int(row.get("position", i))
            except (TypeError, ValueError):
                position = i
            items.append({"author": author, "text": text, "position": position})
        items.sort(key=lambda r: r["position"])
        return [{**r, "position": n} for n, r in enumerate(items[:MAX_REVIEWS])]

    @staticmethod
    def sanitize_reviews(items: list[dict] | None) -> list[dict]:
        """Отзывы из формы кабинета → то, что можно класть в jsonb.

        Порядок задаёт сама форма (кнопки «вверх/вниз» переставляют поля),
        поэтому position перенумеровывается по порядку пришедших строк.
        """
        return PublicService.parse_reviews([
            {"author": r.get("author"), "text": r.get("text"), "position": i}
            for i, r in enumerate(items or []) if isinstance(r, dict)
        ])

    async def update_profile(
        self,
        tutor_user_id: str,
        slug: str,
        bio: str,
        subjects: str,
        public_enabled: bool,
        badges: str = "",
        page_theme: str = "auto",
        price_per_hour: Any = _KEEP,
        price_duration_min: Any = _KEEP,
        price_note: Any = _KEEP,
        telegram_username: Any = _KEEP,
        reviews: Any = _KEEP,
    ) -> tuple[dict | None, str | None]:
        current = await self.repo.get_tutor_profile(tutor_user_id)

        # --- адрес страницы ---------------------------------------------------
        # Пустое поле = «не трогать текущий адрес». Стереть slug нельзя осознанно:
        # на него уже могут вести ссылки из соцсетей и Авито.
        slug = normalize_slug(slug)
        if slug:
            err = slug_error(slug)
            if err:
                return None, err
            existing = await self.repo.get_tutor_profile_by_slug(slug)
            if existing and existing.get("user_id") != tutor_user_id:
                return None, f"Адрес «{slug}» уже занят — выбери другой"
        elif public_enabled and not (current or {}).get("slug"):
            return None, f"Укажи адрес страницы ({SLUG_MIN_LEN}–{SLUG_MAX_LEN} символов) — по нему ученики её откроют"

        # update_tutor_profile drops only None values (keeps empty strings), so we
        # push bio/subjects as plain strings — an empty one must actually CLEAR the
        # field, not be silently ignored. slug stays opt-in (None never clobbers it).
        theme = page_theme if page_theme in ("auto", "light", "dark") else "auto"
        patch: dict[str, Any] = {
            **({"slug": slug} if slug else {}),
            "bio": (bio or "").strip(),
            "subjects": (subjects or "").strip(),
            "public_enabled": public_enabled,
            "badges": "\n".join(f"{b['icon']}|{b['text']}" for b in self.parse_badges(badges)),
            "page_theme": theme,
        }
        # Необязательные поля-визитки. Ключ попадает в патч, только если форма его
        # прислала; nullable разрешает записать туда NULL, т.е. «репетитор очистил».
        nullable: list[str] = []

        if price_per_hour is not _KEEP:
            price, err = self.parse_price(price_per_hour)
            if err:
                return None, err
            patch["price_per_hour"] = price
            nullable.append("price_per_hour")

        if price_duration_min is not _KEEP:
            duration, err = self.parse_duration(price_duration_min)
            if err:
                return None, err
            patch["price_duration_min"] = duration

        if price_note is not _KEEP:
            patch["price_note"] = (str(price_note or "").strip()[:PRICE_NOTE_MAX] or None)
            nullable.append("price_note")

        if telegram_username is not _KEEP:
            tg_username, err = self.normalize_telegram(telegram_username)
            if err:
                return None, err
            patch["telegram_username"] = tg_username
            nullable.append("telegram_username")

        if reviews is not _KEEP:
            patch["reviews"] = self.sanitize_reviews(reviews)

        profile = await self.repo.update_tutor_profile(tutor_user_id, patch, nullable=tuple(nullable))
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

    async def booking_push_target(self, tutor_user_id: str, name: str, contact: str) -> tuple[str, int, str] | None:
        """Return (channel, dest, message) to notify the tutor of a new booking —
        Telegram first, then VK — or None if the tutor has neither linked."""
        tutor = await self.repo.get_user_by_id(tutor_user_id)
        if tutor and tutor.get("tg_id"):
            channel, dest = "tg", int(tutor["tg_id"])
        elif tutor and tutor.get("vk_id"):
            channel, dest = "vk", int(tutor["vk_id"])
        else:
            return None
        return channel, dest, f"🎓 Новая заявка на занятие!\n\n{name} ({contact}) хочет записаться.\nОткрой кабинет → Заявки."
