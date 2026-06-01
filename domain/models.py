from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Any


class UserRole(str, Enum):
    STUDENT = "student"
    TUTOR = "tutor"


class LessonStatus(str, Enum):
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    RESCHEDULE_REQUESTED = "reschedule_requested"
    COMPLETED = "completed"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"


class HomeworkStatus(str, Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    REVIEWED = "reviewed"


class NotificationType(str, Enum):
    LESSON_DAY_BEFORE = "lesson_day_before"
    LESSON_HOUR_BEFORE = "lesson_hour_before"
    HOMEWORK_CREATED = "homework_created"
    HOMEWORK_SUBMITTED = "homework_submitted"
    HOMEWORK_REVIEWED = "homework_reviewed"
    LESSON_RESCHEDULED = "lesson_rescheduled"
    LESSON_RESCHEDULE_REQUEST = "lesson_reschedule_request"
    TUTOR_UNCONFIRMED = "tutor_unconfirmed"
    BOOKING_REQUEST = "booking_request"
    SUBSCRIPTION_EXPIRING = "subscription_expiring"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    READ = "read"


@dataclass(frozen=True)
class User:
    id: str
    role: UserRole
    full_name: str
    tg_id: int | None = None
    tg_username: str | None = None


@dataclass(frozen=True)
class Student:
    id: str
    name: str
    tutor_id: str
    user_id: str | None = None
    subject_name: str | None = None
    level: str | None = None
    status: str = "active"


@dataclass(frozen=True)
class Tutor:
    id: str
    user_id: str
    display_name: str


@dataclass(frozen=True)
class Subject:
    id: str
    tutor_id: str
    name: str


@dataclass(frozen=True)
class ScheduleRule:
    id: str
    tutor_id: str
    student_id: str
    subject_id: str | None
    day_of_week: int
    lesson_time: time
    duration_minutes: int
    is_active: bool


@dataclass(frozen=True)
class Lesson:
    id: str
    tutor_id: str
    student_id: str
    starts_at: datetime
    status: LessonStatus
    subject_id: str | None = None
    public_comment: str | None = None
    private_tutor_note: str | None = None


@dataclass(frozen=True)
class Homework:
    id: str
    tutor_id: str
    student_id: str
    title: str
    status: HomeworkStatus
    due_at: datetime | None = None
    description: str | None = None
    tutor_comment: str | None = None


@dataclass(frozen=True)
class Notification:
    id: str
    user_id: str
    type: NotificationType
    title: str
    body: str
    payload: dict[str, Any]
