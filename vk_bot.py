"""VK (VKontakte) community bot — the second delivery channel alongside Telegram.

Dependency-light on purpose: instead of pulling vkbottle (which pins its own
aiohttp/pydantic and can clash with aiogram), this talks to the VK Bots Long Poll
API directly over aiohttp (already a dependency via aiogram).

Does exactly what the Telegram bot does for students:
  1. onboarding via an invite link  vk.me/club<id>?ref=inv_<token>
  2. delivery of lesson reminders (sending is driven by scheduler.py)
  3. "Буду / Отменяю" callback buttons under reminders

Tutors manage everything in the web cabinet but can link their VK as a
notification channel (vk.me/club<id>?ref=lnk_<token>) to receive booking/
cancel/reschedule pushes here instead of Telegram. Full VK ID OAuth login is
still Фаза 2.
"""
from __future__ import annotations

import asyncio
import json
import random

import aiohttp

import config
from application.factory import create_services

API_URL = "https://api.vk.com/method/"
API_VERSION = "5.199"

services = create_services()

STUDENT_MENU_LABEL = "📅 Моё занятие"

WELCOME_STUDENT = (
    "Привет! 👋\n\n"
    "Перед каждым занятием я пришлю напоминание — нажми «✅ Буду» или «❌ Отменяю».\n\n"
    f"А кнопкой «{STUDENT_MENU_LABEL}» внизу можно посмотреть, когда ближайшее занятие. "
    "Больше ничего делать не нужно 🙂"
)
INVALID_LINK = "Ссылка недействительна. Попроси репетитора прислать новую."


def student_menu_keyboard() -> dict:
    """Persistent bottom keyboard — VK mirror of the Telegram «Моё занятие» button.
    A minimal, read-only way for a student to check their next lesson on demand."""
    return {
        "one_time": False,
        "buttons": [[
            {"action": {"type": "text", "label": STUDENT_MENU_LABEL,
                        "payload": json.dumps({"action": "next_lesson"})}},
        ]],
    }


def lesson_keyboard(lesson_id: str) -> dict:
    """Inline VK keyboard with the same actions as the Telegram reminder."""
    return {
        "inline": True,
        "buttons": [
            [
                {"action": {"type": "callback", "label": "✅ Буду",
                            "payload": json.dumps({"action": "lesson_confirm", "lesson_id": lesson_id})},
                 "color": "positive"},
                {"action": {"type": "callback", "label": "❌ Отменяю",
                            "payload": json.dumps({"action": "lesson_cancel", "lesson_id": lesson_id})},
                 "color": "negative"},
            ],
            [
                {"action": {"type": "callback", "label": "🔄 Прошу перенести",
                            "payload": json.dumps({"action": "lesson_reschedule", "lesson_id": lesson_id})},
                 "color": "secondary"},
            ],
        ],
    }


def _invite_token(raw: str | None) -> str | None:
    """`inv_<token>` → `<token>`; anything else → None."""
    raw = (raw or "").strip()
    return raw[4:] if raw.startswith("inv_") else None


def _link_token(raw: str | None) -> str | None:
    """`lnk_<token>` → `<token>` (tutor VK-link deep link); anything else → None."""
    raw = (raw or "").strip()
    return raw[4:] if raw.startswith("lnk_") else None


def _payload_obj(payload) -> dict:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return {}
    return {}


class VkBot:
    def __init__(self, token: str, tg_bot=None) -> None:
        self.token = token
        self.tg_bot = tg_bot  # used to notify TG tutors when a VK student cancels
        self._session: aiohttp.ClientSession | None = None

    async def _s(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def api(self, method: str, **params):
        params = {k: v for k, v in params.items() if v is not None}
        params["access_token"] = self.token
        params["v"] = API_VERSION
        session = await self._s()
        async with session.post(API_URL + method, data=params) as resp:
            data = await resp.json()
        if "error" in data:
            raise RuntimeError(f"VK {method}: {data['error'].get('error_msg')}")
        return data.get("response")

    async def resolve_group_id(self) -> int:
        """Fill config.VK_GROUP_ID from the token (like BOT_USERNAME for Telegram)."""
        if config.VK_GROUP_ID:
            return config.VK_GROUP_ID
        resp = await self.api("groups.getById")
        groups = resp.get("groups") if isinstance(resp, dict) else resp
        if groups:
            config.VK_GROUP_ID = int(groups[0]["id"])
        return config.VK_GROUP_ID

    async def send_message(self, peer_id: int, text: str, keyboard: dict | None = None) -> None:
        await self.api(
            "messages.send",
            peer_id=peer_id,
            message=text,
            random_id=random.randint(1, 2_000_000_000),
            keyboard=json.dumps(keyboard) if keyboard else None,
        )

    async def _user_name(self, user_id: int) -> str:
        try:
            resp = await self.api("users.get", user_ids=user_id)
            if resp:
                u = resp[0]
                return f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
        except Exception:
            pass
        return ""

    # ---------------- event handlers ----------------
    async def _link_student(self, user_id: int, token: str) -> None:
        name = await self._user_name(user_id)
        student = await services.students.link_student_from_invite_vk(token, int(user_id), name)
        await self.send_message(
            user_id,
            WELCOME_STUDENT if student else INVALID_LINK,
            keyboard=student_menu_keyboard() if student else None,
        )

    async def _link_tutor(self, user_id: int, token: str) -> None:
        """Attach this VK user to the tutor account named by a `lnk_` link token."""
        name = await self._user_name(user_id)
        ok, err = await services.web_auth.link_tutor_vk_by_token(token, int(user_id), name)
        await self.send_message(
            user_id,
            (
                "Готово! ✅ Теперь заявки, отмены и переносы будут приходить сюда, "
                "во ВКонтакте. Управление — в кабинете на сайте."
            ) if ok else (err or INVALID_LINK),
        )

    async def _notify_tutor(self, target) -> None:
        """Route a (channel, dest, text) push: VK straight from this bot, Telegram
        via the shared TG bot instance (tutors may be on either channel)."""
        if not target:
            return
        channel, dest, text = target
        try:
            if channel == "vk":
                await self.send_message(dest, text)
            elif self.tg_bot:
                await self.tg_bot.send_message(dest, text)
        except Exception:
            pass

    async def _send_next_lesson(self, user_id: int) -> None:
        """«Моё занятие» — render the student's next-lesson card, or a nudge to link."""
        user = await services.repo.get_user_by_vk_id(int(user_id))
        if not user:
            await self.send_message(
                user_id,
                "Пока я тебя не знаю 🤔 Попроси репетитора прислать ссылку-приглашение.",
            )
            return
        card = await services.lessons.next_lesson_card(user["id"])
        await self.send_message(user_id, card, keyboard=student_menu_keyboard())

    async def _on_message_new(self, obj: dict) -> None:
        msg = obj.get("message") or obj
        user_id = msg.get("from_id") or msg.get("user_id")
        if not user_id:
            return
        # A token can arrive via the community-link ref, the start payload, or text.
        payload = _payload_obj(msg.get("payload"))
        link_tok = (
            _link_token(msg.get("ref"))
            or _link_token(payload.get("ref"))
            or _link_token(msg.get("text"))
        )
        if link_tok:  # tutor connecting their VK to the web cabinet
            await self._link_tutor(user_id, link_tok)
            return
        token = (
            _invite_token(msg.get("ref"))
            or _invite_token(payload.get("ref"))
            or _invite_token(msg.get("text"))
        )
        if token:  # student onboarding via an invite link
            await self._link_student(user_id, token)
            return
        # «Моё занятие» button (its payload) or the plain button text.
        if payload.get("action") == "next_lesson" or (msg.get("text") or "").strip() == STUDENT_MENU_LABEL:
            await self._send_next_lesson(user_id)

    async def _on_message_allow(self, obj: dict) -> None:
        user_id = obj.get("user_id")
        if not user_id:
            return
        key = obj.get("key")
        link_tok = _link_token(key)
        if link_tok:
            await self._link_tutor(user_id, link_tok)
            return
        token = _invite_token(key)
        if token:
            await self._link_student(user_id, token)

    async def _event_answer(self, event_id, user_id, peer_id, text: str) -> None:
        try:
            await self.api(
                "messages.sendMessageEventAnswer",
                event_id=event_id, user_id=user_id, peer_id=peer_id,
                event_data=json.dumps({"type": "show_snackbar", "text": text}),
            )
        except Exception:
            pass

    async def _on_message_event(self, obj: dict) -> None:
        user_id = obj.get("user_id")
        peer_id = obj.get("peer_id")
        event_id = obj.get("event_id")
        payload = _payload_obj(obj.get("payload"))
        action = payload.get("action")
        lesson_id = payload.get("lesson_id")

        if action == "lesson_confirm":
            user = await services.repo.get_user_by_vk_id(int(user_id)) if user_id else None
            lesson = (
                await services.lessons.student_confirm_lesson(user["id"], lesson_id)
                if user and lesson_id else None
            )
            await self._event_answer(event_id, user_id, peer_id, "Записал: ты будешь 👍")
            await self.send_message(peer_id, "✅ Отлично, ждём тебя на занятии!")
            # Push the tutor "X подтвердил" (Telegram or VK, whichever they linked).
            if lesson:
                await self._notify_tutor(await services.lessons.confirm_push_target(lesson))
            return

        if action == "lesson_cancel":
            user = await services.repo.get_user_by_vk_id(int(user_id)) if user_id else None
            lesson = (
                await services.lessons.student_cancel_lesson(user["id"], lesson_id)
                if user and lesson_id else None
            )
            await self._event_answer(event_id, user_id, peer_id, "Отмена записана")
            await self.send_message(
                peer_id,
                "Понял, занятие отменено. Репетитор уже в курсе — он напишет о переносе.",
            )
            # Notify the tutor (Telegram or VK, whichever they linked).
            if lesson:
                await self._notify_tutor(await services.lessons.cancel_push_target(lesson))
            return

        if action == "lesson_reschedule":
            user = await services.repo.get_user_by_vk_id(int(user_id)) if user_id else None
            lesson = (
                await services.lessons.student_request_reschedule(user["id"], lesson_id)
                if user and lesson_id else None
            )
            await self._event_answer(event_id, user_id, peer_id, "Запрос на перенос отправлен")
            await self.send_message(
                peer_id,
                "Хорошо! Репетитор уже в курсе и предложит новое время.",
            )
            # Notify the tutor (Telegram or VK, whichever they linked).
            if lesson:
                await self._notify_tutor(await services.lessons.reschedule_request_push_target(lesson))

    async def _dispatch(self, update: dict) -> None:
        utype = update.get("type")
        obj = update.get("object") or {}
        try:
            if utype == "message_new":
                await self._on_message_new(obj)
            elif utype == "message_allow":
                await self._on_message_allow(obj)
            elif utype == "message_event":
                await self._on_message_event(obj)
        except Exception as exc:  # never let one bad update kill the loop
            print(f"[vk] update error ({utype}): {exc}")

    async def run(self) -> None:
        await self.resolve_group_id()
        if not config.VK_GROUP_ID:
            print("[vk] no group id resolved — VK bot not started")
            return
        print(f"[vk] bot started for group {config.VK_GROUP_ID}")
        server = await self.api("groups.getLongPollServer", group_id=config.VK_GROUP_ID)
        srv, key, ts = server["server"], server["key"], server["ts"]
        session = await self._s()
        while True:
            try:
                async with session.get(
                    srv, params={"act": "a_check", "key": key, "ts": ts, "wait": 25},
                ) as resp:
                    data = await resp.json()
            except Exception:
                await asyncio.sleep(3)
                continue
            if "failed" in data:
                failed = data["failed"]
                if failed == 1:
                    ts = data.get("ts", ts)
                else:  # 2/3 — key/ts expired, re-request the server
                    server = await self.api("groups.getLongPollServer", group_id=config.VK_GROUP_ID)
                    srv, key, ts = server["server"], server["key"], server["ts"]
                continue
            ts = data.get("ts", ts)
            for update in data.get("updates", []):
                await self._dispatch(update)
