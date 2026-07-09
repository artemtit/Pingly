from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from application.factory import create_services
from application.services.accounts import subscription_info
from application.services.lessons import package_status
from application.services.timezones import DEFAULT_TZ_OFFSET, tz_from_offset
from config import WEB_BASE_URL
from vk_bot import lesson_keyboard as vk_lesson_keyboard

logger = logging.getLogger("pingly.scheduler")

services = create_services()

# Days-before-expiry milestones at which we remind a tutor once.
_SUB_MILESTONES = (3, 1, 0)

# Lessons-remaining milestones at which we alert about an ending package once.
_PACKAGE_MILESTONES = (1, 0)

# How late a lesson reminder may be delivered before its fixed "через 2 часа"
# wording is considered untrustworthy (e.g. after a server downtime).
_REMINDER_STALE_AFTER = timedelta(minutes=15)

# Local hour at which the morning digest goes out (in each tutor's own timezone).
_DIGEST_LOCAL_HOUR = 9


def _plural_lessons(n: int) -> str:
    """Russian plural for 'занятие': 1 занятие, 2–4 занятия, 5+ занятий."""
    if 11 <= n % 100 <= 14:
        return "занятий"
    d = n % 10
    if d == 1:
        return "занятие"
    if 2 <= d <= 4:
        return "занятия"
    return "занятий"


def _parse_dt(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


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

        # "Tutor unconfirmed" nudge and the student's 30-min second ping both
        # only fire if the student still hasn't confirmed/cancelled. Otherwise
        # quietly drop them (a confirmed lesson needs no more nagging).
        if notification["type"] in ("tutor_unconfirmed", "lesson_second_ping"):
            lesson_id = payload.get("lesson_id")
            if not lesson_id or not await services.lessons.lesson_is_unconfirmed(lesson_id):
                await services.notifications.mark_sent(notification["id"])
                continue

        is_lesson = bool(payload.get("lesson_id")) and notification["type"] in {"lesson_day_before", "lesson_hour_before", "lesson_second_ping"}

        title = notification["title"]
        lesson = None
        if is_lesson:
            try:
                lesson = await services.repo.get_lesson_by_id(payload["lesson_id"])
            except Exception:
                logger.exception("get_lesson_by_id failed for lesson_id=%s", payload.get("lesson_id"))
                lesson = None
            # After a downtime a reminder can come due long after it was scheduled.
            # If the lesson has already started, "занятие через 2 часа" is pure noise
            # — drop it. If it's merely late (lesson still ahead), neutralize the
            # fixed "через 2 часа" title so it can never be wrong; the body keeps the
            # exact start time either way.
            now = datetime.now(timezone.utc)
            starts_at = _parse_dt((lesson or {}).get("starts_at"))
            if starts_at is not None and now >= starts_at:
                await services.notifications.mark_sent(notification["id"])
                continue
            scheduled_at = _parse_dt(notification.get("scheduled_for"))
            if scheduled_at is not None and now - scheduled_at > _REMINDER_STALE_AFTER:
                title = "⏰ Скоро занятие"

        text = f"{title}\n\n{notification['body']}"

        # Append the lesson topic (if the tutor set one) at send time, so the
        # student sees the latest version even if it was added after scheduling.
        if is_lesson:
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
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Буду", callback_data=f"lesson_confirm:{lesson_id}"),
                        InlineKeyboardButton(text="❌ Отменяю", callback_data=f"lesson_cancel:{lesson_id}"),
                    ],
                    [InlineKeyboardButton(text="🔄 Прошу перенести", callback_data=f"lesson_reschedule:{lesson_id}")],
                ])
            elif notification["type"] == "subscription_expiring":
                keyboard = _sub_link_keyboard()
            try:
                await tg_bot.send_message(tg_id, text, reply_markup=keyboard)
                delivered = True
                # Delivery works again — clear a previously raised "blocked" flag
                # so the tutor's "не доходят" badge disappears.
                if user.get("tg_blocked_at"):
                    await services.repo.clear_tg_blocked(notification["user_id"])
            except TelegramForbiddenError:
                # The user blocked the bot / deactivated their account. Silent
                # today — stamp it so the tutor sees it on the student's card.
                logger.info("tg blocked by user (tg_id=%s, notification_id=%s)", tg_id, notification["id"])
                if not user.get("tg_blocked_at"):
                    await services.repo.set_tg_blocked(notification["user_id"])
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
        # Dedup per (billing cycle, milestone): keyed on the current access
        # deadline so a RENEWED subscription (new trial_ends_at) gets a fresh set
        # of reminders instead of being suppressed by last cycle's notifications.
        cycle = tutor.get("trial_ends_at")
        recent = await services.repo.list_notifications_for_user(tutor["id"], 50)
        already = any(
            n.get("type") == "subscription_expiring"
            and (n.get("payload") or {}).get("milestone") == days
            and (n.get("payload") or {}).get("cycle") == cycle
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
            tutor["id"], "subscription_expiring", title, body, {"milestone": days, "cycle": cycle},
        )


async def enqueue_morning_digests() -> None:
    """Send each tutor a summary of the day's lessons ("Сегодня N занятий: …") at
    09:00 in THEIR timezone. Runs hourly and fires per tutor only when it's their
    9 AM; dedup per (tutor, date) via the notifications table (restart-safe)."""
    tutors = await services.repo.list_tutor_users()
    now = datetime.now(timezone.utc)
    for tutor in tutors:
        tz = tz_from_offset(tutor.get("tz_offset_minutes") or DEFAULT_TZ_OFFSET)
        local = now.astimezone(tz)
        if local.hour != _DIGEST_LOCAL_HOUR:
            continue
        day = local.date()
        date_key = day.isoformat()
        recent = await services.repo.list_notifications_for_user(tutor["id"], 30)
        if any(
            n.get("type") == "daily_digest" and (n.get("payload") or {}).get("date") == date_key
            for n in recent
        ):
            continue
        # The tutor's local day expressed as a UTC window.
        day_start = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)
        day_end = day_start + timedelta(days=1)
        lessons = await services.repo.list_lessons_for_tutor(tutor["id"], 1000)
        today = []
        for lesson in lessons:
            if lesson.get("status") in ("cancelled", "reschedule_requested"):
                continue
            starts = _parse_dt(lesson.get("starts_at"))
            if starts and day_start <= starts < day_end:
                today.append((starts, lesson))
        if not today:
            continue
        today.sort(key=lambda t: t[0])
        lines = [
            f"• {starts.astimezone(tz):%H:%M} — {(l.get('student_profiles') or {}).get('name') or 'Ученик'}"
            for starts, l in today
        ]
        count = len(today)
        body = f"Сегодня у тебя {count} {_plural_lessons(count)}:\n" + "\n".join(lines)
        await services.repo.create_notification(
            tutor["id"], "daily_digest", "☀️ План на день", body, {"date": date_key},
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
    # Morning digest runs hourly (top of the hour); the job itself fires per tutor
    # only when it's 09:00 in that tutor's timezone, so everyone gets it in the
    # morning regardless of where they are.
    scheduler.add_job(enqueue_morning_digests, "cron", minute=0)
    return scheduler
