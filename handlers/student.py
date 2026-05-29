from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from application.factory import create_services
from handlers.keyboards import student_menu_keyboard

router = Router()
services = create_services()


@router.message(F.text == "📚 Следующее занятие")
async def btn_next_lesson(message: Message) -> None:
    await cmd_next_lesson(message)


@router.message(F.text == "📝 Мои задания")
async def btn_my_homework(message: Message) -> None:
    await cmd_my_homework(message)


@router.message(F.text == "📈 Мой прогресс")
async def btn_progress(message: Message) -> None:
    await cmd_progress(message)


@router.message(Command("next_lesson"))
async def cmd_next_lesson(message: Message) -> None:
    user = await services.accounts.get_by_tg_id(message.from_user.id)
    if not user or user["role"] != "student":
        await message.answer("Эта команда доступна ученику.")
        return
    lesson = await services.lessons.next_lesson_for_student(user["id"])
    if not lesson:
        await message.answer("Ближайших занятий пока нет.", reply_markup=student_menu_keyboard())
        return
    starts = lesson["starts_at"][:16].replace("T", " ")
    await message.answer(f"Следующее занятие: {starts} 📚\nСтатус: {lesson['status']}", reply_markup=student_menu_keyboard())


@router.message(Command("my_homework"))
async def cmd_my_homework(message: Message) -> None:
    user = await services.accounts.get_by_tg_id(message.from_user.id)
    if not user or user["role"] != "student":
        await message.answer("Эта команда доступна ученику.")
        return
    homework = await services.homework.list_for_student(user["id"])
    if not homework:
        await message.answer("Домашних заданий пока нет.", reply_markup=student_menu_keyboard())
        return
    lines = [f"• {h['title']} — {h['status']}" for h in homework[:10]]
    await message.answer("Мои задания:\n\n" + "\n".join(lines), reply_markup=student_menu_keyboard())


@router.message(Command("progress"))
async def cmd_progress(message: Message) -> None:
    user = await services.accounts.get_by_tg_id(message.from_user.id)
    if not user or user["role"] != "student":
        await message.answer("Эта команда доступна ученику.")
        return
    lessons = await services.lessons.list_student_calendar(user["id"])
    homework = await services.homework.list_for_student(user["id"])
    completed = len([l for l in lessons if l.get("status") == "completed"])
    reviewed = len([h for h in homework if h.get("status") == "reviewed"])
    percent = round(reviewed / len(homework) * 100) if homework else 0
    await message.answer(
        "Мой прогресс:\n\n"
        f"Проведено занятий: {completed}\n"
        f"Проверено заданий: {reviewed}\n"
        f"Выполнение ДЗ: {percent}%",
        reply_markup=student_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("lesson_confirm:"))
async def confirm_lesson(callback: CallbackQuery) -> None:
    await callback.message.edit_text("✅ Отлично, ждём тебя на занятии!")
    await callback.answer()


@router.callback_query(F.data.startswith("lesson_cancel:"))
async def cancel_lesson(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Понял, занятие отменено. Репетитор увидит ответ.")
    await callback.answer()
