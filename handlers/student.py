from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from application.factory import create_services

router = Router()
services = create_services()


@router.callback_query(F.data.startswith("lesson_confirm:"))
async def confirm_lesson(callback: CallbackQuery) -> None:
    await callback.message.edit_text("✅ Отлично, ждём тебя на занятии!")
    await callback.answer("Записал: ты будешь 👍")


@router.callback_query(F.data.startswith("lesson_cancel:"))
async def cancel_lesson(callback: CallbackQuery) -> None:
    lesson_id = callback.data.split(":")[1]
    user = await services.accounts.get_by_tg_id(callback.from_user.id)
    if user:
        await services.lessons.student_cancel_lesson(user["id"], lesson_id)
    await callback.message.edit_text("Понял, занятие отменено. Репетитор увидит это в кабинете.")
    await callback.answer("Отмена записана")
