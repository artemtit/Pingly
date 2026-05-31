from __future__ import annotations

from application.services import (
    AccountService,
    AnalyticsService,
    HomeworkService,
    LessonService,
    NotificationService,
    StudentService,
    WebAuthService,
)
from config import BOT_TOKEN, WEB_BASE_URL
from infrastructure.supabase_repository import SupabasePinglyRepository


class Services:
    def __init__(self) -> None:
        self.repo = SupabasePinglyRepository()
        self.accounts = AccountService(self.repo)
        self.students = StudentService(self.repo)
        self.lessons = LessonService(self.repo)
        self.homework = HomeworkService(self.repo)
        self.notifications = NotificationService(self.repo)
        self.analytics = AnalyticsService(self.repo)
        self.web_auth = WebAuthService(self.repo, WEB_BASE_URL, BOT_TOKEN)


def create_services() -> Services:
    return Services()
