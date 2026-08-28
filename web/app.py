from __future__ import annotations

import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import httpx
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import config as _config
from application.factory import create_services
from infrastructure import captcha as _captcha
from infrastructure.deepseek import complete as _ai_complete, extract_text as _ai_extract_text
from application.services.accounts import subscription_info as _subscription_info
from application.services.lessons import _plural_hours
from application.services.timezones import (
    TZ_CHOICES, current_tz, normalize_offset, set_current_offset,
)
from config import WEB_BASE_URL, WEB_SECRET
from web.calendar_view import STATUS_LABELS, build_calendar, parse_anchor

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["status_labels"] = STATUS_LABELS
templates.env.globals["role_label"] = lambda r: "Репетитор" if r == "tutor" else "Ученик"

_DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _ics_escape(text: str) -> str:
    """Escape a value for an iCalendar TEXT field (RFC 5545)."""
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _build_ics(lessons: list[dict]) -> str:
    """F11: the tutor's lessons as an iCalendar feed they can import into Google
    Calendar / Apple Calendar. Times are emitted in UTC (Z), so any client shows
    them in the viewer's own zone correctly."""
    now = datetime.now(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Pingly//Calendar//RU",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Pingly — занятия",
    ]
    for lesson in lessons:
        if lesson.get("status") == "cancelled":
            continue
        raw = lesson.get("starts_at")
        if not raw:
            continue
        try:
            start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        end = start + timedelta(minutes=int(lesson.get("duration_minutes") or 60))
        name = (lesson.get("student_profiles") or {}).get("name") or "Ученик"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{lesson.get('id')}@pingly-app.ru",
            f"DTSTAMP:{_ics_dt(now)}",
            f"DTSTART:{_ics_dt(start)}",
            f"DTEND:{_ics_dt(end)}",
            f"SUMMARY:{_ics_escape('Занятие — ' + name)}",
        ]
        if lesson.get("public_comment"):
            lines.append(f"DESCRIPTION:{_ics_escape(lesson['public_comment'])}")
        lines += ["STATUS:" + ("CONFIRMED" if lesson.get("status") == "confirmed" else "TENTATIVE"), "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _build_finance_csv(data: dict) -> str:
    """Per-student billing as a CSV (`;`-separated + UTF-8 BOM so Russian Excel
    opens Cyrillic and columns correctly). `data` comes from
    LessonService.finance_export — students filtered to a period, with a matching
    ИТОГО row so the totals are internally consistent."""
    import csv
    import io
    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["Отчёт по оплатам — Pingly"])
    writer.writerow([f"Период: {data.get('period_label', 'всё время')}"])
    writer.writerow([f"Сформирован: {data.get('generated', '')}"])
    writer.writerow([])
    writer.writerow(["Ученик", "Проведено занятий", "Оплачено, ₽", "Не оплачено, ₽", "Неоплаченных занятий"])
    for s in data.get("students", []):
        writer.writerow([
            s.get("name", ""), s.get("lessons", 0), s.get("paid_sum", 0),
            s.get("unpaid_sum", 0), s.get("unpaid_count", 0),
        ])
    totals = data.get("totals") or {}
    writer.writerow([])
    writer.writerow([
        "ИТОГО", totals.get("lessons", 0), totals.get("paid_sum", 0),
        totals.get("unpaid_sum", 0), totals.get("unpaid_count", 0),
    ])
    return buf.getvalue()

# Simple in-memory rate limiter for the unauthenticated booking endpoint. The app
# runs as a single uvicorn process, so a process-local window is enough to stop a
# client from flooding the requests table / a tutor's Telegram.
_RATE_BUCKETS: dict[str, list[float]] = {}
_BOOK_RATE_MAX = 5            # max accepted submissions
_BOOK_RATE_WINDOW = 60.0     # per this many seconds, per (ip, slug)
# Auth endpoints: throttle brute-force and registration/email spam. (max, window_s)
_LOGIN_RATE = (10, 300.0)    # per IP / 5 min — password guessing
_REGISTER_RATE = (5, 900.0)  # per IP / 15 min — signup spam
_VERIFY_RATE = (10, 600.0)   # per email / 10 min — code guessing
_RESEND_RATE = (3, 600.0)    # per email / 10 min — email bombing
_TG_AUTH_RATE = (20, 300.0)  # per IP / 5 min — forged Telegram auth_date/hash guessing

# Редакция текста согласия на обработку ПДн (страница /consent). Пишется в
# users.pd_consent_version вместе с моментом согласия. Менять ОБЯЗАТЕЛЬНО при
# любой правке смысла текста: иначе в базе будет написано, что человек
# согласился с редакцией, которой он не видел.
PD_CONSENT_VERSION = "2026-08-28"
_TRACK_RATE = (240, 60.0)    # per IP / 1 min — публичный приём событий аналитики.
                             # Щедро: за одним IP сидит целый класс через NAT.

# Public landing stats: cached in-process so landing traffic never hammers the DB.
_PUBLIC_STATS: dict[str, float | int | None] = {"value": None, "at": 0.0}
_PUBLIC_STATS_TTL = 300.0  # seconds


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


def _client_ip(request: Request) -> str:
    """Real client IP for rate-limiting. Behind Cloudflare→nginx, request.client.host
    is the proxy, so every user would share one bucket (S7). Prefer Cloudflare's
    CF-Connecting-IP (set by CF, forwarded by nginx), then the first X-Forwarded-For
    hop, then the socket peer as a last resort."""
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _csrf_origin_ok(request: Request) -> bool:
    """CSRF defense (S8): for state-changing requests, require the Origin/Referer to
    match our own host. Combined with the session cookie's SameSite=Lax, this blocks
    cross-site form/fetch attacks without a per-form token. If neither header is
    present (rare for real browser POSTs) we allow — SameSite=Lax is the backstop."""
    src = request.headers.get("origin") or request.headers.get("referer")
    if not src:
        return True
    try:
        src_host = urlparse(src).netloc.lower()
    except ValueError:
        return False
    allowed = {"pingly-app.ru", "www.pingly-app.ru"}
    host = (request.headers.get("host") or "").lower()
    if host:
        allowed.add(host)
    wb = urlparse(WEB_BASE_URL).netloc.lower()
    if wb:
        allowed.add(wb)
    return src_host in allowed


def _ru_weekday(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return _DAYS_RU[dt.astimezone(current_tz()).weekday()]
    except Exception:
        return ""


def _fmt_msk(dt_str: str, fmt: str = "%d.%m %H:%M") -> str:
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return dt.astimezone(current_tz()).strftime(fmt)
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


def _series_view(rule: dict, name_by_id: dict) -> dict:
    """Human-readable summary of a recurring schedule rule for the schedule page."""
    import json
    wd = rule.get("weekdays") or [rule.get("day_of_week", 0)]
    if isinstance(wd, str):
        try:
            wd = json.loads(wd)
        except Exception:
            wd = [rule.get("day_of_week", 0)]
    days = ", ".join(_DAYS_RU[int(d)] for d in wd if 0 <= int(d) <= 6)
    t = str(rule.get("lesson_time") or "")[:5]
    rec = rule.get("recurrence", "weekly")
    n = int(rule.get("interval_n", 1) or 1)
    if rec == "daily":
        freq = "каждый день"
    elif rec == "every_n_days":
        freq = f"каждые {n} дн."
    elif rec == "every_n_weeks":
        freq = f"{days} · каждые {n} нед."
    else:  # weekly / multiple_weekly
        freq = f"{days} · каждую неделю"
    return {
        "id": rule["id"],
        "student_name": name_by_id.get(rule.get("student_id"), "Ученик"),
        "schedule_text": f"{freq} · {t}" if t else freq,
        "time_hhmm": t,
    }


templates.env.filters["ru_weekday"] = _ru_weekday
templates.env.filters["msk"] = _fmt_msk
templates.env.filters["ru_days"] = _ru_days
templates.env.filters["ru_hours"] = lambda n: _plural_hours(int(n))
templates.env.globals["subscription_info"] = _subscription_info
templates.env.globals["support_email"] = _config.SUPPORT_EMAIL
templates.env.globals["owner_name"] = _config.OWNER_NAME
templates.env.globals["owner_status"] = _config.OWNER_STATUS
templates.env.globals["owner_address"] = _config.OWNER_ADDRESS
templates.env.globals["support_username"] = _config.SUPPORT_USERNAME
templates.env.globals["tg_bot_id"] = _config.BOT_ID
templates.env.globals["paywall_enabled"] = _config.PAYWALL_ENABLED and _config.PAYMENTS_ENABLED
templates.env.globals["web_base"] = _config.WEB_BASE_URL
templates.env.globals["posthog_key"] = _config.POSTHOG_KEY
templates.env.globals["posthog_host"] = _config.POSTHOG_HOST
templates.env.globals["metrika_id"] = _config.METRIKA_ID
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
# Key→SVG map for the live preview, so its chips render the SAME icons as the
# real public page (not the emoji from the <select> labels).
templates.env.globals["badge_svgs"] = {k: v["svg"] for k, v in BADGE_ICONS.items()}


def _user_plan(user: dict | None) -> str:
    """Effective tier. Default 'max' so accounts stay fully unlocked while the
    paywall is dormant; only matters once PLANS_ENABLED is turned on."""
    return ((user or {}).get("plan") or "max").lower()


def _access_until_active(user: dict | None) -> bool:
    """True while the account's access window (trial_ends_at, reused as the
    'access until' date for paid periods too) is still in the future."""
    raw = (user or {}).get("trial_ends_at")
    if not raw:
        return False
    try:
        ends = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    return (ends - datetime.now(timezone.utc)).total_seconds() > 0


def _plan_locked(user: dict | None, section: str) -> bool:
    """Whether a Max-only section is locked for this account. With PLANS_ENABLED
    off this is always False.

    Access model (tiers live):
    - Paid subscriber (subscription_status == 'active'): the chosen tier decides —
      Max keeps everything, Pro loses the Max-only sections.
    - Still on trial (window not expired, not yet paid): full access.
    - Trial expired without a Max subscription: Max-only sections lock (drop to Pro)."""
    if not (_config.PLANS_ENABLED and section in _config.MAX_ONLY_SECTIONS):
        return False
    user = user or {}
    status = (user.get("subscription_status") or "trial").lower()
    if status == "active":
        return _user_plan(user) != "max"
    # Not a paying subscriber → open during the trial, locked once it expires.
    return not _access_until_active(user)


templates.env.globals["vk_enabled"] = _config.VK_ENABLED
templates.env.globals["ai_enabled"] = _config.AI_ENABLED and bool(_config.DEEPSEEK_API_KEY)
# Read at call time: VK_GROUP_ID is resolved from the token at startup.
templates.env.globals["vk_invite_base"] = lambda: f"https://vk.me/club{_config.VK_GROUP_ID}"
templates.env.globals["plans_enabled"] = _config.PLANS_ENABLED
templates.env.globals["price_pro"] = _config.PRICE_PRO_RUB
templates.env.globals["price_max"] = _config.PRICE_MAX_RUB
templates.env.globals["price_year"] = _config.SUBSCRIPTION_PRICE_YEAR_RUB
templates.env.globals["plan_locked"] = _plan_locked
templates.env.globals["user_plan"] = _user_plan
services = create_services()
# Sessions expire after 30 days; a stolen cookie isn't valid forever. Refuse to
# boot in production (https) with the insecure default secret — otherwise anyone
# could forge a session for any user.
SESSION_MAX_AGE = 60 * 60 * 24 * 30
# S2: refuse to boot with the insecure default secret anywhere except a local dev
# host — otherwise anyone could forge a session for any user. (No longer keyed on
# the URL scheme: production is "not localhost".)
_secret_host = (urlparse(WEB_BASE_URL).hostname or "").lower()
if WEB_SECRET in ("", "dev-change-me") and _secret_host not in ("localhost", "127.0.0.1", ""):
    raise RuntimeError("WEB_SECRET must be set to a strong value in production")
signer = URLSafeTimedSerializer(WEB_SECRET, salt="pingly-web-session")


def _decode_session(raw: str) -> tuple[str | None, int | None] | None:
    """(user_id, token_version) from a session cookie, or None if the signature is
    bad/expired. A dict payload carries token_version (S6); a bare-string payload is
    a legacy pre-S6 cookie (token_version unknown → not enforced)."""
    try:
        data = signer.loads(raw, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if isinstance(data, dict):
        return data.get("uid"), data.get("tv")
    return data, None


def _session_tv_ok(user: dict, tv: int | None) -> bool:
    """S6: reject a cookie whose token_version is behind the user's current one
    (i.e. issued before a logout-all / password change)."""
    if tv is None:
        return True
    return int(user.get("token_version") or 0) == int(tv)


async def _not_found(request: Request, exc: Exception) -> Response:
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)


async def _unauthorized(request: Request, exc: Exception) -> Response:
    """Not logged in → send to login instead of raw {"detail":"Unauthorized"}."""
    return RedirectResponse("/login", status_code=303)


async def _forbidden(request: Request, exc: Exception) -> Response:
    """Logged in but wrong role → bounce to the home router (their cabinet)."""
    return RedirectResponse("/", status_code=303)


async def _server_error(request: Request, exc: Exception) -> Response:
    """Any unhandled error → log it (with traceback) and show a branded page
    instead of a raw stack trace / blank 500."""
    logging.getLogger("pingly.web").exception("Unhandled error on %s", request.url.path)
    return templates.TemplateResponse("500.html", {"request": request}, status_code=500)


class CachedStaticFiles(StaticFiles):
    """Static files with a long Cache-Control so Cloudflare/browsers serve them
    from cache instead of hitting the origin on every page load. CSS/JS are
    versioned with ?v=, so a long TTL is safe — bump the version to bust it."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "public, max-age=604800"
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="Pingly")
    app.mount("/static", CachedStaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.middleware("http")
    async def _paywall(request: Request, call_next):
        """Hard paywall: a tutor whose trial expired with no active subscription
        is bounced to Settings (the only place with a pay button) on every other
        cabinet page. Students and not-yet-lapsed tutors are untouched."""
        if _config.PAYWALL_ENABLED and _config.PAYMENTS_ENABLED:
            path = request.url.path
            if path.startswith("/tutor") and not path.startswith(_PAYWALL_OPEN_PREFIXES):
                user = await _user_from_cookie(request)
                if user and user.get("role") == "tutor" and not _subscription_info(user)["active"]:
                    return RedirectResponse("/tutor/settings?locked=1", status_code=303)
        return await call_next(request)

    @app.middleware("http")
    async def _email_required(request: Request, call_next):
        """A tutor account created via Telegram has no email on file. Force
        linking one before any cabinet page loads — for account recovery, and
        so a later email registration by the same person is caught as a
        duplicate here instead of silently creating a second, empty account."""
        path = request.url.path
        if path.startswith(("/tutor", "/student")):
            user = await _user_from_cookie(request)
            if user and user.get("role") == "tutor" and not user.get("email"):
                return RedirectResponse("/link-email", status_code=303)
        return await call_next(request)

    register_routes(app)
    app.add_exception_handler(404, _not_found)
    app.add_exception_handler(401, _unauthorized)
    app.add_exception_handler(403, _forbidden)
    app.add_exception_handler(500, _server_error)
    app.add_exception_handler(Exception, _server_error)
    return app


async def current_user(request: Request) -> dict:
    raw = request.cookies.get("pingly_session")
    if not raw:
        raise HTTPException(status_code=401)
    decoded = _decode_session(raw)
    if not decoded or not decoded[0]:
        raise HTTPException(status_code=401)
    user_id, tv = decoded
    user = await services.accounts.get_user(user_id)
    if not user or not _session_tv_ok(user, tv) or user.get("is_blocked"):
        raise HTTPException(status_code=401)
    # F6: pin this request's display/parse timezone to the tutor's setting.
    set_current_offset(user.get("tz_offset_minutes"))
    return user


async def _user_from_cookie(request: Request) -> dict | None:
    """Resolve the logged-in user from the session cookie without raising — for
    use in middleware where an anonymous request must simply pass through."""
    raw = request.cookies.get("pingly_session")
    if not raw:
        return None
    decoded = _decode_session(raw)
    if not decoded or not decoded[0]:
        return None
    user_id, tv = decoded
    try:
        user = await services.accounts.get_user(user_id)
        if user and _session_tv_ok(user, tv) and not user.get("is_blocked"):
            set_current_offset(user.get("tz_offset_minutes"))
            return user
        return None
    except Exception:
        return None


# Tutor-cabinet paths that stay reachable while the hard paywall is locking the
# rest of the cabinet — so a lapsed tutor can still get to the pay button.
_PAYWALL_OPEN_PREFIXES = ("/tutor/settings", "/tutor/billing")


def _login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def _require(user: dict, role: str) -> None:
    if user["role"] != role:
        raise HTTPException(status_code=403)


def _require_admin(user: dict) -> None:
    # 404 (not 403) so the admin panel doesn't reveal its existence to non-admins.
    if not user.get("is_admin"):
        raise HTTPException(status_code=404)


def _parse_local(raw: str) -> datetime | None:
    """Parse an <input type=datetime-local> value as Moscow time, return UTC."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if len(raw) == 16:  # YYYY-MM-DDTHH:MM
        raw += ":00"
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=current_tz()).astimezone(timezone.utc)
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


async def _send_vk(peer_id: int, text: str) -> None:
    """Fire-and-forget VK message from the web process (VK mirror of _send_telegram)."""
    from infrastructure import vk

    await vk.send_message(peer_id, text)


async def _notify_tutor(target: tuple[str, int, str] | None) -> None:
    """Route a (channel, dest, text) push to the tutor's chosen channel. No-op on None."""
    if not target:
        return
    channel, dest, text = target
    if channel == "vk":
        await _send_vk(dest, text)
    else:
        await _send_telegram(dest, text)


async def _broadcast_telegram(tg_ids: list[int], text: str) -> dict:
    """Send the same message to many tutors via one short-lived Bot instance.
    Returns {sent, failed}. Throttled lightly to respect Telegram limits."""
    from aiogram import Bot

    import asyncio

    bot = Bot(_config.BOT_TOKEN)
    sent = failed = 0
    try:
        for i, tg_id in enumerate(tg_ids):
            try:
                await bot.send_message(tg_id, text)
                sent += 1
            except Exception:
                failed += 1
            if (i + 1) % 20 == 0:  # ~20 msgs/sec ceiling on Telegram
                await asyncio.sleep(1)
    finally:
        await bot.session.close()
    return {"sent": sent, "failed": failed}


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


def _with_goal(url: str, goal: str) -> str:
    """Прицепить ?goal=<имя> к redirect-адресу. Фронт (partials/analytics.html)
    отправит цель в Метрику и вычистит параметр из адресной строки."""
    return f"{url}{'&' if '?' in url else '?'}goal={goal}"


def _set_session(response: Response, user: dict) -> None:
    # S6: bind the cookie to the user's token_version so a logout-all / password
    # change can invalidate it. S5: Secure flag follows WEB_BASE_URL (https in prod).
    payload = {"uid": user["id"], "tv": int(user.get("token_version") or 0)}
    response.set_cookie(
        "pingly_session", signer.dumps(payload),
        httponly=True, samesite="lax", secure=urlparse(WEB_BASE_URL).scheme == "https",
        max_age=SESSION_MAX_AGE,
    )


def register_routes(app: FastAPI) -> None:  # noqa: C901 - route table
    # S8: reject cross-site state-changing requests (Origin/Referer must be ours).
    # Webhooks under /payments/ are exempt — they're server-to-server with their own
    # signature check and legitimately carry no browser Origin.
    _CSRF_EXEMPT_PREFIXES = ("/payments/",)

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE") \
                and not request.url.path.startswith(_CSRF_EXEMPT_PREFIXES) \
                and not _csrf_origin_ok(request):
            return JSONResponse({"detail": "CSRF check failed"}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        # Baseline security headers on every response (HSTS is left to Cloudflare;
        # X-Frame-Options is intentionally omitted so tutors can embed their /u/ page).
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # S10: clickjacking + baseline CSP. Public tutor pages (/u/<slug>) are the
        # one place we WANT embeddable (tutors paste them into their sites), so they
        # keep frame-ancestors *; everything else is frame-denied. We deliberately
        # do NOT restrict script-src: the cabinet leans on many inline scripts and
        # on* handlers, so a strict script CSP would break it without a big refactor.
        # frame-ancestors / object-src / base-uri are safe wins with no such risk.
        if request.url.path.startswith("/u/"):
            response.headers.setdefault(
                "Content-Security-Policy", "frame-ancestors *; base-uri 'self'; object-src 'none'")
        else:
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault(
                "Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
        ctype = (response.headers.get("content-type") or "").lower()
        if "text/html" in ctype or response.status_code in {301, 302, 303, 307, 308}:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/public/stats")
    async def public_stats() -> Response:
        """Честный счётчик для лендинга: сколько напоминаний «за 2 часа» реально
        отправлено ученикам. Значение из БД, никаких выдуманных цифр; кэш 5 минут
        в памяти + Cache-Control, чтобы лендинговый трафик не ходил в БД."""
        import time
        now = time.monotonic()
        stale = _PUBLIC_STATS["value"] is None or now - float(_PUBLIC_STATS["at"] or 0) > _PUBLIC_STATS_TTL
        if stale:
            try:
                _PUBLIC_STATS["value"] = await services.repo.count_sent_lesson_reminders()
                _PUBLIC_STATS["at"] = now
            except Exception:
                logging.getLogger("pingly.web").warning("public stats unavailable", exc_info=True)
                if _PUBLIC_STATS["value"] is None:
                    # Cold failure: no number to show — the landing hides the counter.
                    return JSONResponse({"reminders_sent": None}, status_code=503,
                                        headers={"Cache-Control": "no-store"})
                # Warm failure: keep serving the last known honest value.
        return JSONResponse({"reminders_sent": _PUBLIC_STATS["value"]},
                            headers={"Cache-Control": "public, max-age=300"})

    @app.post("/api/track", status_code=204)
    async def track_event(request: Request) -> Response:
        """Приём событий собственной аналитики. Всегда отвечает 204, что бы ни
        пришло: браузер шлёт это через sendBeacon и ответ всё равно не читает,
        а одинаковый ответ не подсказывает ботам, по каким признакам их режут."""
        empty = Response(status_code=204)
        if not _rate_ok(f"track:{_client_ip(request)}", *_TRACK_RATE):
            return empty
        try:
            body = await request.json()
        except Exception:
            return empty
        if not isinstance(body, dict):
            return empty

        # user_id берём прямо из подписанной куки, без похода в БД: это самый
        # частый запрос на сайте, лишний SELECT на каждый просмотр не нужен.
        user_id = None
        raw = request.cookies.get("pingly_session")
        if raw:
            decoded = _decode_session(raw)
            if decoded:
                user_id = decoded[0]

        try:
            await services.webstats.track(
                event=str(body.get("event") or ""),
                path=str(body.get("path") or "/"),
                visitor_id=str(body.get("v") or ""),
                session_id=str(body.get("s") or ""),
                referrer=str(body.get("ref") or ""),
                query=body.get("utm") if isinstance(body.get("utm"), dict) else {},
                user_agent=request.headers.get("user-agent", ""),
                user_id=user_id,
                props=body.get("props") if isinstance(body.get("props"), dict) else {},
            )
        except Exception:
            # Аналитика никогда не должна ронять запрос пользователя.
            logging.getLogger("pingly.web").warning("track: insert failed", exc_info=True)
        return empty

    @app.get("/robots.txt")
    async def robots() -> Response:
        body = (
            "User-agent: *\n"
            "Disallow: /tutor\n"
            "Disallow: /student\n"
            "Disallow: /admin\n"
            "Disallow: /auth\n"
            "Disallow: /payments\n"
            f"Sitemap: {WEB_BASE_URL.rstrip('/')}/sitemap.xml\n"
        )
        return Response(content=body, media_type="text/plain")

    @app.get("/yandex_{token}.html")
    async def yandex_verification(token: str) -> Response:
        # Яндекс.Вебмастер проверяет права по файлу в корне сайта.
        # Файл лежит в web/static/, роут отдаёт его с корня. Токен — только hex,
        # чтобы имя не могло увести FileResponse за пределы static/.
        if not re.fullmatch(r"[0-9a-f]{6,64}", token):
            raise HTTPException(status_code=404)
        path = BASE_DIR / "static" / f"yandex_{token}.html"
        if not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="text/html")

    @app.get("/sitemap.xml")
    async def sitemap() -> Response:
        base = WEB_BASE_URL.rstrip("/")
        paths = ["/", "/register", "/login", "/privacy", "/consent", "/terms", "/contacts"]
        # Public tutor pages are real, indexable content — include each enabled one.
        try:
            for slug in await services.public.list_public_slugs():
                paths.append(f"/u/{slug}")
        except Exception:
            logging.getLogger("pingly.web").warning("sitemap: could not list public slugs", exc_info=True)
        urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in paths)
        xml = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               f"{urls}</urlset>")
        return Response(content=xml, media_type="application/xml")

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

    @app.get("/consent", response_class=HTMLResponse)
    async def consent(request: Request) -> Response:
        # Отдельный документ, а не раздел политики: политика информирует, а
        # согласие по ст. 9 152-ФЗ — самостоятельный акт воли, и предъявлять
        # его при проверке надо отдельно от всего остального.
        return templates.TemplateResponse(
            "legal_consent.html", {"request": request, "consent_version": PD_CONSENT_VERSION},
        )

    @app.get("/contacts", response_class=HTMLResponse)
    async def contacts(request: Request) -> Response:
        return templates.TemplateResponse("contacts.html", {"request": request, "bot_username": _config.BOT_USERNAME})

    @app.get("/login", response_class=HTMLResponse)
    async def login(request: Request, error: str | None = None) -> Response:
        return templates.TemplateResponse("login.html", {
            "request": request, "bot_username": _config.BOT_USERNAME, "error": error,
        })

    @app.post("/login")
    async def login_submit(request: Request, email: str = Form(...), password: str = Form(...)) -> Response:
        ip = _client_ip(request)
        if not _rate_ok(f"login:{ip}", *_LOGIN_RATE):
            return RedirectResponse("/login?error=too_many", status_code=303)
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
        ref: str = Form(""), pd_consent: str = Form(""),
        cf_turnstile_response: str = Form("", alias="cf-turnstile-response"),
    ) -> Response:
        from urllib.parse import quote
        ip = _client_ip(request)
        if not _rate_ok(f"reg:{ip}", *_REGISTER_RATE):
            return RedirectResponse(f"/register?error={quote('Слишком много попыток. Попробуй позже.')}", status_code=303)
        if _config.CAPTCHA_ENABLED:
            if not await _captcha.verify_turnstile(cf_turnstile_response, ip):
                return RedirectResponse(f"/register?error={quote('Подтвердите, что вы не робот')}", status_code=303)
        # required у чекбокса — подсказка браузеру, а не защита: форму можно
        # отправить и мимо страницы. Согласие проверяем здесь, иначе в базе
        # окажутся аккаунты с записанным согласием, которого никто не давал.
        if pd_consent != "1":
            return RedirectResponse(
                f"/register?error={quote('Нужно согласие на обработку персональных данных')}", status_code=303,
            )
        user, err = await services.web_auth.register_tutor_email(
            full_name, email, password, require_verification=_config.EMAIL_VERIFICATION_ENABLED,
            consent_version=PD_CONSENT_VERSION,
        )
        if err or not user:
            return RedirectResponse(f"/register?error={quote(err or 'Не удалось зарегистрироваться')}", status_code=303)
        if ref.strip():
            await services.accounts.apply_referral(user["id"], ref.strip())
        if _config.EMAIL_VERIFICATION_ENABLED:
            await services.web_auth.send_verification_code(user)
            return RedirectResponse(f"/verify?email={quote(user['email'])}", status_code=303)
        response = RedirectResponse(f"{_cabinet_url(user)}?goal=signup", status_code=303)
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
        norm_email = email.strip().lower()
        if not _rate_ok(f"verify:{norm_email}", *_VERIFY_RATE):
            return RedirectResponse(f"/verify?email={quote(norm_email)}&error={quote('Слишком много попыток. Подожди и попробуй снова.')}", status_code=303)
        user, err = await services.web_auth.verify_email_code(email, code)
        if err or not user:
            return RedirectResponse(f"/verify?email={quote(email)}&error={quote(err or 'Неверный код')}", status_code=303)
        response = RedirectResponse(_cabinet_url(user), status_code=303)
        _set_session(response, user)
        return response

    @app.post("/verify/resend")
    async def verify_resend(email: str = Form(...)) -> Response:
        from urllib.parse import quote
        norm_email = email.strip().lower()
        if not _rate_ok(f"resend:{norm_email}", *_RESEND_RATE):
            return RedirectResponse(f"/verify?email={quote(norm_email)}&error={quote('Код уже отправлен. Подожди минуту.')}", status_code=303)
        await services.web_auth.resend_code(email)
        return RedirectResponse(f"/verify?email={quote(norm_email)}&sent=1", status_code=303)

    @app.get("/link-email", response_class=HTMLResponse)
    async def link_email_page(request: Request, error: str | None = None, user: dict = Depends(current_user)) -> Response:
        # Only a tutor who logged in via Telegram and has no email yet lands here
        # (see the _email_required middleware) — anyone else is bounced to their
        # cabinet so this page can't be reached "just because".
        if user.get("role") != "tutor" or user.get("email"):
            return RedirectResponse(_cabinet_url(user), status_code=303)
        return templates.TemplateResponse("link_email.html", {"request": request, "error": error})

    @app.post("/link-email")
    async def link_email_submit(
        email: str = Form(...), password: str = Form(...), user: dict = Depends(current_user),
    ) -> Response:
        from urllib.parse import quote
        if user.get("role") != "tutor" or user.get("email"):
            return RedirectResponse(_cabinet_url(user), status_code=303)
        updated, err = await services.web_auth.link_email(user["id"], email, password)
        if err or not updated:
            return RedirectResponse(f"/link-email?error={quote(err or 'Не удалось сохранить email')}", status_code=303)
        return RedirectResponse(_cabinet_url(user), status_code=303)

    @app.get("/auth/telegram")
    async def auth_telegram(token: str) -> Response:
        user = await services.web_auth.consume_login_token(token)
        if not user:
            return RedirectResponse("/login?error=expired", status_code=303)
        response = RedirectResponse(_cabinet_url(user), status_code=303)
        _set_session(response, user)
        return response

    # Роут /auth/telegram/callback (Telegram Login Widget) удалён 28.08.2026.
    # Ст. 8 ч. 10 149-ФЗ запрещает проводить авторизацию пользователей из РФ
    # через иностранную информационную систему, а ст. 13.55 КоАП (с 07.07.2026)
    # добавила за это штраф. Виджет подтверждал личность на стороне Telegram —
    # это ровно запрещённый механизм, поэтому убран и он, и создававший под него
    # аккаунты login_telegram_widget(). Вход через бота (/auth/telegram?token=)
    # остался: токен выпускает Pingly, Telegram лишь доставляет сообщение.
    # Привязка Telegram ниже — не авторизация: пользователь уже вошёл, и виджет
    # тут лишь подтверждает владение аккаунтом для доставки уведомлений.

    @app.post("/auth/telegram/link")
    async def auth_telegram_link(request: Request, user: dict = Depends(current_user)) -> Response:
        # Эндпоинт по-прежнему проверяет подпись Telegram, значит подпись можно
        # пытаться подбирать. Лимит переехал сюда со снятого виджет-роута.
        if not _rate_ok(f"tglink:{_client_ip(request)}", *_TG_AUTH_RATE):
            base = "/tutor/settings" if user["role"] == "tutor" else "/student/settings"
            return RedirectResponse(f"{base}?error=too_many", status_code=303)
        form = await request.form()
        data = {k: str(v) for k, v in form.items()}
        ok, err = await services.web_auth.link_telegram(user["id"], data)
        base = "/tutor/settings" if user["role"] == "tutor" else "/student/settings"
        if not ok:
            from urllib.parse import quote
            return RedirectResponse(f"{base}?error={quote(err or 'Не удалось подключить Telegram')}", status_code=303)
        return RedirectResponse(f"{base}?saved=tg", status_code=303)

    @app.get("/tutor/settings/vk/connect")
    async def tutor_vk_connect(user: dict = Depends(current_user)) -> Response:
        """Mint a one-time link token and bounce the tutor into the VK community
        chat carrying it (ref=lnk_<token>); the VK bot attaches their VK id."""
        _require(user, "tutor")
        if not _config.VK_ENABLED or not _config.VK_GROUP_ID:
            return RedirectResponse("/tutor/settings?error=vk_off", status_code=303)
        token = await services.web_auth.create_vk_link_token(user["id"])
        return RedirectResponse(
            f"https://vk.me/club{_config.VK_GROUP_ID}?ref=lnk_{token}", status_code=303,
        )

    @app.post("/logout")
    async def logout(request: Request) -> Response:
        # S6: bump token_version so every issued cookie for this user stops working,
        # not just the one on this device. Best-effort — always clear the cookie.
        raw = request.cookies.get("pingly_session")
        if raw:
            decoded = _decode_session(raw)
            if decoded and decoded[0]:
                try:
                    await services.repo.bump_token_version(decoded[0])
                except Exception:
                    logging.getLogger("pingly.web").warning("logout: bump_token_version failed", exc_info=True)
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
    async def public_profile(request: Request, slug: str, sent: str | None = None,
                             error: str | None = None) -> Response:
        profile = await services.public.get_public_profile(slug)
        if not profile:
            raise HTTPException(status_code=404)
        tutor_name = (profile.get("users") or {}).get("full_name") or profile.get("display_name") or "Репетитор"
        return templates.TemplateResponse("public_profile.html", {
            "request": request, "profile": profile, "tutor_name": tutor_name,
            "slug": profile.get("slug"), "sent": sent, "error": error,
            "bot_username": _config.BOT_USERNAME,
            "badges": services.public.parse_badges(profile.get("badges")),
            "page_theme": profile.get("page_theme") or "auto",
            "web_base": _config.WEB_BASE_URL,
        })

    @app.post("/u/{slug}/book")
    async def public_book(
        request: Request,
        slug: str,
        name: str = Form(...),
        contact: str = Form(...),
        preferred_time: str = Form(""),
        comment: str = Form(""),
        pd_consent: str = Form(""),
    ) -> Response:
        client_ip = _client_ip(request)
        if not _rate_ok(f"book:{client_ip}:{slug}", _BOOK_RATE_MAX, _BOOK_RATE_WINDOW):
            return RedirectResponse(f"/u/{slug}?sent=1", status_code=303)
        # Без согласия заявку не принимаем. Молча игнорировать нельзя: человек
        # решит, что записался, и будет ждать ответа, которого не будет.
        if pd_consent != "1":
            return RedirectResponse(f"/u/{slug}?error=consent", status_code=303)
        request_row = await services.public.create_booking(slug, name, contact, preferred_time, comment)
        if request_row:
            target = await services.public.booking_push_target(request_row["tutor_user_id"], name.strip(), contact.strip())
            await _notify_tutor(target)
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
        finance = await services.lessons.finance_overview(user["id"])
        now = datetime.now(timezone.utc).isoformat()
        upcoming = [l for l in lessons if l.get("status") in ("scheduled", "confirmed", "reschedule_requested") and (l.get("starts_at") or "") >= now][:6]
        pending_hw = [h for h in homework if h.get("status") == "submitted"]
        all_requests = await services.public.list_requests(user["id"])
        new_requests = [r for r in all_requests if r.get("status") == "new"]
        # Temporarily disabled on the dashboard; keep the code path ready for re-enable.
        ai_summary = None
        return templates.TemplateResponse("tutor.html", _ctx(
            request, user, "overview",
            students=students, analytics=analytics,
            upcoming=upcoming, pending_hw=pending_hw,
            finance=finance, new_requests=new_requests,
            ai_summary=ai_summary,
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
        return RedirectResponse(f"/tutor/students/{student['id']}?created=1&goal=student_added", status_code=303)

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
        # students feed the quick-add ("+" on an empty cell) modal
        students = await services.students.list_students_by_user(user["id"])
        return templates.TemplateResponse("calendar.html", _ctx(request, user, "calendar", cal=cal, base="/tutor/calendar", students=students))

    @app.get("/tutor/calendar.ics")
    async def tutor_calendar_ics(user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        lessons = await services.lessons.list_tutor_calendar(user["id"])
        return Response(
            content=_build_ics(lessons),
            media_type="text/calendar; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="pingly-calendar.ics"'},
        )

    @app.get("/tutor/finance.csv")
    async def tutor_finance_csv(period: str = "all", user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        if _plan_locked(user, "finance"):
            raise HTTPException(status_code=403)
        data = await services.lessons.finance_export(user["id"], period)
        fname = f"pingly-finance-{data['period']}.csv"
        return Response(
            content=_build_finance_csv(data),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    @app.get("/tutor/schedule", response_class=HTMLResponse)
    async def tutor_schedule(request: Request, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        students = await services.students.list_students_by_user(user["id"])
        lessons = await services.lessons.list_tutor_calendar(user["id"])
        now = datetime.now(timezone.utc).isoformat()
        # "Будущие занятия" = only still-pending ones. A completed/cancelled lesson
        # whose time hasn't passed yet must not show here with a «Проведено» badge.
        upcoming = [
            l for l in lessons
            if l.get("status") in ("scheduled", "confirmed", "reschedule_requested")
            and (l.get("starts_at") or "") >= now
        ][:30]
        name_by_id = {s["id"]: s["name"] for s in students}
        rules = await services.lessons.list_series(user["id"])
        series = [_series_view(r, name_by_id) for r in rules]
        return templates.TemplateResponse("schedule.html", _ctx(request, user, "schedule", students=students, upcoming=upcoming, series=series))

    @app.post("/tutor/schedule")
    async def create_schedule(
        student_id: str = Form(...),
        recurrence: str = Form("weekly"),
        lesson_time: str = Form("15:00"),
        lesson_date: str = Form(""),
        interval_n: int = Form(1),
        weekdays: list[int] = Form(default=[]),
        comment: str = Form(""),
        back: str = Form(""),
        user: dict = Depends(current_user),
    ) -> Response:
        _require(user, "tutor")
        time_norm = lesson_time.strip()[:5] or "15:00"
        topic = comment.strip()[:500] or None
        if recurrence == "once":
            day = lesson_date.strip() or datetime.now(timezone.utc).date().isoformat()
            starts_at = datetime.fromisoformat(f"{day}T{time_norm}:00").replace(tzinfo=current_tz()).astimezone(timezone.utc)
            await services.lessons.create_one_time_lesson(user["id"], student_id, starts_at, public_comment=topic)
        else:
            wd = weekdays or None
            await services.lessons.create_schedule(
                user["id"], student_id, recurrence, f"{time_norm}:00",
                weekdays=wd, interval_n=interval_n, public_comment=topic,
            )
        # quick-add from the calendar returns to the same view, not to month
        if back.startswith("/tutor/"):
            return RedirectResponse(_with_goal(back, "schedule_created"), status_code=303)
        return RedirectResponse("/tutor/calendar?view=month&goal=schedule_created", status_code=303)

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
        if _plan_locked(user, "homework"):
            return RedirectResponse("/tutor/settings?upgrade=homework", status_code=303)
        due = _parse_local(due_at)
        await services.homework.create_homework(user["id"], student_id, title, description or None, due)
        return RedirectResponse("/tutor/homework", status_code=303)

    @app.post("/tutor/homework/{homework_id}/review")
    async def review_homework(homework_id: str, comment: str = Form(""), user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        if _plan_locked(user, "homework"):
            return RedirectResponse("/tutor/settings?upgrade=homework", status_code=303)
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

    @app.post("/tutor/lessons/{lesson_id}/comment")
    async def set_lesson_comment(
        lesson_id: str, comment: str = Form(""), date: str = Form(""), user: dict = Depends(current_user),
    ) -> Response:
        _require(user, "tutor")
        try:
            await services.lessons.set_lesson_comment(user["id"], lesson_id, comment)
        except PermissionError as exc:
            raise HTTPException(status_code=404) from exc
        back = f"/tutor/calendar?view=day&date={date}" if date else "/tutor/calendar"
        return RedirectResponse(back, status_code=303)

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
        # oldest debts first: the longer it hangs, the more urgent it is
        unpaid.sort(key=lambda l: l.get("starts_at") or "")
        # last 6 calendar months of completed-lesson income for the sparkline,
        # plus a flat payment history for the per-student expandable timeline —
        # all derived from lessons already fetched, no extra queries
        ru_months = ["", "янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
        now_msk = datetime.now(current_tz())
        month_keys = []
        y, m = now_msk.year, now_msk.month
        for _ in range(6):
            month_keys.append((y, m))
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        month_keys.reverse()
        sums = {key: 0 for key in month_keys}
        fin_history: list[dict] = []
        for l in lessons:
            if l.get("status") != "completed":
                continue
            try:
                dt = datetime.fromisoformat(str(l["starts_at"]).replace("Z", "+00:00")).astimezone(current_tz())
            except (ValueError, KeyError):
                continue
            price = l.get("price") or 0
            if (dt.year, dt.month) in sums:
                sums[(dt.year, dt.month)] += price
            fin_history.append({
                "student_id": l.get("student_id") or "",
                "date": dt.strftime("%d.%m"),
                "ts": dt.isoformat(),
                "price": price,
                "paid": bool(l.get("paid")),
            })
        fin_history.sort(key=lambda r: r["ts"], reverse=True)
        fin_months = [{"label": ru_months[k[1]], "sum": sums[k]} for k in month_keys]
        return templates.TemplateResponse("finance.html", _ctx(
            request, user, "finance", overview=overview, unpaid=unpaid,
            fin_months=fin_months, fin_history=fin_history,
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
            "web_base": _config.WEB_BASE_URL,
        })

    @app.post("/tutor/requests/{request_id}/done")
    async def mark_request_done(request_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        if _plan_locked(user, "requests"):
            return RedirectResponse("/tutor/settings?upgrade=requests", status_code=303)
        await services.public.mark_request(user["id"], request_id, "done")
        return RedirectResponse("/tutor/requests", status_code=303)

    @app.post("/tutor/homework/templates")
    async def create_homework_template(title: str = Form(...), description: str = Form(""), user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        if _plan_locked(user, "homework"):
            return RedirectResponse("/tutor/settings?upgrade=homework", status_code=303)
        await services.homework.create_template(user["id"], title, description)
        return RedirectResponse("/tutor/homework", status_code=303)

    @app.post("/tutor/homework/templates/{template_id}/delete")
    async def delete_homework_template(template_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        if _plan_locked(user, "homework"):
            return RedirectResponse("/tutor/settings?upgrade=homework", status_code=303)
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
    async def tutor_settings(request: Request, saved: str | None = None, error: str | None = None, paid: str | None = None, upgrade: str | None = None, locked: str | None = None, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        # Returning from a payment: don't rely solely on the Platega webhook — ask
        # Platega directly and activate if confirmed, then refresh the user so the
        # page immediately shows the active subscription.
        if paid == "1" and _config.PAYMENTS_ENABLED:
            try:
                if await services.billing.reconcile_on_return(user["id"]):
                    refreshed = await services.accounts.get_user(user["id"])
                    if refreshed:
                        user = refreshed
            except Exception:
                logging.getLogger("pingly.web").exception("reconcile_on_return failed (user_id=%s)", user["id"])
        profile = await services.public.get_profile(user["id"])
        return templates.TemplateResponse("settings.html", _ctx(
            request, user, "settings", bot_username=_config.BOT_USERNAME,
            profile=profile, web_base=WEB_BASE_URL, referral_code=user.get("referral_code"),
            saved=saved, error=error, paid=paid, upgrade=upgrade, locked=locked, price=_config.SUBSCRIPTION_PRICE_RUB,
            tz_choices=TZ_CHOICES,
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
        lesson = await services.lessons.student_confirm_lesson(user["id"], lesson_id)
        if lesson:
            await _notify_tutor(await services.lessons.confirm_push_target(lesson))
        return RedirectResponse("/student", status_code=303)

    @app.post("/student/lessons/{lesson_id}/cancel")
    async def student_cancel_lesson(lesson_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        lesson = await services.lessons.student_cancel_lesson(user["id"], lesson_id)
        if lesson:
            await _notify_tutor(await services.lessons.cancel_push_target(lesson))
        return RedirectResponse("/student", status_code=303)

    @app.post("/student/lessons/{lesson_id}/reschedule-request")
    async def student_request_reschedule(lesson_id: str, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        lesson = await services.lessons.student_request_reschedule(user["id"], lesson_id)
        if lesson:
            await _notify_tutor(await services.lessons.reschedule_request_push_target(lesson))
        return RedirectResponse("/student", status_code=303)

    @app.get("/student/history", response_class=HTMLResponse)
    async def student_history(request: Request, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        history = await services.lessons.list_student_history(user["id"])
        return templates.TemplateResponse("history.html", _ctx(request, user, "history", history=history))

    @app.post("/tutor/billing/subscribe")
    async def billing_subscribe(plan: str = Form("max"), period: str = Form("month"), user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        if not _config.PAYMENTS_ENABLED:
            # Payments are temporarily off (pending bank approval). Infra stays;
            # we just don't start a charge.
            return RedirectResponse("/tutor/settings?error=payments_off", status_code=303)
        redirect, err = await services.billing.start_subscription(user, WEB_BASE_URL, plan, period)
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

    # ---------------- AI assistant (tutor cabinet) ----------------
    # In-memory per-tutor usage: user_id -> [day "YYYY-MM-DD", count, last monotonic].
    # Resets on restart — acceptable for a soft daily cap.
    _ai_usage: dict[str, list] = {}
    _ai_summary_cache: dict[str, list] = {}
    _AI_SUMMARY_TTL = 300.0
    _AI_ANALYTICS_HINTS = (
        "кто чаще",
        "кто переносит",
        "какие ученики",
        "сколько занятий",
        "сколько уроков",
        "у кого падает",
        "кого стоит предупредить",
        "сводк",
        "статист",
        "аналит",
        "отчёт",
        "отчет",
        "не платил",
        "не платили",
        "задолж",
        "долг",
        "явка",
        "посещаемост",
    )

    _AI_SYSTEM = (
        "Ты — встроенный ИИ-помощник сервиса Pingly (pingly-app.ru). "
        "Пользователь — репетитор по имени {name}.\n\n"
        "Чем помогаешь:\n"
        "- составить план занятия, домашнее задание, объяснение темы, мини-тест;\n"
        "- сформулировать сообщение ученику или родителю (напоминание, перенос, оплата);\n"
        "- ответить на вопросы про сам Pingly.\n\n"
        "Факты о Pingly (не выдумывай сверх этого):\n"
        "- Pingly сам шлёт ученикам напоминание за 2 часа до занятия в Telegram или ВКонтакте; "
        "ученик отвечает «Буду / Отменяю / Прошу перенести», репетитор видит статусы на сайте.\n"
        "- Разделы кабинета: Обзор, Ученики, Календарь, Расписание, Задания (ДЗ), Финансы, "
        "Заявки (запись с публичной страницы), Настройки.\n"
        "- Ученика добавляют на сайте и отправляют ему ссылку-приглашение в бота.\n"
        "- Подписка: 14 дней бесплатно, дальше 990 ₽/мес.\n"
        "Если не знаешь ответа про Pingly — скажи честно и направь в поддержку: Настройки → Поддержка.\n\n"
        "Стиль: по-русски, кратко и по делу. Простой текст без Markdown-заголовков; списки — с дефисами."
    )

    def _ai_parse_dt(raw: object) -> datetime | None:
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            return None

    def _ai_is_analytics_question(text: str) -> bool:
        low = f" {text.lower()} "
        if any(marker in low for marker in ("сводк", "статист", "аналит", "отчет", "отчёт", "задолж", "посещаемост", "явка")):
            return True
        interrogative = any(marker in low for marker in ("кто ", "какие ", "сколько ", "у кого ", "кого ", "как часто "))
        return interrogative and any(marker in low for marker in _AI_ANALYTICS_HINTS)

    def _ai_attendance_rate(completed: int, cancelled: int) -> int | None:
        total = completed + cancelled
        if not total:
            return None
        return round(completed / total * 100)

    def _ai_format_dt(raw: datetime | None) -> str:
        if not raw:
            return "—"
        return raw.astimezone(current_tz()).strftime("%d.%m")

    def _build_tutor_ai_snapshot(students: list[dict], lessons: list[dict], finance: dict) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        window_recent = now - timedelta(days=30)
        window_prev = now - timedelta(days=60)
        student_names = {str(s.get("id") or ""): (s.get("name") or "Ученик") for s in students}
        per_student: dict[str, dict[str, object]] = {}
        month_counts: Counter[str] = Counter()

        def get_row(lesson: dict) -> dict[str, object]:
            sid = str(lesson.get("student_id") or "")
            profile = lesson.get("student_profiles") or {}
            name = profile.get("name") or student_names.get(sid) or "Ученик"
            key = sid or name
            row = per_student.get(key)
            if row is None:
                row = {
                    "student_id": sid,
                    "name": name,
                    "total": 0,
                    "completed": 0,
                    "cancelled": 0,
                    "reschedule_requested": 0,
                    "rescheduled": 0,
                    "paid": 0,
                    "unpaid_count": 0,
                    "unpaid_sum": 0,
                    "last_lesson_at": None,
                    "last_reschedule_at": None,
                    "last_unpaid_at": None,
                    "recent_completed": 0,
                    "recent_cancelled": 0,
                    "prev_completed": 0,
                    "prev_cancelled": 0,
                }
                per_student[key] = row
            return row

        for lesson in lessons:
            started = _ai_parse_dt(lesson.get("starts_at"))
            if not started:
                continue
            month_counts[started.astimezone(current_tz()).strftime("%Y-%m")] += 1
            row = get_row(lesson)
            status = str(lesson.get("status") or "")
            row["total"] = int(row["total"]) + 1
            row["last_lesson_at"] = started if not row["last_lesson_at"] or started > row["last_lesson_at"] else row["last_lesson_at"]
            if status == "completed":
                row["completed"] = int(row["completed"]) + 1
            elif status == "cancelled":
                row["cancelled"] = int(row["cancelled"]) + 1
            elif status == "reschedule_requested":
                row["reschedule_requested"] = int(row["reschedule_requested"]) + 1
                row["last_reschedule_at"] = started if not row["last_reschedule_at"] or started > row["last_reschedule_at"] else row["last_reschedule_at"]
            elif status == "rescheduled":
                row["rescheduled"] = int(row["rescheduled"]) + 1

            if started <= now:
                if started >= window_recent:
                    if status == "completed":
                        row["recent_completed"] = int(row["recent_completed"]) + 1
                    elif status == "cancelled":
                        row["recent_cancelled"] = int(row["recent_cancelled"]) + 1
                elif started >= window_prev:
                    if status == "completed":
                        row["prev_completed"] = int(row["prev_completed"]) + 1
                    elif status == "cancelled":
                        row["prev_cancelled"] = int(row["prev_cancelled"]) + 1

            if status == "completed" and not lesson.get("paid"):
                price = int(lesson.get("price") or 0)
                row["unpaid_count"] = int(row["unpaid_count"]) + 1
                row["unpaid_sum"] = int(row["unpaid_sum"]) + price
                row["last_unpaid_at"] = started if not row["last_unpaid_at"] or started > row["last_unpaid_at"] else row["last_unpaid_at"]
            elif lesson.get("paid"):
                row["paid"] = int(row["paid"]) + 1

        def sort_key_name(item: dict[str, object]) -> tuple[int, str]:
            return (-int(item.get("count") or 0), str(item.get("name") or ""))

        reschedules = sorted(
            [
                {
                    "name": row["name"],
                    "count": int(row["reschedule_requested"]) + int(row["rescheduled"]),
                    "last": row["last_reschedule_at"],
                }
                for row in per_student.values()
                if int(row["reschedule_requested"]) + int(row["rescheduled"])
            ],
            key=sort_key_name,
        )
        debts = [
            {
                "name": item.get("name") or "Ученик",
                "unpaid_sum": int(item.get("unpaid_sum") or 0),
                "unpaid_count": int(item.get("unpaid_count") or 0),
                "last_unpaid_at": per_student.get(str(item.get("student_id") or item.get("name") or ""), {}).get("last_unpaid_at"),
            }
            for item in (finance.get("students") or [])
            if int(item.get("unpaid_sum") or 0) > 0
        ]
        attendance = []
        for row in per_student.values():
            recent_rate = _ai_attendance_rate(int(row["recent_completed"]), int(row["recent_cancelled"]))
            prev_rate = _ai_attendance_rate(int(row["prev_completed"]), int(row["prev_cancelled"]))
            if recent_rate is None or prev_rate is None:
                continue
            if int(row["recent_completed"]) + int(row["recent_cancelled"]) < 3:
                continue
            if int(row["prev_completed"]) + int(row["prev_cancelled"]) < 3:
                continue
            attendance.append({
                "name": row["name"],
                "recent_rate": recent_rate,
                "prev_rate": prev_rate,
                "delta": recent_rate - prev_rate,
            })
        attendance.sort(key=lambda item: (item["delta"], -item["prev_rate"], item["name"]))

        month_series = sorted(month_counts.items())[-18:]
        snapshot_lines = [
            f"Ученики: {len(students)}",
            f"Уроки всего: {len(lessons)}",
            f"Уроки по месяцам: " + (", ".join(f"{month}={count}" for month, count in month_series) or "нет данных"),
            f"Переносы: " + (", ".join(
                f"{item['name']} — {item['count']} (последний { _ai_format_dt(item['last']) })"
                for item in reschedules[:5]
            ) or "нет"),
            f"Долги: " + (", ".join(
                f"{item['name']} — {item['unpaid_sum']} ₽ ({item['unpaid_count']} урок{'' if item['unpaid_count'] == 1 else 'ов'}, последний { _ai_format_dt(item['last_unpaid_at']) })"
                for item in debts[:5]
            ) or "нет"),
            f"Посещаемость просела: " + (", ".join(
                f"{item['name']} {item['prev_rate']}% → {item['recent_rate']}% ({item['delta']:+d} п.п.)"
                for item in attendance[:5]
            ) or "нет"),
        ]
        return {
            "students_count": len(students),
            "lessons_count": len(lessons),
            "month_counts": month_series,
            "reschedules": reschedules,
            "debts": debts,
            "attendance": attendance,
            "snapshot_text": "\n".join(snapshot_lines),
        }

    def _ai_fallback_summary(snapshot: dict[str, object]) -> str:
        parts: list[str] = []
        reschedules = snapshot.get("reschedules") or []
        debts = snapshot.get("debts") or []
        attendance = snapshot.get("attendance") or []
        if reschedules:
            top = reschedules[0]
            parts.append(f"Чаще всех переносит: {top['name']} — {top['count']}")
        if debts:
            top = debts[0]
            parts.append(f"По долгам в приоритете: {top['name']} — {top['unpaid_sum']} ₽")
        if attendance:
            top = attendance[0]
            parts.append(f"Просела явка: {top['name']} {top['prev_rate']}% → {top['recent_rate']}%")
        if not parts:
            parts.append("Пока мало данных для сводки. Добавь учеников и занятия — здесь появятся сигналы.")
        return "\n".join(f"• {line}" for line in parts[:3])

    async def _build_tutor_ai_summary(tutor_user_id: str, students: list[dict], lessons: list[dict], finance: dict) -> str:
        cache_sig = [
            len(students),
            len(lessons),
            int(finance.get("total_unpaid") or 0),
            int(finance.get("month_earned") or 0),
        ]
        cached = _ai_summary_cache.get(tutor_user_id)
        if cached and time.monotonic() - float(cached[0]) < _AI_SUMMARY_TTL and cached[1:5] == cache_sig:
            return str(cached[5])

        snapshot = _build_tutor_ai_snapshot(students, lessons, finance)
        if _config.AI_ENABLED and _config.DEEPSEEK_API_KEY:
            system = (
                "Ты готовишь короткую ИИ-сводку для главного экрана кабинета репетитора Pingly. "
                "Ответ нужен на русском, без заголовков, 3 коротких пункта максимум. "
                "Используй только данные ниже, ничего не выдумывай. "
                "Если данных мало, скажи об этом прямо."
            )
            user_text = (
                snapshot["snapshot_text"]
                + "\n\nСделай сводку на сегодня: кто чаще переносит, у кого долг, у кого падает посещаемость."
            )
            try:
                reply = await _ai_complete(system, user_text, max_tokens=220, timeout=10.0)
            except Exception:
                reply = None
            if reply and reply.strip():
                summary = reply.strip()
                _ai_summary_cache[tutor_user_id] = [time.monotonic(), *cache_sig, summary]
                return summary
        summary = _ai_fallback_summary(snapshot)
        _ai_summary_cache[tutor_user_id] = [time.monotonic(), *cache_sig, summary]
        return summary

    @app.post("/api/ai/chat")
    async def ai_chat(request: Request, user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        if not (_config.AI_ENABLED and _config.DEEPSEEK_API_KEY):
            raise HTTPException(status_code=503)
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400) from exc
        raw = body.get("messages")
        if not isinstance(raw, list):
            raise HTTPException(status_code=400)
        msgs = []
        for m in raw[-10:]:
            if not isinstance(m, dict):
                continue
            role, content = m.get("role"), (m.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                msgs.append({"role": role, "content": content[:4000]})
        if not msgs or msgs[-1]["role"] != "user":
            raise HTTPException(status_code=400)

        use_analytics = _ai_is_analytics_question(msgs[-1]["content"])
        analytics_block = ""
        if use_analytics:
            try:
                students = await services.students.list_students_by_user(user["id"])
                lessons = await services.repo.list_lessons_for_tutor(user["id"], 1000)
                finance = await services.lessons.finance_overview(user["id"])
                snapshot = _build_tutor_ai_snapshot(students, lessons, finance)
                analytics_block = "\n\nДАННЫЕ КАБИНЕТА:\n" + str(snapshot["snapshot_text"])
            except Exception:
                logging.getLogger("pingly.web").warning("ai chat: failed to build analytics snapshot", exc_info=True)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rec = _ai_usage.get(user["id"])
        if not rec or rec[0] != today:
            rec = [today, 0, 0.0]
        if rec[1] >= _config.AI_DAILY_LIMIT:
            return JSONResponse({"error": "Дневной лимит помощника исчерпан — продолжим завтра."}, status_code=429)
        if time.monotonic() - rec[2] < 2.0:
            return JSONResponse({"error": "Слишком часто — подожди пару секунд."}, status_code=429)
        rec[1] += 1
        rec[2] = time.monotonic()
        _ai_usage[user["id"]] = rec

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                system_prompt = _AI_SYSTEM.format(name=user.get("full_name") or "репетитор")
                if analytics_block:
                    system_prompt += (
                        "\n\nЕсли вопрос про статистику, переносы, долги или посещаемость, "
                        "используй только блок ДАННЫЕ КАБИНЕТА ниже и не выдумывай."
                        + analytics_block
                    )
                resp = await client.post(
                    f"{_config.DEEPSEEK_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {_config.DEEPSEEK_API_KEY}"},
                    json={
                        "model": _config.DEEPSEEK_MODEL,
                        "messages": [{"role": "system", "content": system_prompt}, *msgs],
                        "max_tokens": 1500,
                    },
                )
        except httpx.HTTPError:
            logging.getLogger("pingly.web").warning("ai chat: deepseek request failed", exc_info=True)
            return JSONResponse({"error": "Не получилось связаться с помощником — попробуй ещё раз."}, status_code=502)
        if resp.status_code != 200:
            logging.getLogger("pingly.web").warning("ai chat: deepseek returned %s: %s", resp.status_code, resp.text[:300])
            return JSONResponse({"error": "Помощник сейчас недоступен — попробуй позже."}, status_code=502)
        text = _ai_extract_text(resp.json())
        if not text:
            return JSONResponse({"error": "Пустой ответ — попробуй переформулировать."}, status_code=502)
        return JSONResponse({"reply": text})

    @app.post("/settings/name")
    async def update_name(full_name: str = Form(...), user: dict = Depends(current_user)) -> Response:
        await services.accounts.update_name_by_user_id(user["id"], full_name)
        base = "/tutor/settings" if user["role"] == "tutor" else "/student/settings"
        return RedirectResponse(f"{base}?saved=name", status_code=303)

    @app.post("/settings/timezone")
    async def update_timezone(tz_offset: str = Form(default=""), user: dict = Depends(current_user)) -> Response:
        # normalize_offset clamps anything unexpected back to Москва.
        await services.accounts.set_timezone(user["id"], normalize_offset(tz_offset))
        base = "/tutor/settings" if user["role"] == "tutor" else "/student/settings"
        return RedirectResponse(f"{base}?saved=timezone", status_code=303)

    @app.post("/settings/reminder-hours")
    async def update_reminder_hours(reminder_hours: str = Form(default="2"), user: dict = Depends(current_user)) -> Response:
        _require(user, "tutor")
        try:
            hours = int(reminder_hours)
        except ValueError:
            hours = 2
        await services.accounts.set_reminder_hours(user["id"], hours)
        return RedirectResponse("/tutor/settings?saved=reminder", status_code=303)

    @app.post("/account/delete/send-code")
    async def delete_account_send_code(user: dict = Depends(current_user)) -> Response:
        base = "/tutor/settings" if user["role"] == "tutor" else "/student/settings"
        from urllib.parse import quote
        if not user.get("email"):
            return RedirectResponse(f"{base}?error={quote('У аккаунта нет email — подтверждение кодом недоступно')}", status_code=303)
        if not _rate_ok(f"delcode:{user['id']}", *_RESEND_RATE):
            return RedirectResponse(f"{base}?error={quote('Код уже отправлен. Подожди немного и проверь почту.')}", status_code=303)
        ok, err = await services.web_auth.send_delete_code(user)
        if not ok:
            return RedirectResponse(f"{base}?error={quote(err or 'Не удалось отправить код')}", status_code=303)
        return RedirectResponse(f"{base}?saved=delete_code", status_code=303)

    @app.post("/account/delete")
    async def delete_account(confirm: str = Form(default=""), code: str = Form(default=""), user: dict = Depends(current_user)) -> Response:
        # F12: irreversible self-service deletion. Require typing "удалить" so it
        # can't happen by a stray click. Tutors also lose all their students' data.
        # If the account has an email on file, a fresh 6-digit code sent to it is
        # also required — the typed word alone isn't proof it's really the owner.
        base = "/tutor/settings" if user["role"] == "tutor" else "/student/settings"
        if confirm.strip().lower() != "удалить":
            from urllib.parse import quote
            return RedirectResponse(f"{base}?error={quote('Для удаления введите слово «удалить»')}", status_code=303)
        if user.get("email") and not services.web_auth.check_delete_code(user, code):
            from urllib.parse import quote
            return RedirectResponse(f"{base}?error={quote('Неверный или устаревший код из письма')}", status_code=303)
        if user["role"] == "tutor":
            await services.students.delete_tutor_account(user["id"])
        else:
            await services.accounts.delete_account(user["id"])
        response = RedirectResponse("/?deleted=1", status_code=303)
        response.delete_cookie("pingly_session")
        return response

    @app.get("/student/settings", response_class=HTMLResponse)
    async def student_settings(request: Request, saved: str | None = None, error: str | None = None, user: dict = Depends(current_user)) -> Response:
        _require(user, "student")
        return templates.TemplateResponse("settings.html", _ctx(request, user, "settings", bot_username=_config.BOT_USERNAME, saved=saved, error=error, tz_choices=TZ_CHOICES))

    # ---------------- Admin panel (users.is_admin only) ----------------
    @app.get("/admin", response_class=HTMLResponse)
    async def admin_home(request: Request, user: dict = Depends(current_user)) -> Response:
        _require_admin(user)
        stats = await services.admin.overview()
        return templates.TemplateResponse(
            "admin/overview.html", _ctx(request, user, "admin", stats=stats),
        )

    @app.get("/admin/analytics", response_class=HTMLResponse)
    async def admin_analytics(
        request: Request, days: int = 30, user: dict = Depends(current_user),
    ) -> Response:
        _require_admin(user)
        stats = await services.webstats.dashboard(days)
        return templates.TemplateResponse(
            "admin/analytics.html", _ctx(request, user, "admin", stats=stats),
        )

    @app.get("/admin/tutors", response_class=HTMLResponse)
    async def admin_tutors(request: Request, saved: str | None = None, user: dict = Depends(current_user)) -> Response:
        _require_admin(user)
        tutors = await services.admin.list_tutors()
        return templates.TemplateResponse(
            "admin/tutors.html", _ctx(request, user, "admin", tutors=tutors, saved=saved),
        )

    @app.post("/admin/tutors/{tutor_id}/subscription")
    async def admin_set_subscription(
        request: Request,
        tutor_id: str,
        action: str = Form(...),
        plan: str = Form("max"),
        days: int = Form(30),
        user: dict = Depends(current_user),
    ) -> Response:
        _require_admin(user)
        target = await services.admin.get_tutor(tutor_id)
        if not target:
            raise HTTPException(status_code=404)
        if action == "grant":
            await services.admin.grant_subscription(tutor_id, plan, max(1, int(days)))
        elif action == "set_plan":
            await services.admin.set_plan(tutor_id, plan)
        elif action == "extend_trial":
            await services.admin.extend_trial(tutor_id, max(1, int(days)))
        elif action == "revoke":
            await services.admin.revoke_subscription(tutor_id)
            logging.getLogger("pingly.admin").warning(
                "REVOKE subscription by=%s target=%s", user.get("id"), tutor_id,
            )
        dest = str(request.query_params.get("from") or "").strip()
        if dest == "detail":
            return RedirectResponse(f"/admin/tutors/{tutor_id}?saved=1", status_code=303)
        return RedirectResponse("/admin/tutors?saved=1", status_code=303)

    @app.get("/admin/tutors/{tutor_id}", response_class=HTMLResponse)
    async def admin_tutor_detail(request: Request, tutor_id: str, saved: str | None = None, user: dict = Depends(current_user)) -> Response:
        _require_admin(user)
        detail = await services.admin.tutor_detail(tutor_id)
        if not detail:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            "admin/tutor_detail.html", _ctx(request, user, "admin", d=detail, saved=saved),
        )

    @app.post("/admin/tutors/{tutor_id}/block")
    async def admin_block_tutor(
        tutor_id: str,
        blocked: str = Form(...),
        user: dict = Depends(current_user),
    ) -> Response:
        _require_admin(user)
        target = await services.admin.get_tutor(tutor_id)
        if not target:
            raise HTTPException(status_code=404)
        if tutor_id == user.get("id"):
            # Guard: an admin can't lock themselves out of the panel.
            return RedirectResponse(f"/admin/tutors/{tutor_id}?saved=self", status_code=303)
        want_block = blocked == "1"
        await services.admin.set_blocked(tutor_id, want_block)
        logging.getLogger("pingly.admin").warning(
            "%s by=%s target=%s", "BLOCK" if want_block else "UNBLOCK", user.get("id"), tutor_id,
        )
        return RedirectResponse(f"/admin/tutors/{tutor_id}?saved=1", status_code=303)

    @app.get("/admin/broadcast", response_class=HTMLResponse)
    async def admin_broadcast_form(request: Request, result: str | None = None, user: dict = Depends(current_user)) -> Response:
        _require_admin(user)
        counts = await services.admin.broadcast_counts()
        return templates.TemplateResponse(
            "admin/broadcast.html",
            _ctx(request, user, "admin", counts=counts, target_count=counts["tutors"], result=result),
        )

    @app.post("/admin/broadcast")
    async def admin_broadcast_send(message: str = Form(...), audience: str = Form("tutors"), user: dict = Depends(current_user)) -> Response:
        _require_admin(user)
        text = message.strip()
        if not text:
            return RedirectResponse("/admin/broadcast?result=empty", status_code=303)
        targets = await services.admin.broadcast_targets(audience)
        # S12: audit trail — who blasted whom, when, and what (message truncated).
        # Goes to journalctl so a hijacked admin session leaves a durable record.
        logging.getLogger("pingly.admin").warning(
            "BROADCAST by user=%s tg=@%s audience=%s recipients=%d text=%r",
            user.get("id"), user.get("tg_username") or "-", audience, len(targets), text[:120],
        )
        stats = await _broadcast_telegram(targets, text)
        logging.getLogger("pingly.admin").warning(
            "BROADCAST done by user=%s sent=%s failed=%s", user.get("id"), stats["sent"], stats["failed"],
        )
        return RedirectResponse(
            f"/admin/broadcast?result={stats['sent']}-{stats['failed']}", status_code=303,
        )
