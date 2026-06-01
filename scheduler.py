from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from application.factory import create_services

services = create_services()


async def send_due_notifications(bot: Bot) -> None:
    notifications = await services.notifications.due_notifications()
    for notification in notifications:
        user = notification.get("users") or {}
        tg_id = user.get("tg_id")
        if not tg_id:
            continue

        payload = notification.get("payload") or {}

        # "Tutor unconfirmed" nudge: only fire if the student still hasn't
        # confirmed/cancelled. Otherwise quietly drop it.
        if notification["type"] == "tutor_unconfirmed":
            lesson_id = payload.get("lesson_id")
            if not lesson_id or not await services.lessons.lesson_is_unconfirmed(lesson_id):
                await services.notifications.mark_sent(notification["id"])
                continue

        keyboard = None
        if payload.get("lesson_id") and notification["type"] in {"lesson_day_before", "lesson_hour_before"}:
            lesson_id = payload["lesson_id"]
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Буду", callback_data=f"lesson_confirm:{lesson_id}"),
                InlineKeyboardButton(text="❌ Отменяю", callback_data=f"lesson_cancel:{lesson_id}"),
            ]])

        await bot.send_message(
            tg_id,
            f"{notification['title']}\n\n{notification['body']}",
            reply_markup=keyboard,
        )
        await services.notifications.mark_sent(notification["id"])


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_due_notifications, "interval", minutes=1, args=[bot])
    return scheduler
