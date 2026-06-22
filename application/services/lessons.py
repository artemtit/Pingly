from __future__ import annotations

from datetime import datetime, timedelta, timezone

from application.repositories import PinglyRepository
from domain import LessonStatus, NotificationType

# How far ahead recurring lessons are pre-generated.
HORIZON_DAYS = 56
MAX_GENERATED = 60

RECURRENCE_LABELS = {
    "once": "Разовое",
    "daily": "Каждый день",
    "weekly": "Каждую неделю",
    "multiple_weekly": "Несколько раз в неделю",
    "every_n_days": "Каждые N дней",
    "every_n_weeks": "Каждые N недель",
}


def _parse_time(lesson_time: str) -> tuple[int, int]:
    hour, minute = map(int, lesson_time[:5].split(":"))
    return hour, minute


_MONTHS_RU = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

# Moscow time — UTC+3, no DST. All user-facing time formatting goes through here.
_MSK = timezone(timedelta(hours=3))


def _to_msk(dt: datetime) -> datetime:
    return dt.astimezone(_MSK)


def _fmt_dt_msk(dt: datetime) -> str:
    """Format a UTC datetime as Moscow time for user-facing messages."""
    msk = _to_msk(dt)
    return f"{msk.day} {_MONTHS_RU[msk.month - 1]} в {msk:%H:%M}"


def _fmt_when_ru(starts_at: str) -> str:
    try:
        dt = datetime.fromisoformat(str(starts_at).replace("Z", "+00:00"))
        return _fmt_dt_msk(dt)
    except Exception:
        return str(starts_at)[:16].replace("T", " ")


# Statuses that never consume a package slot.
_PACKAGE_SKIP_STATUSES = {"cancelled", "reschedule_requested"}


def package_status(student: dict, lessons: list[dict]) -> dict | None:
    """Compute the abonement (lesson package) state for a student from their
    already-loaded lessons. Returns None if no package is set.

    A lesson consumes one slot when it actually happened — i.e. the student
    pressed «Буду» (confirmed) and it's in the past, OR the tutor marked it
    «проведено» (completed) — and it started on/after the current cycle start.
    Remaining is computed (never stored) so it can't drift or double-count.
    """
    size = student.get("package_size")
    if not size:
        return None
    started_at = _parse_package_dt(student.get("package_started_at"))
    now = datetime.now(timezone.utc)
    consumed = 0
    for l in lessons:
        status = l.get("status")
        if status in _PACKAGE_SKIP_STATUSES:
            continue
        started = _parse_package_dt(l.get("starts_at"))
        if started_at and (started is None or started < started_at):
            continue
        if status == LessonStatus.COMPLETED.value:
            consumed += 1
        elif status == LessonStatus.CONFIRMED.value and started is not None and started < now:
            consumed += 1
    return {
        "size": int(size),
        "started_at": student.get("package_started_at"),
        "consumed": consumed,
        "remaining": max(int(size) - consumed, 0),
    }


def _parse_package_dt(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class LessonService:
    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    # ---- creation -------------------------------------------------------
    async def create_recurring_lesson(self, tutor_tg_id: int, student_id: str, day_of_week: int, lesson_time: str, duration_minutes: int = 60) -> dict:
        tutor = await self.repo.get_user_by_tg_id(tutor_tg_id)
        if not tutor or tutor["role"] != "tutor":
            raise PermissionError("Only tutors can create lessons")
        return await self.create_schedule(tutor["id"], student_id, "weekly", lesson_time, weekdays=[day_of_week], duration_minutes=duration_minutes)

    async def create_recurring_lesson_for_user(self, tutor_user_id: str, student_id: str, day_of_week: int, lesson_time: str, duration_minutes: int = 60) -> dict:
        return await self.create_schedule(tutor_user_id, student_id, "weekly", lesson_time, weekdays=[day_of_week], duration_minutes=duration_minutes)

    async def create_one_time_lesson(self, tutor_user_id: str, student_id: str, starts_at: datetime, duration_minutes: int = 60, public_comment: str | None = None) -> dict:
        tutor = await self.repo.get_user_by_id(tutor_user_id)
        if not tutor or tutor["role"] != "tutor":
            raise PermissionError("Only tutors can create lessons")
        student = await self.repo.get_student_for_tutor(tutor_user_id, student_id)
        if not student:
            raise PermissionError("Student does not belong to tutor")
        lesson = await self.repo.create_lesson(tutor_user_id, student_id, starts_at, public_comment=public_comment)
        await self._schedule_lesson_notifications(lesson, starts_at, student.get("name"))
        return lesson

    async def create_schedule(
        self,
        tutor_user_id: str,
        student_id: str,
        recurrence: str,
        lesson_time: str,
        weekdays: list[int] | None = None,
        interval_n: int = 1,
        duration_minutes: int = 60,
        start_date: datetime | None = None,
        public_comment: str | None = None,
    ) -> dict:
        tutor = await self.repo.get_user_by_id(tutor_user_id)
        if not tutor or tutor["role"] != "tutor":
            raise PermissionError("Only tutors can create lessons")
        student = await self.repo.get_student_for_tutor(tutor_user_id, student_id)
        if not student:
            raise PermissionError("Student does not belong to tutor")

        weekdays = sorted(set(weekdays or []))
        anchor = start_date or datetime.now(timezone.utc)
        day_of_week = weekdays[0] if weekdays else anchor.weekday()
        rule = await self.repo.create_schedule_rule(
            tutor_user_id,
            student_id,
            day_of_week,
            lesson_time,
            duration_minutes,
            recurrence=recurrence,
            interval_n=max(interval_n, 1),
            weekdays=weekdays or [day_of_week],
            start_date=anchor.date().isoformat(),
        )
        await self._generate_lessons(tutor_user_id, student_id, rule, public_comment=public_comment)
        return rule

    def _occurrences(self, recurrence: str, weekdays: list[int], interval_n: int, lesson_time: str, start: datetime) -> list[datetime]:
        hour, minute = _parse_time(lesson_time)
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(days=HORIZON_DAYS)
        out: list[datetime] = []
        weekdays = weekdays or [start.weekday()]
        interval_n = max(interval_n, 1)

        def at(d: datetime) -> datetime:
            # hour/minute are Moscow time — subtract 3h to store as UTC
            return d.replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(hours=3)

        if recurrence == "daily":
            cursor = at(start)
            while cursor <= horizon and len(out) < MAX_GENERATED:
                if cursor >= now:
                    out.append(cursor)
                cursor += timedelta(days=1)
        elif recurrence == "every_n_days":
            cursor = at(start)
            while cursor <= horizon and len(out) < MAX_GENERATED:
                if cursor >= now:
                    out.append(cursor)
                cursor += timedelta(days=interval_n)
        elif recurrence == "every_n_weeks":
            wd = weekdays[0]
            cursor = at(start + timedelta(days=(wd - start.weekday()) % 7))
            while cursor <= horizon and len(out) < MAX_GENERATED:
                if cursor >= now:
                    out.append(cursor)
                cursor += timedelta(weeks=interval_n)
        else:  # weekly / multiple_weekly
            for week in range((HORIZON_DAYS // 7) + 1):
                for wd in weekdays:
                    occ = at(start + timedelta(days=(wd - start.weekday()) % 7, weeks=week))
                    if now <= occ <= horizon:
                        out.append(occ)
        return sorted(set(out))[:MAX_GENERATED]

    async def _generate_lessons(self, tutor_user_id: str, student_id: str, rule: dict, public_comment: str | None = None) -> list[dict]:
        weekdays = rule.get("weekdays") or [rule["day_of_week"]]
        if isinstance(weekdays, str):
            import json
            weekdays = json.loads(weekdays)
        occurrences = self._occurrences(
            rule.get("recurrence", "weekly"),
            [int(w) for w in weekdays],
            int(rule.get("interval_n", 1)),
            rule["lesson_time"],
            datetime.now(timezone.utc),
        )
        student = await self.repo.get_student_for_tutor(tutor_user_id, student_id)
        student_name = (student or {}).get("name")
        lessons = []
        for starts_at in occurrences:
            lesson = await self.repo.create_lesson(tutor_user_id, student_id, starts_at, schedule_rule_id=rule["id"], public_comment=public_comment)
            lessons.append(lesson)
            await self._schedule_lesson_notifications(lesson, starts_at, student_name)
        return lessons

    async def _schedule_lesson_notifications(self, lesson: dict, starts_at: datetime, student_name: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        student_user_id = lesson.get("student_user_id")
        if student_user_id:
            # Single reminder 2 hours before the lesson (matches the promise on
            # the landing). Skipped if the lesson is sooner than 2h (e.g. added
            # the same day), so it never fires instantly with wrong wording.
            send_at = starts_at - timedelta(hours=2)
            if send_at > now:
                await self.repo.create_notification(
                    student_user_id,
                    NotificationType.LESSON_HOUR_BEFORE.value,
                    "⏰ Занятие через 2 часа",
                    f"Занятие начнётся {_fmt_dt_msk(starts_at)}",
                    {"lesson_id": lesson["id"]},
                    send_at,
                )
        # Nudge the tutor 1h before (after the student got the 2h reminder) if
        # the lesson still isn't confirmed. The scheduler drops it if the lesson
        # was already confirmed/cancelled. Skipped if the lesson is sooner than 1h.
        tutor_user_id = lesson.get("tutor_user_id")
        if tutor_user_id:
            send_at = starts_at - timedelta(hours=1)
            if send_at > now:
                who = student_name or (lesson.get("student_profiles") or {}).get("name") or "ученик"
                await self.repo.create_notification(
                    tutor_user_id,
                    NotificationType.TUTOR_UNCONFIRMED.value,
                    "❓ Занятие пока не подтверждено",
                    f"До занятия ({_fmt_dt_msk(starts_at)}) меньше часа, а {who} ещё не нажал(а) «Буду». Стоит написать.",
                    {"lesson_id": lesson["id"]},
                    send_at,
                )

    # ---- reads ----------------------------------------------------------
    async def list_tutor_calendar(self, tutor_user_id: str) -> list[dict]:
        return await self.repo.list_lessons_for_tutor(tutor_user_id)

    async def list_student_calendar(self, student_user_id: str) -> list[dict]:
        return await self.repo.list_lessons_for_student_user(student_user_id)

    async def next_lesson_for_student(self, student_user_id: str) -> dict | None:
        return await self.repo.get_next_lesson_for_student_user(student_user_id)

    # ---- single lesson actions -----------------------------------------
    async def complete_lesson(self, tutor_user_id: str, lesson_id: str) -> dict | None:
        return await self.repo.update_lesson_status(tutor_user_id, lesson_id, LessonStatus.COMPLETED.value)

    async def cancel_lesson(self, tutor_user_id: str, lesson_id: str) -> dict | None:
        lesson = await self.repo.update_lesson_status(tutor_user_id, lesson_id, LessonStatus.CANCELLED.value)
        if lesson and lesson.get("student_user_id"):
            await self.repo.create_notification(
                lesson["student_user_id"],
                NotificationType.LESSON_RESCHEDULED.value,
                "❌ Занятие отменено",
                "Репетитор отменил занятие.",
                {"lesson_id": lesson_id},
            )
        return lesson

    async def set_lesson_comment(self, tutor_user_id: str, lesson_id: str, comment: str | None) -> dict | None:
        """Set/clear the lesson topic (public_comment) the student sees in the
        reminder and calendar. Optional — empty clears it."""
        existing = await self.repo.get_lesson_for_tutor(tutor_user_id, lesson_id)
        if not existing:
            raise PermissionError("Lesson does not belong to tutor")
        text = (comment or "").strip()
        return await self.repo.update_lesson_fields(lesson_id, {"public_comment": text or None})

    async def reschedule_lesson(self, tutor_user_id: str, lesson_id: str, new_starts_at: datetime) -> dict | None:
        existing = await self.repo.get_lesson_for_tutor(tutor_user_id, lesson_id)
        if not existing:
            return None
        patch = {
            "starts_at": new_starts_at.isoformat(),
            "status": LessonStatus.SCHEDULED.value,
            "rescheduled_from": existing.get("starts_at"),
        }
        lesson = await self.repo.update_lesson_fields(lesson_id, patch)
        if lesson and lesson.get("student_user_id"):
            await self.repo.create_notification(
                lesson["student_user_id"],
                NotificationType.LESSON_RESCHEDULED.value,
                "🔄 Занятие перенесено",
                f"Новое время: {_fmt_dt_msk(new_starts_at)}",
                {"lesson_id": lesson_id},
            )
            await self._schedule_lesson_notifications(lesson, new_starts_at, (existing.get("student_profiles") or {}).get("name"))
        return lesson

    # ---- series actions -------------------------------------------------
    async def cancel_series(self, tutor_user_id: str, rule_id: str) -> int:
        rule = await self.repo.get_schedule_rule(tutor_user_id, rule_id)
        if not rule:
            return 0
        await self.repo.update_schedule_rule(rule_id, {"is_active": False})
        now = datetime.now(timezone.utc)
        future = await self.repo.list_future_lessons_for_rule(rule_id, now)
        for lesson in future:
            await self.repo.update_lesson_fields(lesson["id"], {"status": LessonStatus.CANCELLED.value})
        if future and future[0].get("student_user_id"):
            await self.repo.create_notification(
                future[0]["student_user_id"],
                NotificationType.LESSON_RESCHEDULED.value,
                "❌ Серия занятий отменена",
                "Репетитор отменил все будущие занятия этой серии.",
                {"rule_id": rule_id},
            )
        return len(future)

    async def reschedule_series(self, tutor_user_id: str, rule_id: str, new_time: str) -> int:
        rule = await self.repo.get_schedule_rule(tutor_user_id, rule_id)
        if not rule:
            return 0
        hour, minute = _parse_time(new_time)
        await self.repo.update_schedule_rule(rule_id, {"lesson_time": f"{hour:02d}:{minute:02d}:00"})
        now = datetime.now(timezone.utc)
        future = await self.repo.list_future_lessons_for_rule(rule_id, now)
        count = 0
        student_user_id = None
        for lesson in future:
            old = datetime.fromisoformat(lesson["starts_at"].replace("Z", "+00:00"))
            new_dt = old.replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(hours=3)
            await self.repo.update_lesson_fields(lesson["id"], {"starts_at": new_dt.isoformat(), "rescheduled_from": lesson["starts_at"]})
            student_user_id = lesson.get("student_user_id") or student_user_id
            count += 1
        if student_user_id:
            await self.repo.create_notification(
                student_user_id,
                NotificationType.LESSON_RESCHEDULED.value,
                "🔄 Серия занятий перенесена",
                f"Новое время занятий: {hour:02d}:{minute:02d}",
                {"rule_id": rule_id},
            )
        return count

    async def student_confirm_lesson(self, student_user_id: str, lesson_id: str) -> dict | None:
        """Mark a scheduled lesson as confirmed by the student. Returns the lesson
        (with tutor_user_id, starts_at, student_profiles) so the caller can push
        the tutor, or None if it wasn't a confirmable lesson (already confirmed,
        cancelled, etc.) — None also prevents a duplicate "confirmed" push."""
        lessons = await self.repo.list_lessons_for_student_user(student_user_id)
        lesson = next((l for l in lessons if l["id"] == lesson_id), None)
        if not lesson or lesson.get("status") != "scheduled":
            return None
        await self.repo.update_lesson_fields(lesson_id, {"status": LessonStatus.CONFIRMED.value})
        return lesson

    async def confirm_push_target(self, lesson: dict) -> tuple[int, str] | None:
        """Given a just-confirmed lesson, return (tutor_tg_id, message) to notify
        the tutor, or None if the tutor has no Telegram linked."""
        tutor_id = lesson.get("tutor_user_id")
        if not tutor_id:
            return None
        tutor = await self.repo.get_user_by_id(tutor_id)
        tg_id = (tutor or {}).get("tg_id")
        if not tg_id:
            return None
        name = (lesson.get("student_profiles") or {}).get("name") or "Ученик"
        when = _fmt_when_ru(lesson.get("starts_at", ""))
        return tg_id, f"✅ {name} подтвердил(а) занятие {when}."

    async def student_request_reschedule(self, student_user_id: str, lesson_id: str) -> dict | None:
        """Student asks to move a lesson. Marks it and returns the lesson so the
        caller can push the tutor (who then reschedules manually)."""
        lessons = await self.repo.list_lessons_for_student_user(student_user_id)
        lesson = next((l for l in lessons if l["id"] == lesson_id), None)
        if not lesson or lesson.get("status") not in ("scheduled", "confirmed"):
            return None
        await self.repo.update_lesson_fields(lesson_id, {"status": LessonStatus.RESCHEDULE_REQUESTED.value})
        if lesson.get("tutor_user_id"):
            await self.repo.create_notification(
                lesson["tutor_user_id"],
                NotificationType.LESSON_RESCHEDULE_REQUEST.value,
                "🟠 Ученик просит перенести занятие",
                "Открой кабинет и предложи новое время.",
                {"lesson_id": lesson_id},
            )
        return lesson

    async def reschedule_request_push_target(self, lesson: dict) -> tuple[int, str] | None:
        tutor_id = lesson.get("tutor_user_id")
        if not tutor_id:
            return None
        tutor = await self.repo.get_user_by_id(tutor_id)
        tg_id = (tutor or {}).get("tg_id")
        if not tg_id:
            return None
        name = (lesson.get("student_profiles") or {}).get("name") or "Ученик"
        when = _fmt_when_ru(lesson.get("starts_at", ""))
        message = (
            f"🟠 {name} просит перенести занятие {when}.\n\n"
            "Напиши ученику и поставь новое время в кабинете."
        )
        return tg_id, message

    async def set_lesson_paid(self, tutor_user_id: str, lesson_id: str, paid: bool) -> dict | None:
        return await self.repo.set_lesson_payment(tutor_user_id, lesson_id, paid)

    async def lesson_is_unconfirmed(self, lesson_id: str) -> bool:
        """True if the lesson still exists and hasn't been confirmed/cancelled —
        used by the scheduler to decide whether to nudge the tutor."""
        lesson = await self.repo.get_lesson_by_id(lesson_id)
        if not lesson:
            return False
        return lesson.get("status") == LessonStatus.SCHEDULED.value

    async def finance_overview(self, tutor_user_id: str) -> dict:
        """Per-student billing summary built from completed lessons."""
        lessons = await self.repo.list_lessons_for_tutor(tutor_user_id, 1000)
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        by_student: dict[str, dict] = {}
        month_earned = 0
        total_unpaid = 0
        for l in lessons:
            if l.get("status") != LessonStatus.COMPLETED.value:
                continue
            sid = l.get("student_id") or "—"
            name = (l.get("student_profiles") or {}).get("name") or "Ученик"
            row = by_student.setdefault(sid, {
                "student_id": sid, "name": name,
                "lessons": 0, "paid_sum": 0, "unpaid_sum": 0, "unpaid_count": 0,
            })
            price = l.get("price") or 0
            row["lessons"] += 1
            if l.get("paid"):
                row["paid_sum"] += price
            else:
                row["unpaid_sum"] += price
                row["unpaid_count"] += 1
                total_unpaid += price
            started = datetime.fromisoformat(str(l["starts_at"]).replace("Z", "+00:00")) if l.get("starts_at") else None
            if started and started >= month_start:
                month_earned += price
        students = sorted(by_student.values(), key=lambda r: r["unpaid_sum"], reverse=True)
        return {
            "students": students,
            "month_earned": month_earned,
            "total_unpaid": total_unpaid,
        }

    async def list_student_history(self, student_user_id: str) -> dict:
        """Past lessons for a student + simple counters."""
        lessons = await self.repo.list_lessons_for_student_user(student_user_id, 1000)
        now = datetime.now(timezone.utc)
        past = []
        for l in lessons:
            started = datetime.fromisoformat(str(l["starts_at"]).replace("Z", "+00:00")) if l.get("starts_at") else None
            if started and started < now:
                past.append(l)
        past.sort(key=lambda l: l.get("starts_at") or "", reverse=True)
        completed = len([l for l in past if l.get("status") == LessonStatus.COMPLETED.value])
        cancelled = len([l for l in past if l.get("status") == LessonStatus.CANCELLED.value])
        return {"lessons": past, "completed": completed, "cancelled": cancelled, "total": len(past)}

    async def student_cancel_lesson(self, student_user_id: str, lesson_id: str) -> dict | None:
        """Cancel a scheduled/confirmed lesson on the student's behalf. Returns the lesson
        (with tutor_user_id, starts_at, student_profiles) so the caller can push
        the tutor, or None if it wasn't a cancellable lesson."""
        lessons = await self.repo.list_lessons_for_student_user(student_user_id)
        lesson = next((l for l in lessons if l["id"] == lesson_id), None)
        if not lesson or lesson.get("status") not in ("scheduled", "confirmed"):
            return None
        await self.repo.update_lesson_fields(lesson_id, {"status": LessonStatus.CANCELLED.value})
        return lesson

    async def delete_lesson(self, tutor_user_id: str, lesson_id: str) -> None:
        await self.repo.delete_lesson(tutor_user_id, lesson_id)

    async def cancel_push_target(self, lesson: dict) -> tuple[int, str] | None:
        """Given a just-cancelled lesson, return (tutor_tg_id, message) to notify
        the tutor, or None if the tutor has no Telegram linked."""
        tutor_id = lesson.get("tutor_user_id")
        if not tutor_id:
            return None
        tutor = await self.repo.get_user_by_id(tutor_id)
        tg_id = (tutor or {}).get("tg_id")
        if not tg_id:
            return None
        name = (lesson.get("student_profiles") or {}).get("name") or "Ученик"
        when = _fmt_when_ru(lesson.get("starts_at", ""))
        message = (
            f"🔔 {name} отменил(а) занятие {when}.\n\n"
            "Напиши ученику, чтобы договориться о переносе."
        )
        return tg_id, message

    async def change_lesson_status(self, tutor_user_id: str, lesson_id: str, status: LessonStatus, starts_at: datetime | None = None) -> dict | None:
        return await self.repo.update_lesson_status(tutor_user_id, lesson_id, status.value, starts_at)
