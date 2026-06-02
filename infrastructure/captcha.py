"""Cloudflare Turnstile CAPTCHA verification (https://developers.cloudflare.com/turnstile)."""
from __future__ import annotations

import httpx

import config

_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(token: str | None, remote_ip: str | None = None) -> bool:
    """Validate a Turnstile token server-side. Returns True if the challenge passed.
    If no secret key is configured the check is skipped (returns True) so the flag
    can be flipped on only once keys are in place."""
    if not config.TURNSTILE_SECRET_KEY:
        return True
    if not token:
        return False
    data = {"secret": config.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(_VERIFY_URL, data=data)
        return bool(resp.json().get("success"))
    except Exception:
        return False
