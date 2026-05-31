from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer

import config as _config
from application.factory import create_services
from config import WEB_SECRET
from web.calendar_view import STATUS_LABELS, build_calendar, parse_anchor

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["status_labels"] = STATUS_LABELS
templates.env.globals["role_label"] = lambda r: "Репетитор" if r == "tutor" else "Ученик"

_DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

def _ru_weekday(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return _DAYS_RU[dt.weekday()]
    except Exception:
        return ""

templates.env.filters["ru_weekday"] = _ru_weekday
services = create_services()
signer = URLSafeSerializer(WEB_SECRET, salt="pingly-web-session")


def create_app() -> FastAPI:
    app = FastAPI(title="Pingly")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    register_routes(app)
    return app


async def current_user(request: Request) -> dict:
    raw = request.cookies.get("pingly_session")
    if not raw:
        raise HTTPException(status_code=401)
    try:
        user_id = signer.loads(raw)
    except BadSignature as exc:
        raise HTTPException(status_code=401) from exc
    user = await services.accounts.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401)
    return user


def _login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def _require(user: dict, role: str) -> None:
    if user["role"] != role:
        raise HTTPException(status_code=403)


def _parse_local(raw: str) -> datetime | None:
    """Parse an <input type=datetime-local> value (seconds optional) as UTC."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if len(raw) == 16:  # YYYY-MM-DDTHH:MM
        raw += ":00"
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _ctx(request: Request, user: dict, active: str, **extra) -> dict:
    base = {"request": request, "user": user, "active": active}
    base.update(extra)
    return base


def _cabinet_url(user: dict) -> str:
    return "/tutor" if user["role"] == "tutor" else "/student"


def _set_session(response: Response, user: dict) -> None:
    response.set_cookie(
        "pingly_session", signer.dumps(user["id"]),
        httponly=True, samesite="lax", secure=True, max_age=60 * 60 * 24 * 30,
    )


def register_routes(app: FastAPI) -> None:  # noqa: C901 - route table
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Response:
        try:
            user = await current_user(request)
        except HTTPException:
            return templates.TemplateResponse("landing.html", {"request": request, "bot_username": _config.BOT_USERNAME})
        return RedirectResponse(_cabinet_url(user), status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    async def login(request: Request, error: str | None = None) -> Response:
        return templates.TemplateResponse("login.html", {
            "request": request, "bot_username": _config.BOT_USERNAME, "error": error,
        })

    @app.post("/login")
    async def login_submit(email: str = Form(...), password: str = Form(...)) -> Response:
        user = await services.web_auth.login_email(email, password)
        if not user:
            return RedirectResponse("/login?error=bad_credentials", status_code=303)
        response = RedirectResponse(_cabinet_url(user), status_code=303)
        _set_session(response, user)
        return response

    @app.get("/register", response_class=HTMLResponse)
    async def register(request: Request, error: str | None = None) -> Response:
        return templates.TemplateResponse("register.html", {
            "request": request, "bot_username": _config.BOT_USERNAME, "error": error,
        })

    @app.post("/register")
    async def register_submit(
        full_name: str = Form(...), email: str = Form(...), password: str = Form(...),
    ) -> Response:
        user, err = await services.web_auth.register_tutor_email(full_name, email, password)
        if err or not user:
            from urllib.parse import quote
            return RedirectResponse(f"/register?error={quote(err or 'Не удалось зарегистрироваться')}", status_code=303)
        response = RedirectResponse(_cabinet_url(user), status_code=303)
        _set_session(response, user)
        return response

    @app.get("/auth/telegram")
    async def auth_telegram(token: str) -> Response:
        user = await services.web_auth.consume_login_token(token)
        if not user:
            return RedirectResponse("/login?error=expired", status_code=303)
        response = RedirectResponse(_cabinet_url(user), status_code=303)
        _set_session(response, user)
        return response

    @app.get("/auth/telegram/callback")
    async def auth_telegram_widget(request: Request) -> Response:
        data = dict(request.query_params)
        user = await services.web_auth.login_telegram_widget(data)
        if not user:
            return RedirectResponse("/login?error=tg_failed", status_code=303)
        response = RedirectResponse(_cabinet_url(user), status_code=303)
        _set_session(response, user)
        return response

    @app.get("/logout")
    async def logout() -> Response:
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie("pingly_session")
        return response

    @app.get("/design-tokens.css")
    async def design_tokens() -> Response:
        return FileResponse(BASE_DIR.parent / "design-tokens.css", media_type="text/css")

    # ---------------- TUTOR ----------------
    @app.get("/tutor", response_class=HTMLResponse)
    async def tutor_dashboard(request: Request, user: dict = Depends(current_user)) -> Response:
        if user["role"] != "tutor":
            return RedirectResponse("/student", status_code=303)
        students = await services.students.list_students_by_user(user["id"])
        lessons = await services.lessons.list_tutor_calendar(user["id"])
        homework = await services.homework.list_for_tutor(user["id"])
        analytics = await services.analytics.tutor_dashboard(user["id"])
        now = datetime.now(timezone.utc).isoformat()
        upcoming = [l for l in lessons if l.get("status") == "scheduled" and (l.get("starts_at") or "") >= now][:6]
        pending_hw = [h for h in homework if h.get("status") == "submitted"]
        return templates.TemplateResponse("tutor.html", _ctx(
            request, user, "overview",
            students=students, analytics=analytics,
            upcoming=upcoming, pending_hw=pending_hw,
        ))

    @app.get("/tutor/students", response_class=HTMLResponse)
    async def tutor_students(request: Request, q: str | None = None, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        students = await services.students.list_students_by_user(user["id"], q)
        return templates.TemplateResponse("students.html", _ctx(request, user, "students", students=students, q=q or ""))

    @app.post("/tutor/students/create")
    async def create_student(
        name: str = Form(...),
        tg_username: str = Form(""),
        subject_summary: str = Form(""),
        user: dict = Depends(current_user),
    ) -> Response:
        _require(user, "tutor")
        if not name.strip():
            return RedirectResponse("/tutor/students", status_code=303)
        student = await services.students.create_student_for_user(
            user["id"], name, tg_username, subject_summary,
        )
        return RedirectResponse(f"/tutor/students/{student['id']}?created=1", status_code=303)

    @app.get("/tutor/students/{student_id}", response_class=HTMLResponse)
    async def tutor_student_card(
        request: Request, student_id: str, created: str | None = None, user: dict = Depends(current_user),
    ) -> Response:
        _require(user, "tutor")
        try:
            card = await services.students.student_card(user["id"], student_id)
        except PermissionError as exc:
            raise HTTPException(status_code=404) from exc
        return templates.TemplateResponse("student_card.html", _ctx(
            request, user, "students", **card, bot_username=_config.BOT_USERNAME, created=created,
        ))

    @app.post("/tutor/students/{student_id}/profile")
    async def update_student_profile(
        student_id: str,
        name: str = Form(...),
        subject_summary: str = Form(""),
        grade: str = Form(""),
        goal: str = Form(""),
        started_at: str = Form(""),
        user: dict = Depends(current_user),
    ) -> Response:
        _require(user, "tutor")
        await services.students.update_profile(user["id"], student_id, {
            "name": name.strip(),
            "subject_summary": subject_summary.strip() or None,
            "grade": grade.strip() or None,
            "goal": goal.strip() or None,
            "started_at": started_at.strip() or None,
        })
        return RedirectResponse(f"/tutor/students/{student_id}", status_code=303)

    @app.post("/tutor/students/{student_id}/delete")
    async def delete_student(student_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.students.delete_student(user["id"], student_id)
        return RedirectResponse("/tutor/students", status_code=303)

    @app.post("/tutor/students/{student_id}/note")
    async def update_student_note(student_id: str, note: str = Form(""), user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.students.set_note(user["id"], student_id, note.strip() or None)
        return RedirectResponse(f"/tutor/students/{student_id}", status_code=303)

    @app.get("/tutor/calendar", response_class=HTMLResponse)
    async def tutor_calendar(request: Request, view: str = "month", date: str | None = None, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        lessons = await services.lessons.list_tutor_calendar(user["id"])
        cal = build_calendar(lessons, view if view in {"day", "week", "month"} else "month", parse_anchor(date))
        return templates.TemplateResponse("calendar.html", _ctx(request, user, "calendar", cal=cal, base="/tutor/calendar"))

    @app.get("/tutor/schedule", response_class=HTMLResponse)
    async def tutor_schedule(request: Request, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        students = await services.students.list_students_by_user(user["id"])
        lessons = await services.lessons.list_tutor_calendar(user["id"])
        now = datetime.now(timezone.utc).isoformat()
        upcoming = [l for l in lessons if (l.get("starts_at") or "") >= now][:30]
        return templates.TemplateResponse("schedule.html", _ctx(request, user, "schedule", students=students, upcoming=upcoming))

    @app.post("/tutor/schedule")
    async def create_schedule(
        student_id: str = Form(...),
        recurrence: str = Form("weekly"),
        lesson_time: str = Form("15:00"),
        lesson_date: str = Form(""),
        interval_n: int = Form(1),
        weekdays: list[int] = Form(default=[]),
        user: dict = Depends(current_user),
    ) -> Response:
        _require(user, "tutor")
        time_norm = lesson_time.strip()[:5] or "15:00"
        if recurrence == "once":
            day = lesson_date.strip() or datetime.now(timezone.utc).date().isoformat()
            starts_at = datetime.fromisoformat(f"{day}T{time_norm}:00").replace(tzinfo=timezone.utc)
            await services.lessons.create_one_time_lesson(user["id"], student_id, starts_at)
        else:
            wd = weekdays or None
            await services.lessons.create_schedule(
                user["id"], student_id, recurrence, f"{time_norm}:00",
                weekdays=wd, interval_n=interval_n,
            )
        return RedirectResponse("/tutor/calendar?view=month", status_code=303)

    @app.get("/tutor/homework", response_class=HTMLResponse)
    async def tutor_homework(request: Request, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        students = await services.students.list_students_by_user(user["id"])
        homework = await services.homework.list_for_tutor(user["id"])
        return templates.TemplateResponse("homework_tutor.html", _ctx(request, user, "homework", students=students, homework=homework))

    @app.post("/tutor/homework")
    async def create_homework(
        student_id: str = Form(...),
        title: str = Form(...),
        description: str = Form(""),
        due_at: str = Form(""),
        user: dict = Depends(current_user),
    ) -> Response:
        _require(user, "tutor")
        due = _parse_local(due_at)
        await services.homework.create_homework(user["id"], student_id, title, description or None, due)
        return RedirectResponse("/tutor/homework", status_code=303)

    @app.post("/tutor/homework/{homework_id}/review")
    async def review_homework(homework_id: str, comment: str = Form(""), user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.homework.review(user["id"], homework_id, comment.strip() or None)
        return RedirectResponse("/tutor/homework", status_code=303)

    @app.post("/tutor/lessons/{lesson_id}/complete")
    async def complete_lesson(lesson_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.lessons.complete_lesson(user["id"], lesson_id)
        return RedirectResponse("/tutor/calendar", status_code=303)

    @app.post("/tutor/lessons/{lesson_id}/cancel")
    async def cancel_lesson(lesson_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.lessons.cancel_lesson(user["id"], lesson_id)
        return RedirectResponse("/tutor/calendar", status_code=303)

    @app.post("/tutor/lessons/{lesson_id}/reschedule")
    async def reschedule_lesson(lesson_id: str, new_at: str = Form(...), user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        new_dt = _parse_local(new_at)
        if new_dt:
            await services.lessons.reschedule_lesson(user["id"], lesson_id, new_dt)
        return RedirectResponse("/tutor/calendar", status_code=303)

    @app.post("/tutor/series/{rule_id}/cancel")
    async def cancel_series(rule_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.lessons.cancel_series(user["id"], rule_id)
        return RedirectResponse("/tutor/schedule", status_code=303)

    @app.post("/tutor/series/{rule_id}/reschedule")
    async def reschedule_series(rule_id: str, new_time: str = Form(...), user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.lessons.reschedule_series(user["id"], rule_id, new_time.strip()[:5])
        return RedirectResponse("/tutor/schedule", status_code=303)

    @app.get("/tutor/settings", response_class=HTMLResponse)
    async def tutor_settings(request: Request, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        return templates.TemplateResponse("settings.html", _ctx(request, user, "settings", bot_username=_config.BOT_USERNAME))

    # ---------------- STUDENT ----------------
    @app.get("/student", response_class=HTMLResponse)
    async def student_dashboard(request: Request, user: dict = Depends(current_user)) -> Response:
        if user["role"] != "student":
            return RedirectResponse("/tutor", status_code=303)
        lessons = await services.lessons.list_student_calendar(user["id"])
        next_lesson = await services.lessons.next_lesson_for_student(user["id"])
        homework = await services.homework.list_for_student(user["id"])
        game = services.gamification.compute(lessons, homework)
        active_hw = [h for h in homework if h.get("status") in ("new", "in_progress")]
        now_iso = datetime.now(timezone.utc).isoformat()
        upcoming = sorted(
            [l for l in lessons if l.get("status") == "scheduled" and (l.get("starts_at") or "") >= now_iso],
            key=lambda l: l.get("starts_at") or "",
        )[:6]
        return templates.TemplateResponse("student.html", _ctx(
            request, user, "overview",
            next_lesson=next_lesson, game=game, active_hw=active_hw, upcoming=upcoming,
        ))

    @app.get("/student/calendar", response_class=HTMLResponse)
    async def student_calendar(request: Request, view: str = "month", date: str | None = None, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        lessons = await services.lessons.list_student_calendar(user["id"])
        cal = build_calendar(lessons, view if view in {"day", "week", "month"} else "month", parse_anchor(date))
        return templates.TemplateResponse("calendar.html", _ctx(request, user, "calendar", cal=cal, base="/student/calendar"))

    @app.get("/student/homework", response_class=HTMLResponse)
    async def student_homework(request: Request, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        homework = await services.homework.list_for_student(user["id"])
        return templates.TemplateResponse("homework_student.html", _ctx(request, user, "homework", homework=homework))

    @app.post("/student/homework/{homework_id}/progress")
    async def hw_progress(homework_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        await services.homework.mark_in_progress(user["id"], homework_id)
        return RedirectResponse("/student/homework", status_code=303)

    @app.post("/student/homework/{homework_id}/submit")
    async def hw_submit(homework_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        await services.homework.mark_submitted(user["id"], homework_id)
        return RedirectResponse("/student/homework", status_code=303)

    @app.get("/student/progress", response_class=HTMLResponse)
    async def student_progress(request: Request, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        lessons = await services.lessons.list_student_calendar(user["id"])
        homework = await services.homework.list_for_student(user["id"])
        game = services.gamification.compute(lessons, homework)
        completed = sorted([l for l in lessons if l.get("status") == "completed"], key=lambda l: l.get("starts_at") or "", reverse=True)
        reviewed = [h for h in homework if h.get("status") == "reviewed"]
        progress = {
            "completed_lessons": len(completed),
            "homework_completion_percent": round(len(reviewed) / len(homework) * 100) if homework else 0,
            "reviewed": len(reviewed),
            "total_homework": len(homework),
        }
        return templates.TemplateResponse("student_progress.html", _ctx(
            request, user, "progress", game=game, progress=progress, history=completed[:15],
        ))

    @app.post("/student/lessons/{lesson_id}/confirm")
    async def student_confirm_lesson(lesson_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        return RedirectResponse("/student", status_code=303)

    @app.post("/student/lessons/{lesson_id}/cancel")
    async def student_cancel_lesson(lesson_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        await services.lessons.student_cancel_lesson(user["id"], lesson_id)
        return RedirectResponse("/student", status_code=303)

    @app.get("/student/settings", response_class=HTMLResponse)
    async def student_settings(request: Request, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        return templates.TemplateResponse("settings.html", _ctx(request, user, "settings", bot_username=_config.BOT_USERNAME))
