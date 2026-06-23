from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config
from application.repositories import PinglyRepository

VALID_PLANS = ("pro", "max")
VALID_AUDIENCES = ("tutors", "students", "all")


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

        active_subs = sum(1 for t in tutors if (t.get("subscription_status") or "").lower() == "active")
        # Recent signups (latest tutors) and recent confirmed payments — small feeds.
        recent_tutors = sorted(tutors, key=lambda t: str(t.get("created_at") or ""), reverse=True)[:8]
        recent_payments = sorted(paid, key=lambda p: str(p.get("created_at") or ""), reverse=True)[:8]

        return {
            "tutors_total": len(tutors),
            "students_total": len(students),
            "lessons_total": len(lessons),
            "active_subscriptions": active_subs,
            "active_access": sum(1 for t in tutors if _is_active(t, now)),
            "new_tutors_week": sum(1 for t in tutors if (_parse_dt(t.get("created_at")) or now) >= week_ago),
            "revenue_total": sum(int(p.get("amount_rub") or 0) for p in paid),
            "payments_count": len(paid),
            # MRR ≈ active monthly subs × price; conversion = paid / all tutors.
            "mrr": active_subs * config.SUBSCRIPTION_PRICE_RUB,
            "conversion": round(active_subs / len(tutors) * 100) if tutors else 0,
            "recent_tutors": [
                {
                    "name": t.get("full_name") or "—",
                    "created_at": t.get("created_at"),
                    "active": _is_active(t, now),
                    "tg": t.get("tg_username"),
                }
                for t in recent_tutors
            ],
            "recent_payments": [
                {"amount_rub": int(p.get("amount_rub") or 0), "created_at": p.get("created_at")}
                for p in recent_payments
            ],
        }

    async def list_tutors(self) -> list[dict]:
        users = await self.repo.admin_list_users()
        links = await self.repo.admin_student_links()
        lessons = await self.repo.admin_lessons_min()
        payments = await self.repo.admin_payments()

        counts: dict[str, int] = {}
        for link in links:
            tid = link.get("tutor_user_id")
            if tid:
                counts[tid] = counts.get(tid, 0) + 1

        # Lessons total + held (completed/confirmed) per tutor — at-a-glance sense
        # of how actively each account is used.
        lesson_total: dict[str, int] = {}
        lesson_done: dict[str, int] = {}
        for lesson in lessons:
            tid = lesson.get("tutor_user_id")
            if not tid:
                continue
            lesson_total[tid] = lesson_total.get(tid, 0) + 1
            if (lesson.get("status") or "").lower() in ("completed", "confirmed"):
                lesson_done[tid] = lesson_done.get(tid, 0) + 1

        # Confirmed subscription revenue per tutor.
        revenue: dict[str, int] = {}
        for p in payments:
            if (p.get("status") or "").lower() != "confirmed":
                continue
            uid = p.get("user_id")
            if uid:
                revenue[uid] = revenue.get(uid, 0) + int(p.get("amount_rub") or 0)

        now = datetime.now(timezone.utc)
        tutors = []
        for u in users:
            if u.get("role") != "tutor":
                continue
            u = dict(u)
            uid = u["id"]
            u["student_count"] = counts.get(uid, 0)
            u["lesson_count"] = lesson_total.get(uid, 0)
            u["lessons_done"] = lesson_done.get(uid, 0)
            u["revenue"] = revenue.get(uid, 0)
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

    async def broadcast_targets(self, audience: str = "tutors") -> list[int]:
        """Telegram ids of the chosen audience who connected Telegram:
        'tutors' (default), 'students', or 'all'."""
        audience = audience if audience in VALID_AUDIENCES else "tutors"
        users = await self.repo.admin_list_users()
        return [
            int(u["tg_id"]) for u in users
            if u.get("tg_id") and (audience == "all" or u.get("role") == audience)
        ]

    async def broadcast_counts(self) -> dict[str, int]:
        """How many reachable (Telegram-connected) accounts per audience."""
        users = await self.repo.admin_list_users()
        with_tg = [u for u in users if u.get("tg_id")]
        tutors = sum(1 for u in with_tg if u.get("role") == "tutor")
        students = sum(1 for u in with_tg if u.get("role") == "student")
        return {"tutors": tutors, "students": students, "all": len(with_tg)}
