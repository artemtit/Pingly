from __future__ import annotations

import contextvars
from datetime import timedelta, timezone

# F6: per-tutor timezone as a fixed UTC offset in minutes. Russia has no DST, so a
# fixed offset is exact. 180 = Москва (UTC+3) — the historical hardcoded default.
DEFAULT_TZ_OFFSET = 180

# Russian time zones offered in Settings (label, offset minutes). Ordered west→east.
TZ_CHOICES: list[tuple[int, str]] = [
    (120, "Калининград (UTC+2)"),
    (180, "Москва (UTC+3)"),
    (240, "Самара (UTC+4)"),
    (300, "Екатеринбург (UTC+5)"),
    (360, "Омск (UTC+6)"),
    (420, "Красноярск (UTC+7)"),
    (480, "Иркутск (UTC+8)"),
    (540, "Якутск (UTC+9)"),
    (600, "Владивосток (UTC+10)"),
    (660, "Магадан (UTC+11)"),
    (720, "Камчатка (UTC+12)"),
]

_VALID = {m for m, _ in TZ_CHOICES}


def tz_from_offset(minutes: int | None) -> timezone:
    """Build a tzinfo from an offset in minutes, falling back to Москва."""
    if minutes is None:
        minutes = DEFAULT_TZ_OFFSET
    return timezone(timedelta(minutes=int(minutes)))


def tutor_offset(user: dict | None) -> int:
    """Read a user's stored offset, defaulting to Москва when unset."""
    if not user:
        return DEFAULT_TZ_OFFSET
    return int(user.get("tz_offset_minutes") or DEFAULT_TZ_OFFSET)


def normalize_offset(minutes: int | None) -> int:
    """Clamp an incoming offset to a known Russian zone (guards form tampering)."""
    try:
        value = int(minutes)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_TZ_OFFSET
    return value if value in _VALID else DEFAULT_TZ_OFFSET


# Per-request "current viewer" offset for web display. Set once in the auth
# dependency; the calendar builder and Jinja time filters read it so every page
# shows times in the logged-in tutor's zone. Defaults to Москва off-request.
_current_offset: contextvars.ContextVar[int] = contextvars.ContextVar(
    "pingly_tz_offset", default=DEFAULT_TZ_OFFSET,
)


def set_current_offset(minutes: int | None) -> None:
    _current_offset.set(int(minutes or DEFAULT_TZ_OFFSET))


def current_offset() -> int:
    return _current_offset.get()


def current_tz() -> timezone:
    return tz_from_offset(_current_offset.get())
