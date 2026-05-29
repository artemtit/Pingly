from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer

from application.factory import create_services
from config import WEB_SECRET

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
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


def register_routes(app: FastAPI) -> None:
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Response:
        try:
            user = await current_user(request)
        except HTTPException:
            return _login_redirect()
        return RedirectResponse("/tutor" if user["role"] == "tutor" else "/student", status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    async def login(request: Request) -> Response:
        return templates.TemplateResponse("login.html", {"request": request})

    @app.get("/auth/telegram")
    async def auth_telegram(token: str) -> Response:
        user = await services.web_auth.consume_login_token(token)
        if not user:
            return RedirectResponse("/login?error=expired", status_code=303)
        response = RedirectResponse("/tutor" if user["role"] == "tutor" else "/student", status_code=303)
        response.set_cookie(
            "pingly_session",
            signer.dumps(user["id"]),
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
        )
        return response

    @app.get("/logout")
    async def logout() -> Response:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie("pingly_session")
        return response

    @app.get("/design-tokens.css")
    async def design_tokens() -> Response:
        return FileResponse(BASE_DIR.parent / "design-tokens.css", media_type="text/css")

    @app.get("/tutor", response_class=HTMLResponse)
    async def tutor_dashboard(request: Request, user: dict = Depends(current_user)) -> Response:
        if user["role"] != "tutor":
            return RedirectResponse("/student", status_code=303)
        students = await services.students.list_students_by_user(user["id"])
        lessons = await services.lessons.list_tutor_calendar(user["id"])
        homework = await services.homework.list_for_tutor(user["id"])
        analytics = await services.analytics.tutor_dashboard(user["id"])
        notifications = await services.notifications.list_for_user(user["id"])
        return templates.TemplateResponse(
            "tutor.html",
            {
                "request": request,
                "user": user,
                "students": students,
                "lessons": lessons,
                "homework": homework,
                "analytics": analytics,
                "notifications": notifications,
            },
        )

    @app.get("/tutor/students", response_class=HTMLResponse)
    async def tutor_students(request: Request, q: str | None = None, user: dict = Depends(current_user)) -> Response:
        if user["role"] != "tutor":
            raise HTTPException(status_code=403)
        students = await services.students.list_students_by_user(user["id"], q)
        return templates.TemplateResponse("students.html", {"request": request, "user": user, "students": students, "q": q or ""})

    @app.get("/tutor/students/{student_id}", response_class=HTMLResponse)
    async def tutor_student_card(request: Request, student_id: str, user: dict = Depends(current_user)) -> Response:
        if user["role"] != "tutor":
            raise HTTPException(status_code=403)
        try:
            card = await services.students.student_card(user["id"], student_id)
        except PermissionError as exc:
            raise HTTPException(status_code=404) from exc
        return templates.TemplateResponse("student_card.html", {"request": request, "user": user, **card})

    @app.post("/tutor/lessons")
    async def create_lesson(
        student_id: str = Form(...),
        day_of_week: int = Form(...),
        lesson_time: str = Form(...),
        user: dict = Depends(current_user),
    ) -> Response:
        if user["role"] != "tutor":
            raise HTTPException(status_code=403)
        await services.lessons.create_recurring_lesson_for_user(user["id"], student_id, day_of_week, lesson_time)
        return RedirectResponse("/tutor#calendar", status_code=303)

    @app.post("/tutor/homework")
    async def create_homework(
        student_id: str = Form(...),
        title: str = Form(...),
        description: str = Form(""),
        user: dict = Depends(current_user),
    ) -> Response:
        if user["role"] != "tutor":
            raise HTTPException(status_code=403)
        await services.homework.create_homework(user["id"], student_id, title, description or None)
        return RedirectResponse("/tutor#homework", status_code=303)

    @app.get("/student", response_class=HTMLResponse)
    async def student_dashboard(request: Request, user: dict = Depends(current_user)) -> Response:
        if user["role"] != "student":
            return RedirectResponse("/tutor", status_code=303)
        lessons = await services.lessons.list_student_calendar(user["id"])
        next_lesson = await services.lessons.next_lesson_for_student(user["id"])
        homework = await services.homework.list_for_student(user["id"])
        notifications = await services.notifications.list_for_user(user["id"])
        reviewed = len([h for h in homework if h.get("status") == "reviewed"])
        progress = {
            "completed_lessons": len([l for l in lessons if l.get("status") == "completed"]),
            "homework_completion_percent": round(reviewed / len(homework) * 100) if homework else 0,
        }
        return templates.TemplateResponse(
            "student.html",
            {
                "request": request,
                "user": user,
                "lessons": lessons,
                "next_lesson": next_lesson,
                "homework": homework,
                "notifications": notifications,
                "progress": progress,
            },
        )
