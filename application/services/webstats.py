from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from application.repositories import PinglyRepository

# Что вообще принимаем. Эндпоинт публичный: без закрытого списка любой зальёт
# в базу произвольные имена событий и испортит отчёты.
PAGEVIEW = "pageview"
ALLOWED_EVENTS: frozenset[str] = frozenset({
    PAGEVIEW,
    "signup",
    "student_added",
    "schedule_created",
    "register_submitted",
    "subscribe_click",
    "booking_submitted",   # заявка с публичной страницы /u/<slug>
    "cta_click",           # клики по кнопкам лендинга
})

# Всё, что похоже на робота. Cloudflare считает их посетителями — из-за этого
# в дашборде CF 1,47к «уникальных», и цифра ничего не значит. Здесь их режем,
# иначе своя аналитика будет врать ровно так же.
_BOT_RE = re.compile(
    r"bot|crawler|spider|crawling|slurp|bingpreview|"
    r"headless|phantomjs|puppeteer|playwright|curl|wget|python-requests|httpx|"
    r"monitoring|uptime|pingdom|semrush|ahrefs|mj12|dotbot|petalbot|facebookexternalhit",
    re.I,
)
_MOBILE_RE = re.compile(r"iphone|ipod|android.*mobile|windows phone|blackberry", re.I)
_TABLET_RE = re.compile(r"ipad|android(?!.*mobile)|tablet", re.I)

_UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign")


def is_bot(user_agent: str) -> bool:
    ua = (user_agent or "").strip()
    # Пустой User-Agent — почти всегда скрипт: браузеры его всегда шлют.
    return not ua or bool(_BOT_RE.search(ua))


def device_of(user_agent: str) -> str:
    ua = user_agent or ""
    if _MOBILE_RE.search(ua):
        return "mobile"
    if _TABLET_RE.search(ua):
        return "tablet"
    return "desktop"


def _clean_path(raw: str) -> str:
    """Только путь, без query и фрагмента. В query ходят почты (/verify?email=),
    токены и ?goal= — в аналитике им не место, а хранить их значило бы копить
    персданные без нужды."""
    path = urlsplit((raw or "/").strip()).path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return path[:300]


def _referrer_host(raw: str) -> str | None:
    """Из реферера берём только хост. Полный URL чужого сайта — это чужие
    query-параметры, за которые мы не отвечаем."""
    host = urlsplit((raw or "").strip()).netloc.lower()
    if not host or host == "localhost" or host.split(":")[0].endswith("pingly-app.ru"):
        return None  # внутренний переход — не источник
    return host[:160] or None


def _short(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] or None


def _token(value: Any) -> str | None:
    """Анонимный идентификатор из браузера. Пропускаем только то, что сами же
    и генерируем — короткая строка из безопасных символов."""
    text = str(value or "").strip()
    if not text or len(text) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        return None
    return text


class WebStatsService:
    """Собственная веб-аналитика: события пишутся в свою базу и никуда не
    уходят. Заменяет внешний счётчик там, где нужны честные цифры, и снимает
    вопросы о передаче данных третьим лицам."""

    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def track(
        self,
        *,
        event: str,
        path: str,
        visitor_id: str,
        session_id: str,
        referrer: str = "",
        query: dict[str, str] | None = None,
        user_agent: str = "",
        user_id: str | None = None,
        props: dict[str, Any] | None = None,
    ) -> bool:
        """Записать событие. Возвращает False, если событие отброшено —
        вызывающий всё равно отвечает 204, чтобы не подсказывать ботам,
        по каким признакам их отсеивают."""
        event = (event or "").strip()
        if event not in ALLOWED_EVENTS:
            return False
        if is_bot(user_agent):
            return False

        visitor = _token(visitor_id)
        session = _token(session_id)
        if not visitor or not session:
            return False

        q = query or {}
        row: dict[str, Any] = {
            "visitor_id": visitor,
            "session_id": session,
            "event": event,
            "path": _clean_path(path),
            "referrer_host": _referrer_host(referrer),
            "device": device_of(user_agent),
            "user_id": user_id,
            "props": props if isinstance(props, dict) else {},
        }
        for key in _UTM_KEYS:
            row[key] = _short(q.get(key), 120)

        await self.repo.insert_web_event(row)
        return True

    async def dashboard(self, days: int = 30) -> dict[str, Any]:
        days = max(1, min(int(days or 30), 365))
        summary = await self.repo.web_stats("web_stats_summary", {"p_days": days})
        daily = await self.repo.web_stats("web_stats_daily", {"p_days": days})
        paths = await self.repo.web_stats("web_stats_paths", {"p_days": days, "p_lim": 15})
        sources = await self.repo.web_stats("web_stats_sources", {"p_days": days, "p_lim": 15})
        goals = await self.repo.web_stats("web_stats_goals", {"p_days": days})
        devices = await self.repo.web_stats("web_stats_devices", {"p_days": days})

        head = summary[0] if summary else {}
        visitors = int(head.get("visitors") or 0)
        goal_by_name = {str(g.get("event")): int(g.get("visitors") or 0) for g in goals}

        # Воронка: сколько посетителей дошло до каждого шага. Считаем по
        # посетителям, а не по событиям — иначе один человек, добавивший трёх
        # учеников, выглядит как три конверсии.
        funnel = [
            {"label": "Посетители", "value": visitors},
            {"label": "Начали регистрацию", "value": goal_by_name.get("register_submitted", 0)},
            {"label": "Зарегистрировались", "value": goal_by_name.get("signup", 0)},
            {"label": "Добавили ученика", "value": goal_by_name.get("student_added", 0)},
            {"label": "Создали расписание", "value": goal_by_name.get("schedule_created", 0)},
        ]
        for step in funnel:
            step["percent"] = round(step["value"] * 100 / visitors, 1) if visitors else 0.0

        return {
            "days": days,
            "visitors": visitors,
            "sessions": int(head.get("sessions") or 0),
            "pageviews": int(head.get("pageviews") or 0),
            "daily": daily,
            "paths": paths,
            "sources": sources,
            "goals": goals,
            "devices": devices,
            "funnel": funnel,
        }
