from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import db

REMINDER_DELTA = timedelta(hours=2)
CHECK_WINDOW = timedelta(minutes=5)

DAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


async def send_reminders(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    target = now + REMINDER_DELTA

    lessons = await db.get_all_active_lessons()
    for lesson in lessons:
        if lesson["day_of_week"] != target.weekday():
            continue

        lesson_time_str = lesson["lesson_time"][:5]
        lesson_hour, lesson_minute = map(int, lesson_time_str.split(":"))
        lesson_dt = target.replace(hour=lesson_hour, minute=lesson_minute, second=0, microsecond=0)

        if abs((lesson_dt - target).total_seconds()) > CHECK_WINDOW.total_seconds():
            continue

        student = lesson["students"]
        if not student.get("tg_id"):
            continue

        scheduled_for = lesson_dt.isoformat()
        if await db.reminder_already_sent(lesson["id"], scheduled_for):
            continue

        reminder = await db.create_reminder(lesson["id"], scheduled_for)
        tutor_name = student["tutors"]["name"]

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Буду", callback_data=f"confirm:{reminder['id']}"),
            InlineKeyboardButton(text="❌ Отменяю", callback_data=f"cancel:{reminder['id']}"),
        ]])

        await bot.send_message(
            student["tg_id"],
            f"Привет! Репетитор {tutor_name} напоминает — занятие сегодня в {lesson_time_str} 📚\n\n"
            "Подтверди, пожалуйста:",
            reply_markup=keyboard,
        )


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_reminders, "interval", minutes=5, args=[bot])
    return scheduler
