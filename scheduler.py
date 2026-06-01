from __future__ import annotations

from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from application.factory import create_services
from application.services.accounts import subscription_info
from config import WEB_BASE_URL

services = create_services()

# Days-before-expiry milestones at which we remind a tutor once.
_SUB_MILESTONES = (3, 1, 0)


def _sub_link_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💳 Оформить подписку", url=f"{WEB_BASE_URL}/tutor/settings"),
    ]])


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
        elif notification["type"] == "subscription_expiring":
            keyboard = _sub_link_keyboard()

        await bot.send_message(
            tg_id,
            f"{notification['title']}\n\n{notification['body']}",
            reply_markup=keyboard,
        )
        await services.notifications.mark_sent(notification["id"])


async def enqueue_subscription_reminders() -> None:
    """Once per day-ish, queue a Telegram reminder for tutors whose trial ends
    in 3 / 1 / 0 days. Dedup per milestone via the notifications table."""
    tutors = await services.repo.list_tutors_with_trial()
    for tutor in tutors:
        info = subscription_info(tutor)
        days = info.get("days_left")
        if days is None or days not in _SUB_MILESTONES:
            continue
        recent = await services.repo.list_notifications_for_user(tutor["id"], 50)
        already = any(
            n.get("type") == "subscription_expiring" and (n.get("payload") or {}).get("milestone") == days
            for n in recent
        )
        if already:
            continue
        paid = info.get("status") == "active"
        period = "Подписка" if paid else "Пробный период"
        if days > 0:
            word = "день" if days == 1 else "дня"
            title = f"⏳ {period} заканчивается"
            body = (
                f"Осталось {days} {word}. "
                + ("Продли подписку Pingly Pro" if paid else "Оформи подписку Pingly Pro")
                + ", чтобы не потерять напоминания и кабинет."
            )
        else:
            title = f"⛔ {period} закончился" if not paid else "⛔ Подписка закончилась"
            body = "Продли подписку Pingly Pro, чтобы продолжить пользоваться сервисом 💙"
        await services.repo.create_notification(
            tutor["id"], "subscription_expiring", title, body, {"milestone": days},
        )


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_due_notifications, "interval", minutes=1, args=[bot])
    scheduler.add_job(
        enqueue_subscription_reminders, "interval", hours=12,
        next_run_time=datetime.now() + timedelta(seconds=30),
    )
    return scheduler
