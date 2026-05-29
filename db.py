from supabase import AsyncClient, acreate_client
from config import SUPABASE_URL, SUPABASE_KEY

_client: AsyncClient | None = None


async def init_db() -> None:
    global _client
    _client = await acreate_client(SUPABASE_URL, SUPABASE_KEY)


def _db() -> AsyncClient:
    assert _client is not None, "DB not initialized"
    return _client


# --- Tutors ---

async def get_tutor(tg_id: int) -> dict | None:
    result = await _db().table("tutors").select("*").eq("tg_id", tg_id).execute()
    return result.data[0] if result.data else None


async def create_tutor(tg_id: int, name: str) -> dict:
    result = await _db().table("tutors").insert({"tg_id": tg_id, "name": name}).execute()
    return result.data[0]


# --- Students ---

async def get_student_by_username(tg_username: str) -> dict | None:
    result = await _db().table("students").select("*").eq("tg_username", tg_username).execute()
    return result.data[0] if result.data else None


async def get_student_by_tg_id(tg_id: int) -> dict | None:
    result = await _db().table("students").select("*").eq("tg_id", tg_id).execute()
    return result.data[0] if result.data else None


async def get_students(tutor_id: int) -> list[dict]:
    result = await _db().table("students").select("*").eq("tutor_id", tutor_id).execute()
    return result.data


async def get_student(student_id: str) -> dict | None:
    result = await _db().table("students").select("*").eq("id", student_id).execute()
    return result.data[0] if result.data else None


async def create_student(tutor_id: int, name: str, tg_username: str) -> dict:
    result = await _db().table("students").insert({
        "tutor_id": tutor_id,
        "name": name,
        "tg_username": tg_username,
    }).execute()
    return result.data[0]


async def update_student_tg_id(tg_username: str, tg_id: int) -> None:
    await _db().table("students").update({"tg_id": tg_id}).eq("tg_username", tg_username).execute()


# --- Lessons ---

async def get_lessons(student_id: str) -> list[dict]:
    result = await _db().table("lessons").select("*").eq("student_id", student_id).eq("is_active", True).execute()
    return result.data


async def get_all_active_lessons() -> list[dict]:
    result = await (
        _db().table("lessons")
        .select("*, students(name, tg_id, tg_username, tutor_id, tutors(name, tg_id))")
        .eq("is_active", True)
        .execute()
    )
    return result.data


async def create_lesson(student_id: str, day_of_week: int, lesson_time: str) -> dict:
    result = await _db().table("lessons").insert({
        "student_id": student_id,
        "day_of_week": day_of_week,
        "lesson_time": lesson_time,
        "is_active": True,
    }).execute()
    return result.data[0]


# --- Reminders ---

async def reminder_already_sent(lesson_id: str, scheduled_for: str) -> bool:
    result = await (
        _db().table("reminders")
        .select("id")
        .eq("lesson_id", lesson_id)
        .eq("scheduled_for", scheduled_for)
        .execute()
    )
    return len(result.data) > 0


async def create_reminder(lesson_id: str, scheduled_for: str) -> dict:
    result = await _db().table("reminders").insert({
        "lesson_id": lesson_id,
        "scheduled_for": scheduled_for,
        "status": "sent",
    }).execute()
    return result.data[0]


async def update_reminder_status(reminder_id: str, status: str) -> None:
    await _db().table("reminders").update({"status": status}).eq("id", reminder_id).execute()


async def get_reminder(reminder_id: str) -> dict | None:
    result = await (
        _db().table("reminders")
        .select("*, lessons(student_id, students(tutor_id, name, tutors(tg_id)))")
        .eq("id", reminder_id)
        .execute()
    )
    return result.data[0] if result.data else None
