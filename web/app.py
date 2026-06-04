from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer

import config as _config
from application.factory import create_services
from infrastructure import captcha as _captcha
from application.services.accounts import subscription_info as _subscription_info
from config import WEB_BASE_URL, WEB_SECRET
from web.calendar_view import STATUS_LABELS, build_calendar, parse_anchor

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["status_labels"] = STATUS_LABELS
templates.env.globals["role_label"] = lambda r: "Репетитор" if r == "tutor" else "Ученик"

_DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_MSK = timezone(timedelta(hours=3))

# Simple in-memory rate limiter for the unauthenticated booking endpoint. The app
# runs as a single uvicorn process, so a process-local window is enough to stop a
# client from flooding the requests table / a tutor's Telegram.
_RATE_BUCKETS: dict[str, list[float]] = {}
_BOOK_RATE_MAX = 5            # max accepted submissions
_BOOK_RATE_WINDOW = 60.0     # per this many seconds, per (ip, slug)


def _rate_ok(key: str, max_hits: int, window: float) -> bool:
    import time
    now = time.monotonic()
    hits = [t for t in _RATE_BUCKETS.get(key, []) if now - t < window]
    if len(hits) >= max_hits:
        _RATE_BUCKETS[key] = hits
        return False
    hits.append(now)
    _RATE_BUCKETS[key] = hits
    # Opportunistic cleanup so the dict doesn't grow unbounded.
    if len(_RATE_BUCKETS) > 5000:
        for k in [k for k, v in _RATE_BUCKETS.items() if all(now - t >= window for t in v)]:
            _RATE_BUCKETS.pop(k, None)
    return True


def _ru_weekday(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return _DAYS_RU[dt.astimezone(_MSK).weekday()]
    except Exception:
        return ""


def _fmt_msk(dt_str: str, fmt: str = "%d.%m %H:%M") -> str:
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return dt.astimezone(_MSK).strftime(fmt)
    except Exception:
        return str(dt_str)[:16].replace("T", " ")


def _ru_days(n: object) -> str:
    """Russian plural for 'день': 1 день, 2-4 дня, 5-20 дней, 21 день, 44 дня…"""
    try:
        n = abs(int(n))
    except (TypeError, ValueError):
        return "дней"
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "дня"
    return "дней"


templates.env.filters["ru_weekday"] = _ru_weekday
templates.env.filters["msk"] = _fmt_msk
templates.env.filters["ru_days"] = _ru_days
templates.env.globals["subscription_info"] = _subscription_info
templates.env.globals["support_email"] = _config.SUPPORT_EMAIL
templates.env.globals["support_username"] = _config.SUPPORT_USERNAME
templates.env.globals["payments_enabled"] = _config.PAYMENTS_ENABLED
templates.env.globals["captcha_enabled"] = _config.CAPTCHA_ENABLED
templates.env.globals["turnstile_site_key"] = _config.TURNSTILE_SITE_KEY

# Brand icon set for the public-page badges (chips). key -> {label for the picker,
# svg = inner paths rendered inside a stroked 24x24 <svg>}.
BADGE_ICONS: dict[str, dict[str, str]] = {
    "monitor": {"label": "💻 Онлайн", "svg": '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>'},
    "map-pin": {"label": "📍 Очно", "svg": '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>'},
    "gauge": {"label": "📊 Опыт", "svg": '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>'},
    "clock": {"label": "🕐 Время", "svg": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'},
    "calendar": {"label": "📅 Расписание", "svg": '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>'},
    "graduation-cap": {"label": "🎓 Образование", "svg": '<path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z"/><path d="M22 10v6"/><path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/>'},
    "award": {"label": "🏅 Результат", "svg": '<path d="m15.477 12.89 1.515 8.526a.5.5 0 0 1-.81.47l-3.58-2.687a1 1 0 0 0-1.197 0l-3.586 2.686a.5.5 0 0 1-.81-.469l1.514-8.526"/><circle cx="12" cy="8" r="6"/>'},
    "users": {"label": "👥 Ученики", "svg": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'},
    "star": {"label": "⭐ Рейтинг", "svg": '<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"/>'},
    "check": {"label": "✓ Гарантия", "svg": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>'},
    "ruble": {"label": "₽ Цена", "svg": '<path d="M6 11h8a4 4 0 0 0 0-8H9v18"/><path d="M6 15h8"/>'},
    "bell": {"label": "🔔 Напоминания", "svg": '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/>'},
    "message": {"label": "💬 Telegram", "svg": '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22z"/>'},
}

DEFAULT_BADGES = [
    {"icon": "clock", "text": "Ответ в течение дня"},
    {"icon": "calendar", "text": "Удобное время"},
    {"icon": "bell", "text": "Напоминания в Telegram"},
]

templates.env.globals["badge_icons"] = BADGE_ICONS
templates.env.globals["default_badges"] = DEFAULT_BADGES


def _user_plan(user: dict | None) -> str:
    """Effective tier. Default 'max' so accounts stay fully unlocked while the
    paywall is dormant; only matters once PLANS_ENABLED is turned on."""
    return ((user or {}).get("plan") or "max").lower()


def _plan_locked(user: dict | None, section: str) -> bool:
    """True only when the tier paywall is live AND this section is Max-only AND
    the account is not on Max. With PLANS_ENABLED off this is always False."""
    return bool(
        _config.PLANS_ENABLED
        and section in _config.MAX_ONLY_SECTIONS
        and _user_plan(user) != "max"
    )


templates.env.globals["vk_enabled"] = _config.VK_ENABLED
# Read at call time: VK_GROUP_ID is resolved from the token at startup.
templates.env.globals["vk_invite_base"] = lambda: f"https://vk.me/club{_config.VK_GROUP_ID}"
templates.env.globals["plans_enabled"] = _config.PLANS_ENABLED
templates.env.globals["price_pro"] = _config.PRICE_PRO_RUB
templates.env.globals["price_max"] = _config.PRICE_MAX_RUB
templates.env.globals["plan_locked"] = _plan_locked
templates.env.globals["user_plan"] = _user_plan
services = create_services()
signer = URLSafeSerializer(WEB_SECRET, salt="pingly-web-session")


async def _not_found(request: Request, exc: Exception) -> Response:
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)


async def _unauthorized(request: Request, exc: Exception) -> Response:
    """Not logged in → send to login instead of raw {"detail":"Unauthorized"}."""
    return RedirectResponse("/login", status_code=303)


async def _forbidden(request: Request, exc: Exception) -> Response:
    """Logged in but wrong role → bounce to the home router (their cabinet)."""
    return RedirectResponse("/", status_code=303)


def create_app() -> FastAPI:
    app = FastAPI(title="Pingly")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    register_routes(app)
    app.add_exception_handler(404, _not_found)
    app.add_exception_handler(401, _unauthorized)
    app.add_exception_handler(403, _forbidden)
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
    """Parse an <input type=datetime-local> value as Moscow time, return UTC."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if len(raw) == 16:  # YYYY-MM-DDTHH:MM
        raw += ":00"
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=_MSK).astimezone(timezone.utc)
    except ValueError:
        return None


async def _send_telegram(tg_id: int, text: str) -> None:
    """Fire-and-forget Telegram message from the web process via a short-lived
    Bot instance. Used for rare events (student removed, lesson cancelled)."""
    from aiogram import Bot

    bot = Bot(_config.BOT_TOKEN)
    try:
        await bot.send_message(tg_id, text)
    except Exception:
        pass
    finally:
        await bot.session.close()


async def _notify_removed_student(tg_id: int, tutor_name: str) -> None:
    await _send_telegram(
        tg_id,
        f"❌ Репетитор {tutor_name} удалил тебя из Pingly.\n\n"
        "Напоминания о занятиях больше приходить не будут. "
        "Если это ошибка — попроси у репетитора новую ссылку-приглашение.",
    )


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

    # Public legal pages — always reachable, no auth (payment provider review needs these).
    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy(request: Request) -> Response:
        return templates.TemplateResponse("legal_privacy.html", {"request": request})

    @app.get("/terms", response_class=HTMLResponse)
    async def terms(request: Request) -> Response:
        return templates.TemplateResponse("legal_terms.html", {"request": request})

    @app.get("/contacts", response_class=HTMLResponse)
    async def contacts(request: Request) -> Response:
        return templates.TemplateResponse("contacts.html", {"request": request, "bot_username": _config.BOT_USERNAME})

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
        if _config.EMAIL_VERIFICATION_ENABLED and not user.get("email_verified"):
            from urllib.parse import quote
            await services.web_auth.send_verification_code(user)
            return RedirectResponse(f"/verify?email={quote(email.strip().lower())}", status_code=303)
        response = RedirectResponse(_cabinet_url(user), status_code=303)
        _set_session(response, user)
        return response

    @app.get("/register", response_class=HTMLResponse)
    async def register(request: Request, error: str | None = None, ref: str | None = None) -> Response:
        return templates.TemplateResponse("register.html", {
            "request": request, "bot_username": _config.BOT_USERNAME, "error": error, "ref": ref or "",
        })

    @app.post("/register")
    async def register_submit(
        request: Request,
        full_name: str = Form(...), email: str = Form(...), password: str = Form(...),
        ref: str = Form(""),
        cf_turnstile_response: str = Form("", alias="cf-turnstile-response"),
    ) -> Response:
        from urllib.parse import quote
        if _config.CAPTCHA_ENABLED:
            ip = request.client.host if request.client else None
            if not await _captcha.verify_turnstile(cf_turnstile_response, ip):
                return RedirectResponse(f"/register?error={quote('Подтвердите, что вы не робот')}", status_code=303)
        user, err = await services.web_auth.register_tutor_email(
            full_name, email, password, require_verification=_config.EMAIL_VERIFICATION_ENABLED,
        )
        if err or not user:
            return RedirectResponse(f"/register?error={quote(err or 'Не удалось зарегистрироваться')}", status_code=303)
        if ref.strip():
            await services.accounts.apply_referral(user["id"], ref.strip())
        if _config.EMAIL_VERIFICATION_ENABLED:
            await services.web_auth.send_verification_code(user)
            return RedirectResponse(f"/verify?email={quote(user['email'])}", status_code=303)
        response = RedirectResponse(_cabinet_url(user), status_code=303)
        _set_session(response, user)
        return response

    @app.get("/verify", response_class=HTMLResponse)
    async def verify_page(request: Request, email: str = "", error: str | None = None, sent: str | None = None) -> Response:
        return templates.TemplateResponse("verify.html", {
            "request": request, "email": email, "error": error, "sent": sent,
        })

    @app.post("/verify")
    async def verify_submit(email: str = Form(...), code: str = Form(...)) -> Response:
        from urllib.parse import quote
        user, err = await services.web_auth.verify_email_code(email, code)
        if err or not user:
            return RedirectResponse(f"/verify?email={quote(email)}&error={quote(err or 'Неверный код')}", status_code=303)
        response = RedirectResponse(_cabinet_url(user), status_code=303)
        _set_session(response, user)
        return response

    @app.post("/verify/resend")
    async def verify_resend(email: str = Form(...)) -> Response:
        from urllib.parse import quote
        await services.web_auth.resend_code(email)
        return RedirectResponse(f"/verify?email={quote(email.strip().lower())}&sent=1", status_code=303)

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
        # `ref` is not part of Telegram's signed payload — pop it before the
        # hash check. apply_referral is idempotent (one bonus per account), so
        # it's safe to call whenever a ref link is used.
        ref = (data.pop("ref", "") or "").strip()
        user = await services.web_auth.login_telegram_widget(data)
        if not user:
            return RedirectResponse("/login?error=tg_failed", status_code=303)
        if ref:
            await services.accounts.apply_referral(user["id"], ref)
        response = RedirectResponse(_cabinet_url(user), status_code=303)
        _set_session(response, user)
        return response

    @app.get("/auth/telegram/link")
    async def auth_telegram_link(request: Request, user: dict = Depends(current_user)) -> Response:
        data = dict(request.query_params)
        ok, err = await services.web_auth.link_telegram(user["id"], data)
        base = "/tutor/settings" if user["role"] == "tutor" else "/student/settings"
        if not ok:
            from urllib.parse import quote
            return RedirectResponse(f"{base}?error={quote(err or 'Не удалось подключить Telegram')}", status_code=303)
        return RedirectResponse(f"{base}?saved=tg", status_code=303)

    @app.get("/logout")
    async def logout() -> Response:
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie("pingly_session")
        return response

    @app.get("/design-tokens.css")
    async def design_tokens() -> Response:
        return FileResponse(BASE_DIR.parent / "design-tokens.css", media_type="text/css")

    @app.get("/favicon.ico")
    async def favicon() -> Response:
        return FileResponse(BASE_DIR / "static" / "logo-mark.svg", media_type="image/svg+xml")

    # ---------------- PUBLIC BOOKING (/u/<slug>) ----------------
    @app.get("/u/{slug}", response_class=HTMLResponse)
    async def public_profile(request: Request, slug: str, sent: str | None = None) -> Response:
        profile = await services.public.get_public_profile(slug)
        if not profile:
            raise HTTPException(status_code=404)
        tutor_name = (profile.get("users") or {}).get("full_name") or profile.get("display_name") or "Репетитор"
        return templates.TemplateResponse("public_profile.html", {
            "request": request, "profile": profile, "tutor_name": tutor_name,
            "slug": profile.get("slug"), "sent": sent, "bot_username": _config.BOT_USERNAME,
            "badges": services.public.parse_badges(profile.get("badges")),
            "page_theme": profile.get("page_theme") or "auto",
        })

    @app.post("/u/{slug}/book")
    async def public_book(
        request: Request,
        slug: str,
        name: str = Form(...),
        contact: str = Form(...),
        preferred_time: str = Form(""),
        comment: str = Form(""),
    ) -> Response:
        client_ip = request.client.host if request.client else "?"
        if not _rate_ok(f"book:{client_ip}:{slug}", _BOOK_RATE_MAX, _BOOK_RATE_WINDOW):
            return RedirectResponse(f"/u/{slug}?sent=1", status_code=303)
        request_row = await services.public.create_booking(slug, name, contact, preferred_time, comment)
        if request_row:
            target = await services.public.booking_push_target(request_row["tutor_user_id"], name.strip(), contact.strip())
            if target:
                await _send_telegram(target[0], target[1])
            return RedirectResponse(f"/u/{slug}?sent=1", status_code=303)
        return RedirectResponse(f"/u/{slug}", status_code=303)

    # ---------------- PAYMENTS (Platega webhook) ----------------
    @app.post("/payments/platega/webhook")
    async def platega_webhook(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        ok = await services.billing.handle_webhook(
            request.headers.get("X-MerchantId"),
            request.headers.get("X-Secret"),
            body if isinstance(body, dict) else {},
        )
        return Response(status_code=200 if ok else 400)

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
        upcoming = [l for l in lessons if l.get("status") in ("scheduled", "confirmed", "reschedule_requested") and (l.get("starts_at") or "") >= now][:6]
        pending_hw = [h for h in homework if h.get("status") == "submitted"]
        finance = await services.lessons.finance_overview(user["id"])
        all_requests = await services.public.list_requests(user["id"])
        new_requests = [r for r in all_requests if r.get("status") == "new"]
        return templates.TemplateResponse("tutor.html", _ctx(
            request, user, "overview",
            students=students, analytics=analytics,
            upcoming=upcoming, pending_hw=pending_hw,
            finance=finance, new_requests=new_requests,
        ))

    @app.get("/tutor/students", response_class=HTMLResponse)
    async def tutor_students(request: Request, q: str | None = None, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        students = await services.students.list_students_by_user(user["id"], q)
        return templates.TemplateResponse("students.html", _ctx(request, user, "students", students=students, q=q or "", bot_username=_config.BOT_USERNAME))

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
        request: Request, student_id: str, created: str | None = None, saved: str | None = None, user: dict = Depends(current_user),
    ) -> Response:
        _require(user, "tutor")
        try:
            card = await services.students.student_card(user["id"], student_id)
        except PermissionError as exc:
            raise HTTPException(status_code=404) from exc
        return templates.TemplateResponse("student_card.html", _ctx(
            request, user, "students", **card, bot_username=_config.BOT_USERNAME, created=created, saved=saved,
        ))

    @app.post("/tutor/students/{student_id}/profile")
    async def update_student_profile(
        student_id: str,
        name: str = Form(...),
        subject_summary: str = Form(""),
        grade: str = Form(""),
        goal: str = Form(""),
        started_at: str = Form(""),
        default_price: str = Form(""),
        user: dict = Depends(current_user),
    ) -> Response:
        _require(user, "tutor")
        await services.students.update_profile(user["id"], student_id, {
            "name": name.strip(),
            "subject_summary": subject_summary.strip() or None,
            "grade": grade.strip() or None,
            "goal": goal.strip() or None,
            "started_at": started_at.strip() or None,
            "default_price": int(default_price) if default_price.strip().isdigit() else None,
        })
        return RedirectResponse(f"/tutor/students/{student_id}?saved=profile#profile", status_code=303)

    @app.post("/tutor/students/{student_id}/delete")
    async def delete_student(student_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        result = await services.students.delete_student(user["id"], student_id)
        if result.get("notify_tg_id"):
            await _notify_removed_student(result["notify_tg_id"], user.get("full_name") or "Репетитор")
        return RedirectResponse("/tutor/students", status_code=303)

    @app.post("/tutor/students/{student_id}/note")
    async def update_student_note(student_id: str, note: str = Form(""), user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.students.set_note(user["id"], student_id, note.strip() or None)
        return RedirectResponse(f"/tutor/students/{student_id}?saved=note#notes", status_code=303)

    @app.post("/tutor/students/{student_id}/package")
    async def update_student_package(
        student_id: str,
        action: str = Form("set"),
        package_size: str = Form(""),
        user: dict = Depends(current_user),
    ) -> Response:
        _require(user, "tutor")
        size = None
        if action == "set" and package_size.strip().isdigit() and int(package_size) > 0:
            size = int(package_size)
        await services.students.set_package(user["id"], student_id, size)
        return RedirectResponse(f"/tutor/students/{student_id}?saved=package#package", status_code=303)

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
            starts_at = datetime.fromisoformat(f"{day}T{time_norm}:00").replace(tzinfo=_MSK).astimezone(timezone.utc)
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
        if _plan_locked(user, "homework"):
            return RedirectResponse("/tutor/settings?upgrade=homework", status_code=303)
        students = await services.students.list_students_by_user(user["id"])
        homework = await services.homework.list_for_tutor(user["id"])
        hw_templates = await services.homework.list_templates(user["id"])
        return templates.TemplateResponse("homework_tutor.html", _ctx(request, user, "homework", students=students, homework=homework, hw_templates=hw_templates))

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

    @app.post("/tutor/lessons/{lesson_id}/delete")
    async def delete_lesson(lesson_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.lessons.delete_lesson(user["id"], lesson_id)
        return RedirectResponse("/tutor/calendar", status_code=303)

    @app.post("/tutor/lessons/{lesson_id}/paid")
    async def toggle_lesson_paid(lesson_id: str, paid: str = Form("1"), user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.lessons.set_lesson_paid(user["id"], lesson_id, paid == "1")
        return RedirectResponse("/tutor/finance", status_code=303)

    @app.get("/tutor/finance", response_class=HTMLResponse)
    async def tutor_finance(request: Request, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        if _plan_locked(user, "finance"):
            return RedirectResponse("/tutor/settings?upgrade=finance", status_code=303)
        overview = await services.lessons.finance_overview(user["id"])
        lessons = await services.lessons.list_tutor_calendar(user["id"])
        unpaid = [l for l in lessons if l.get("status") == "completed" and not l.get("paid")]
        unpaid.sort(key=lambda l: l.get("starts_at") or "", reverse=True)
        return templates.TemplateResponse("finance.html", _ctx(
            request, user, "finance", overview=overview, unpaid=unpaid,
        ))

    @app.get("/tutor/requests", response_class=HTMLResponse)
    async def tutor_requests(request: Request, saved: str | None = None, error: str | None = None, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        if _plan_locked(user, "requests"):
            return RedirectResponse("/tutor/settings?upgrade=requests", status_code=303)
        requests = await services.public.list_requests(user["id"])
        profile = await services.public.get_profile(user["id"])
        badge_list = services.public.parse_badges((profile or {}).get("badges")) or DEFAULT_BADGES
        return templates.TemplateResponse("requests.html", _ctx(
            request, user, "requests", requests=requests,
            profile=profile, web_base=WEB_BASE_URL, saved=saved, error=error,
            badge_list=badge_list,
        ))

    @app.get("/tutor/requests/preview", response_class=HTMLResponse)
    async def public_preview(request: Request, user: dict = Depends(current_user)) -> Response:
        # An *ideal-example* page (a well-filled sample profile) so the tutor sees
        # how a good public page looks and how to fill their own. It does NOT show
        # the tutor's own data — it's a reference. The booking form is disabled.
        _require(user, "tutor")
        sample_profile = {
            "subjects": "Математика, физика · 5–11 класс",
            "bio": ("Помогаю подтянуть оценки и подготовиться к ОГЭ и ЕГЭ без "
                    "зубрёжки. Объясняю простым языком, занятия онлайн и очно."),
        }
        sample_badges = [
            {"icon": "monitor", "text": "Онлайн и очно"},
            {"icon": "gauge", "text": "Опыт 8 лет"},
            {"icon": "award", "text": "90% сдали на 4 и 5"},
            {"icon": "clock", "text": "Удобное время"},
        ]
        return templates.TemplateResponse("public_profile.html", {
            "request": request, "profile": sample_profile, "tutor_name": "Анна Соколова",
            "slug": "example", "sent": None, "bot_username": _config.BOT_USERNAME,
            "badges": sample_badges, "page_theme": "auto", "example": True,
        })

    @app.post("/tutor/requests/{request_id}/done")
    async def mark_request_done(request_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.public.mark_request(user["id"], request_id, "done")
        return RedirectResponse("/tutor/requests", status_code=303)

    @app.post("/tutor/homework/templates")
    async def create_homework_template(title: str = Form(...), description: str = Form(""), user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.homework.create_template(user["id"], title, description)
        return RedirectResponse("/tutor/homework", status_code=303)

    @app.post("/tutor/homework/templates/{template_id}/delete")
    async def delete_homework_template(template_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        await services.homework.delete_template(user["id"], template_id)
        return RedirectResponse("/tutor/homework", status_code=303)

    @app.post("/tutor/settings/public")
    async def update_public_profile(
        slug: str = Form(""),
        bio: str = Form(""),
        subjects: str = Form(""),
        public_enabled: str = Form(""),
        badge_icon: list[str] = Form(default=[]),
        badge_text: list[str] = Form(default=[]),
        page_theme: str = Form("auto"),
        user: dict = Depends(current_user),
    ) -> Response:
        _require(user, "tutor")
        # Pair each icon with its text; drop empty rows. Stored as "icon|text" lines.
        badges = "\n".join(
            f"{(ic or 'check').strip()}|{tx.strip()}"
            for ic, tx in zip(badge_icon, badge_text) if (tx or "").strip()
        )
        _, err = await services.public.update_profile(
            user["id"], slug, bio, subjects, public_enabled == "1", badges, page_theme,
        )
        if err:
            from urllib.parse import quote
            return RedirectResponse(f"/tutor/requests?error={quote(err)}", status_code=303)
        return RedirectResponse("/tutor/requests?saved=1", status_code=303)

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
    async def tutor_settings(request: Request, saved: str | None = None, error: str | None = None, paid: str | None = None, upgrade: str | None = None, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        profile = await services.public.get_profile(user["id"])
        return templates.TemplateResponse("settings.html", _ctx(
            request, user, "settings", bot_username=_config.BOT_USERNAME,
            profile=profile, web_base=WEB_BASE_URL, referral_code=user.get("referral_code"),
            saved=saved, error=error, paid=paid, upgrade=upgrade, price=_config.SUBSCRIPTION_PRICE_RUB,
        ))

    # ---------------- STUDENT ----------------
    @app.get("/student", response_class=HTMLResponse)
    async def student_dashboard(request: Request, user: dict = Depends(current_user)) -> Response:
        if user["role"] != "student":
            return RedirectResponse("/tutor", status_code=303)
        lessons = await services.lessons.list_student_calendar(user["id"])
        next_lesson = await services.lessons.next_lesson_for_student(user["id"])
        homework = await services.homework.list_for_student(user["id"])
        active_hw = [h for h in homework if h.get("status") in ("new", "in_progress")]
        now_iso = datetime.now(timezone.utc).isoformat()
        upcoming = sorted(
            [l for l in lessons if l.get("status") in ("scheduled", "confirmed", "reschedule_requested") and (l.get("starts_at") or "") >= now_iso],
            key=lambda l: l.get("starts_at") or "",
        )[:6]
        return templates.TemplateResponse("student.html", _ctx(
            request, user, "overview",
            next_lesson=next_lesson, active_hw=active_hw, upcoming=upcoming,
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

    @app.post("/student/lessons/{lesson_id}/confirm")
    async def student_confirm_lesson(lesson_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        await services.lessons.student_confirm_lesson(user["id"], lesson_id)
        return RedirectResponse("/student", status_code=303)

    @app.post("/student/lessons/{lesson_id}/cancel")
    async def student_cancel_lesson(lesson_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        lesson = await services.lessons.student_cancel_lesson(user["id"], lesson_id)
        if lesson:
            target = await services.lessons.cancel_push_target(lesson)
            if target:
                await _send_telegram(target[0], target[1])
        return RedirectResponse("/student", status_code=303)

    @app.post("/student/lessons/{lesson_id}/reschedule-request")
    async def student_request_reschedule(lesson_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        lesson = await services.lessons.student_request_reschedule(user["id"], lesson_id)
        if lesson:
            target = await services.lessons.reschedule_request_push_target(lesson)
            if target:
                await _send_telegram(target[0], target[1])
        return RedirectResponse("/student", status_code=303)

    @app.get("/student/history", response_class=HTMLResponse)
    async def student_history(request: Request, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        history = await services.lessons.list_student_history(user["id"])
        return templates.TemplateResponse("history.html", _ctx(request, user, "history", history=history))

    @app.post("/tutor/billing/subscribe")
    async def billing_subscribe(plan: str = Form("max"), user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        if not _config.PAYMENTS_ENABLED:
            # Payments are temporarily off (pending bank approval). Infra stays;
            # we just don't start a charge.
            return RedirectResponse("/tutor/settings?error=payments_off", status_code=303)
        redirect, err = await services.billing.start_subscription(user, WEB_BASE_URL, plan)
        if err or not redirect:
            from urllib.parse import quote
            return RedirectResponse(f"/tutor/settings?error={quote(err or 'Не удалось создать платёж')}", status_code=303)
        return RedirectResponse(redirect, status_code=303)

    @app.post("/support")
    async def support(message: str = Form(...), user: dict = Depends(current_user)) -> Response:
        text = (message or "").strip()
        base = "/tutor/settings" if user["role"] == "tutor" else "/student/settings"
        if text and _config.SUPPORT_TG_ID:
            who = user.get("full_name") or "Пользователь"
            role = "репетитор" if user["role"] == "tutor" else "ученик"
            contact = ("@" + user["tg_username"]) if user.get("tg_username") else (user.get("email") or "—")
            acct_id = str(user.get("id") or "")[:8].upper()
            await _send_telegram(
                _config.SUPPORT_TG_ID,
                f"🆘 Поддержка Pingly\n\nОт: {who} ({role}, {contact})\nID: {acct_id}\n\n{text[:3000]}",
            )
        return RedirectResponse(f"{base}?saved=support", status_code=303)

    @app.post("/settings/name")
    async def update_name(full_name: str = Form(...), user: dict = Depends(current_user)) -> Response:
        await services.accounts.update_name_by_user_id(user["id"], full_name)
        base = "/tutor/settings" if user["role"] == "tutor" else "/student/settings"
        return RedirectResponse(f"{base}?saved=name", status_code=303)

    @app.get("/student/settings", response_class=HTMLResponse)
    async def student_settings(request: Request, saved: str | None = None, error: str | None = None, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        return templates.TemplateResponse("settings.html", _ctx(request, user, "settings", bot_username=_config.BOT_USERNAME, saved=saved, error=error))
