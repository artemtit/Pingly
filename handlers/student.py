from __future__ import annotations

import random

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from application.factory import create_services
from handlers.keyboards import student_menu_keyboard

router = Router()
services = create_services()

PRAISE = ["🎉 Отлично!", "🔥 Супер!", "⭐ Молодец!", "🚀 Так держать!", "💪 Красавчик!"]


def _xp_bar(percent: int) -> str:
    filled = max(0, min(10, round(percent / 10)))
    return "▰" * filled + "▱" * (10 - filled)


def homework_keyboard(homework_id: str, status: str) -> InlineKeyboardMarkup | None:
    if status == "reviewed":
        return None
    rows = []
    if status == "new":
        rows.append([InlineKeyboardButton(text="🚧 Взять в работу", callback_data=f"hw_progress:{homework_id}")])
    if status in {"new", "in_progress", "submitted"}:
        rows.append([InlineKeyboardButton(text="✅ Сдать задание", callback_data=f"hw_submit:{homework_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


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
        await message.answer("Эта команда доступна ученику 🎓\nРоль можно поменять в ⚙️ Настройках.")
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
        await message.answer("Эта команда доступна ученику 🎓\nРоль можно поменять в ⚙️ Настройках.")
        return
    homework = await services.homework.list_for_student(user["id"])
    if not homework:
        await message.answer("Домашних заданий пока нет.", reply_markup=student_menu_keyboard())
        return
    await message.answer("📝 Мои задания\n\nНиже каждое задание отдельной карточкой. Когда закончишь — нажми «Сдать задание».")
    for h in homework[:10]:
        due = f"\nДедлайн: {h['due_at'][:16].replace('T', ' ')}" if h.get("due_at") else ""
        text = (
            f"📌 {h['title']}\n"
            f"Статус: {h['status']}{due}\n\n"
            f"{h.get('description') or 'Описание не добавлено.'}"
        )
        await message.answer(text, reply_markup=homework_keyboard(h["id"], h["status"]))
    await message.answer("Главное меню ниже 👇", reply_markup=student_menu_keyboard())


@router.message(Command("progress"))
async def cmd_progress(message: Message) -> None:
    user = await services.accounts.get_by_tg_id(message.from_user.id)
    if not user or user["role"] != "student":
        await message.answer("Эта команда доступна ученику 🎓\nРоль можно поменять в ⚙️ Настройках.")
        return
    lessons = await services.lessons.list_student_calendar(user["id"])
    homework = await services.homework.list_for_student(user["id"])
    completed = len([l for l in lessons if l.get("status") == "completed"])
    reviewed = len([h for h in homework if h.get("status") == "reviewed"])
    game = services.gamification.compute(lessons, homework)

    ach = [a for a in game["achievements"] if a["unlocked"]]
    ach_text = " ".join(a["emoji"] for a in ach) if ach else "пока нет — всё впереди!"

    await message.answer(
        "🚀 Твой прогресс\n\n"
        f"⭐ Уровень {game['level']} · {game['rank']}\n"
        f"{_xp_bar(game['level_progress_percent'])} {game['level_progress_percent']}%\n"
        f"💎 {game['xp']} XP · до следующего уровня {game['xp_to_next']} XP\n"
        f"🔥 Серия активности: {game['streak']} дн.\n\n"
        f"🔵 Занятий пройдено: {completed}\n"
        f"📝 ДЗ выполнено: {reviewed}\n\n"
        f"🏆 Достижения ({game['unlocked_count']}/{game['total_achievements']}): {ach_text}",
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


@router.callback_query(F.data.startswith("hw_progress:"))
async def homework_in_progress(callback: CallbackQuery) -> None:
    user = await services.accounts.get_by_tg_id(callback.from_user.id)
    if not user or user["role"] != "student":
        await callback.answer("Это действие доступно ученику.", show_alert=True)
        return
    homework_id = callback.data.split(":")[1]
    homework = await services.homework.mark_in_progress(user["id"], homework_id)
    if not homework:
        await callback.answer("Задание не найдено.", show_alert=True)
        return
    await callback.message.edit_text(
        f"🚧 Задание в работе\n\n📌 {homework['title']}\n\nКогда закончишь, открой «Мои задания» и нажми «Сдать задание»."
    )
    await callback.answer("Статус обновлён")


@router.callback_query(F.data.startswith("hw_submit:"))
async def homework_submit(callback: CallbackQuery) -> None:
    user = await services.accounts.get_by_tg_id(callback.from_user.id)
    if not user or user["role"] != "student":
        await callback.answer("Это действие доступно ученику.", show_alert=True)
        return
    homework_id = callback.data.split(":")[1]
    homework = await services.homework.mark_submitted(user["id"], homework_id)
    if not homework:
        await callback.answer("Задание не найдено.", show_alert=True)
        return
    await callback.message.edit_text(
        f"{random.choice(PRAISE)}\n\n"
        f"✅ Задание сдано\n📌 {homework['title']}\n\n"
        "Я отправил репетитору уведомление. Когда он проверит ДЗ, ты получишь сообщение. "
        "Загляни в 📈 Мой прогресс — возможно, ты приблизился к новому уровню! 🚀"
    )
    await callback.answer("Сдано 🎉")
