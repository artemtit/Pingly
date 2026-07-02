from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from application.factory import create_services
from application.services.accounts import subscription_info
from application.services.lessons import package_status
from config import WEB_BASE_URL
from vk_bot import lesson_keyboard as vk_lesson_keyboard

logger = logging.getLogger("pingly.scheduler")

services = create_services()

# Days-before-expiry milestones at which we remind a tutor once.
_SUB_MILESTONES = (3, 1, 0)

# Lessons-remaining milestones at which we alert about an ending package once.
_PACKAGE_MILESTONES = (1, 0)


def _sub_link_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💳 Оформить подписку", url=f"{WEB_BASE_URL}/tutor/settings"),
    ]])


async def send_due_notifications(tg_bot: Bot, vk_bot=None) -> None:
    notifications = await services.notifications.due_notifications()
    for notification in notifications:
        user = notification.get("users") or {}
        vk_id = user.get("vk_id")
        tg_id = user.get("tg_id")
        if not tg_id and not vk_id:
            continue

        payload = notification.get("payload") or {}

        # "Tutor unconfirmed" nudge: only fire if the student still hasn't
        # confirmed/cancelled. Otherwise quietly drop it.
        if notification["type"] == "tutor_unconfirmed":
            lesson_id = payload.get("lesson_id")
            if not lesson_id or not await services.lessons.lesson_is_unconfirmed(lesson_id):
                await services.notifications.mark_sent(notification["id"])
                continue

        text = f"{notification['title']}\n\n{notification['body']}"
        is_lesson = bool(payload.get("lesson_id")) and notification["type"] in {"lesson_day_before", "lesson_hour_before"}

        # Append the lesson topic (if the tutor set one) at send time, so the
        # student sees the latest version even if it was added after scheduling.
        if is_lesson:
            try:
                lesson = await services.repo.get_lesson_by_id(payload["lesson_id"])
            except Exception:
                logger.exception("get_lesson_by_id failed for lesson_id=%s", payload.get("lesson_id"))
                lesson = None
            topic = (lesson or {}).get("public_comment")
            if topic:
                text += f"\n\n📝 Тема: {topic}"

        # A student can have both channels connected — deliver to each one they
        # have. The "Буду / Отменяю" buttons write to the same account, so it
        # doesn't matter which message the student answers from.
        delivered = False

        if vk_id and vk_bot is not None:
            keyboard = vk_lesson_keyboard(payload["lesson_id"]) if is_lesson else None
            try:
                await vk_bot.send_message(vk_id, text, keyboard=keyboard)
                delivered = True
            except Exception:
                logger.exception("vk send failed (vk_id=%s, notification_id=%s)", vk_id, notification["id"])

        if tg_id:
            keyboard = None
            if is_lesson:
                lesson_id = payload["lesson_id"]
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Буду", callback_data=f"lesson_confirm:{lesson_id}"),
                    InlineKeyboardButton(text="❌ Отменяю", callback_data=f"lesson_cancel:{lesson_id}"),
                ]])
            elif notification["type"] == "subscription_expiring":
                keyboard = _sub_link_keyboard()
            try:
                await tg_bot.send_message(tg_id, text, reply_markup=keyboard)
                delivered = True
            except Exception:
                logger.exception("tg send failed (tg_id=%s, notification_id=%s)", tg_id, notification["id"])

        if delivered:
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


async def enqueue_package_reminders() -> None:
    """Alert the tutor (and student) once when a lesson package runs low (1 left)
    or out (0 left). Remaining is computed; dedup per package cycle + milestone via
    the notifications table, so renewing a package re-enables future alerts."""
    rows = await services.repo.list_active_package_students()
    if not rows:
        return
    # Fetch each tutor's lessons once, then split per student.
    by_tutor: dict[str, list[dict]] = {}
    for row in rows:
        by_tutor.setdefault(row["tutor_user_id"], []).append(row)
    for tutor_user_id, students in by_tutor.items():
        lessons = await services.repo.list_lessons_for_tutor(tutor_user_id, 1000)
        for student in students:
            student_lessons = [l for l in lessons if l.get("student_id") == student["student_id"]]
            status = package_status(
                {"package_size": student["package_size"], "package_started_at": student["package_started_at"]},
                student_lessons,
            )
            if not status or status["remaining"] not in _PACKAGE_MILESTONES:
                continue
            await _alert_package(tutor_user_id, student, status)


async def _already_notified(user_id: str, student_id: str, started_at, milestone: int) -> bool:
    recent = await services.repo.list_notifications_for_user(user_id, 50)
    for n in recent:
        if n.get("type") != "package_ending":
            continue
        p = n.get("payload") or {}
        if (p.get("student_id") == student_id and p.get("started_at") == started_at
                and p.get("milestone") == milestone):
            return True
    return False


async def _alert_package(tutor_user_id: str, student: dict, status: dict) -> None:
    remaining = status["remaining"]
    started_at = status["started_at"]
    student_id = student["student_id"]
    name = student["name"]
    size = status["size"]

    # Tutor alert (both milestones).
    if not await _already_notified(tutor_user_id, student_id, started_at, remaining):
        if remaining == 1:
            title = "📦 Абонемент заканчивается"
            body = f"У {name} остался 1 урок по абонементу. Пора предложить продление."
        else:
            title = "📦 Абонемент закончился"
            body = f"У {name} закончился абонемент ({size} занятий пройдены). Время продлевать."
        await services.repo.create_notification(
            tutor_user_id, "package_ending", title, body,
            {"student_id": student_id, "started_at": started_at, "milestone": remaining},
        )

    # Student nudge — one soft message at the "1 left" milestone only.
    student_user_id = student.get("student_user_id")
    if remaining == 1 and student_user_id:
        if not await _already_notified(student_user_id, student_id, started_at, remaining):
            await services.repo.create_notification(
                student_user_id, "package_ending", "📦 Абонемент заканчивается",
                "Это одно из последних занятий по абонементу — напиши репетитору, чтобы продлить 💙",
                {"student_id": student_id, "started_at": started_at, "milestone": remaining},
            )


def create_scheduler(bot: Bot, vk_bot=None) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    # max_instances=1 + coalesce: if a delivery run is still going when the next
    # minute fires, don't start a second overlapping run (which would re-read the
    # same still-unsent rows and double-send). One process + this guard = no dupes;
    # a distributed atomic claim would only be needed across multiple processes.
    scheduler.add_job(
        send_due_notifications, "interval", minutes=1, args=[bot, vk_bot],
        max_instances=1, coalesce=True, misfire_grace_time=120,
    )
    scheduler.add_job(
        enqueue_subscription_reminders, "interval", hours=12,
        next_run_time=datetime.now() + timedelta(seconds=30),
    )
    scheduler.add_job(
        enqueue_package_reminders, "interval", hours=12,
        next_run_time=datetime.now() + timedelta(seconds=45),
    )
    return scheduler
