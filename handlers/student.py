from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from application.factory import create_services

router = Router()
services = create_services()

# Lightweight, in-memory "awaiting cancel reason" state. The bot is otherwise
# stateless (no FSM, per CLAUDE.md) — this is one bounded exception: after a
# student taps «Отменяю» we wait for a single optional free-text reason, forward
# it to the tutor, then forget. Lost on restart, which is fine for a 10-min window.
_awaiting_reason: dict[int, dict] = {}  # tg_user_id -> {tutor_tg_id, name, at}
_REASON_TTL = 600  # seconds to wait for the reason before giving up


@router.callback_query(F.data.startswith("lesson_confirm:"))
async def confirm_lesson(callback: CallbackQuery) -> None:
    lesson_id = callback.data.split(":")[1]
    user = await services.accounts.get_by_tg_id(callback.from_user.id)
    lesson = await services.lessons.student_confirm_lesson(user["id"], lesson_id) if user else None
    await callback.message.edit_text("✅ Отлично, ждём тебя на занятии!")
    await callback.answer("Записал: ты будешь 👍")
    if lesson:
        target = await services.lessons.confirm_push_target(lesson)
        if target:
            try:
                await callback.bot.send_message(target[0], target[1])
            except Exception:
                pass


@router.callback_query(F.data.startswith("lesson_cancel:"))
async def cancel_lesson(callback: CallbackQuery) -> None:
    lesson_id = callback.data.split(":")[1]
    user = await services.accounts.get_by_tg_id(callback.from_user.id)
    lesson = await services.lessons.student_cancel_lesson(user["id"], lesson_id) if user else None
    await callback.message.edit_text(
        "Понял, занятие отменено. Репетитор уже в курсе.\n\n"
        "Если хочешь, напиши одним сообщением причину — я передам её репетитору."
    )
    await callback.answer("Отмена записана")
    if lesson:
        target = await services.lessons.cancel_push_target(lesson)
        if target:
            try:
                await callback.bot.send_message(target[0], target[1])
            except Exception:
                pass
            # Wait for an optional free-text reason and forward it to the tutor.
            _awaiting_reason[callback.from_user.id] = {
                "tutor_tg_id": target[0],
                "name": (lesson.get("student_profiles") or {}).get("name") or "Ученик",
                "at": time.monotonic(),
            }


@router.message(F.text & ~F.text.startswith("/"))
async def capture_cancel_reason(message: Message) -> None:
    """Forward a just-cancelled lesson's reason to the tutor. Only fires for a
    student who tapped «Отменяю» in the last few minutes; otherwise stays silent
    so the bot keeps its service-only behaviour."""
    info = _awaiting_reason.pop(message.from_user.id, None)
    if not info or (time.monotonic() - info["at"] > _REASON_TTL):
        return
    reason = (message.text or "").strip()[:500]
    if not reason:
        return
    try:
        await message.bot.send_message(
            info["tutor_tg_id"], f"📝 {info['name']} о причине отмены: «{reason}»"
        )
    except Exception:
        pass
    await message.answer("Передал причину репетитору 🙏")
