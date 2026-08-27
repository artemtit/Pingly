"""Slug-хелперы для публичной страницы репетитора (/u/<slug>).

Живут в domain, потому что нужны с обеих сторон: application (репетитор
меняет адрес вручную в кабинете) и infrastructure (адрес генерится из имени
при регистрации). Чистые функции, без БД и фреймворков.
"""
from __future__ import annotations

import re

SLUG_MIN_LEN = 3
SLUG_MAX_LEN = 30

# Практическая транслитерация (не ГОСТ): цель — читаемый адрес вида
# «Иван Петров» → ivan-petrov, а не формальная обратимость.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # Украинский/белорусский — встречаются в именах.
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g", "ў": "u",
}

_NOT_ALLOWED = re.compile(r"[^a-z0-9-]+")
_MULTI_DASH = re.compile(r"-{2,}")
_SLUG_OK = re.compile(r"^[a-z0-9-]+$")


def translit(raw: str) -> str:
    """Кириллица → латиница. Всё остальное пропускается как есть.

    Регистр не важен: normalize_slug всё равно приводит к нижнему.
    """
    out: list[str] = []
    for ch in (raw or ""):
        low = ch.lower()
        out.append(_TRANSLIT[low] if low in _TRANSLIT else ch)
    return "".join(out)


def normalize_slug(raw: str) -> str:
    """Привести ввод к каноничному виду [a-z0-9-] БЕЗ обрезки по длине.

    Обрезать молча нельзя: если репетитор вручную ввёл 40 символов, он должен
    получить внятную ошибку, а не молча другой адрес. Длину проверяет вызывающий
    через slug_error().
    """
    slug = translit((raw or "").strip()).lower()
    slug = slug.replace(" ", "-").replace("_", "-")
    slug = _NOT_ALLOWED.sub("", slug)
    slug = _MULTI_DASH.sub("-", slug)
    return slug.strip("-")


def slug_error(slug: str) -> str | None:
    """Сообщение об ошибке для уже нормализованного slug, либо None."""
    if len(slug) < SLUG_MIN_LEN or len(slug) > SLUG_MAX_LEN:
        return f"Адрес страницы — от {SLUG_MIN_LEN} до {SLUG_MAX_LEN} символов (латиница, цифры, дефис)"
    if not _SLUG_OK.match(slug):
        return "Адрес страницы — только латиница, цифры и дефис"
    return None


def slug_from_name(full_name: str) -> str:
    """Базовый адрес из имени: «Иван Петров» → ivan-petrov.

    Возвращает "" если из имени ничего пригодного не вышло (пустое имя, одни
    эмодзи, слишком короткий результат) — вызывающий подставляет случайный.
    Уникальность здесь НЕ проверяется, это забота репозитория.
    """
    base = normalize_slug(full_name)[:SLUG_MAX_LEN].strip("-")
    return base if len(base) >= SLUG_MIN_LEN else ""
