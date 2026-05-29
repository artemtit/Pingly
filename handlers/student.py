from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
import db

router = Router()


@router.message(CommandStart())
async def student_start(message: Message) -> None:
    username = message.from_user.username
    if username:
        await db.update_student_tg_id(username, message.from_user.id)
    await message.answer(
        "Привет! 👋\n\n"
        "Я буду напоминать тебе о занятиях с репетитором за 2 часа до урока.\n"
        "Ничего настраивать не нужно — просто жди напоминание!"
    )


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_lesson(callback: CallbackQuery) -> None:
    reminder_id = callback.data.split(":")[1]
    reminder = await db.get_reminder(reminder_id)
    if not reminder:
        await callback.answer("Напоминание не найдено.")
        return

    await db.update_reminder_status(reminder_id, "confirmed")
    await callback.message.edit_text("✅ Отлично, ждём тебя на занятии!")

    tutor_tg_id = reminder["lessons"]["students"]["tutors"]["tg_id"]
    student_name = reminder["lessons"]["students"]["name"]
    scheduled_for = reminder["scheduled_for"][:16].replace("T", " ")
    await callback.bot.send_message(
        tutor_tg_id,
        f"✅ {student_name} подтвердил занятие ({scheduled_for})"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_lesson(callback: CallbackQuery) -> None:
    reminder_id = callback.data.split(":")[1]
    reminder = await db.get_reminder(reminder_id)
    if not reminder:
        await callback.answer("Напоминание не найдено.")
        return

    await db.update_reminder_status(reminder_id, "cancelled")
    await callback.message.edit_text("Понял, занятие отменено. Увидимся в следующий раз!")

    tutor_tg_id = reminder["lessons"]["students"]["tutors"]["tg_id"]
    student_name = reminder["lessons"]["students"]["name"]
    scheduled_for = reminder["scheduled_for"][:16].replace("T", " ")
    await callback.bot.send_message(
        tutor_tg_id,
        f"❌ {student_name} отменил занятие ({scheduled_for})"
    )
    await callback.answer()
