from __future__ import annotations

from datetime import datetime, timedelta, timezone

from application.repositories import PinglyRepository

VALID_PLANS = ("pro", "max")


def _parse_dt(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _is_active(user: dict, now: datetime) -> bool:
    """Paid-active or still within the trial/access window."""
    if (user.get("subscription_status") or "").lower() == "active":
        return True
    ends = _parse_dt(user.get("trial_ends_at"))
    return bool(ends and ends > now)


class AdminService:
    """Read/manage every account. Guarded at the route layer by users.is_admin."""

    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def overview(self) -> dict:
        users = await self.repo.admin_list_users()
        lessons = await self.repo.admin_lessons_min()
        payments = await self.repo.admin_payments()
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        tutors = [u for u in users if u.get("role") == "tutor"]
        students = [u for u in users if u.get("role") == "student"]
        paid = [p for p in payments if (p.get("status") or "").lower() == "confirmed"]

        return {
            "tutors_total": len(tutors),
            "students_total": len(students),
            "lessons_total": len(lessons),
            "active_subscriptions": sum(1 for t in tutors if (t.get("subscription_status") or "").lower() == "active"),
            "active_access": sum(1 for t in tutors if _is_active(t, now)),
            "new_tutors_week": sum(1 for t in tutors if (_parse_dt(t.get("created_at")) or now) >= week_ago),
            "revenue_total": sum(int(p.get("amount_rub") or 0) for p in paid),
            "payments_count": len(paid),
        }

    async def list_tutors(self) -> list[dict]:
        users = await self.repo.admin_list_users()
        links = await self.repo.admin_student_links()
        counts: dict[str, int] = {}
        for link in links:
            tid = link.get("tutor_user_id")
            if tid:
                counts[tid] = counts.get(tid, 0) + 1
        now = datetime.now(timezone.utc)
        tutors = []
        for u in users:
            if u.get("role") != "tutor":
                continue
            u = dict(u)
            u["student_count"] = counts.get(u["id"], 0)
            u["access_active"] = _is_active(u, now)
            tutors.append(u)
        tutors.sort(key=lambda t: str(t.get("created_at") or ""), reverse=True)
        return tutors

    async def get_tutor(self, user_id: str) -> dict | None:
        user = await self.repo.get_user_by_id(user_id)
        return user if user and user.get("role") == "tutor" else None

    async def grant_subscription(self, user_id: str, plan: str, days: int = 30) -> None:
        """Manually give/extend a paid subscription on the chosen tier."""
        plan = plan if plan in VALID_PLANS else "max"
        await self.repo.activate_subscription(user_id, days, plan)

    async def set_plan(self, user_id: str, plan: str) -> None:
        if plan in VALID_PLANS:
            await self.repo.admin_set_plan(user_id, plan)

    async def extend_trial(self, user_id: str, days: int) -> None:
        await self.repo.extend_trial(user_id, days)

    async def broadcast_targets(self) -> list[int]:
        """Telegram ids of all tutors who connected Telegram."""
        tutors = await self.repo.admin_list_tutors()
        return [int(t["tg_id"]) for t in tutors if t.get("tg_id")]
