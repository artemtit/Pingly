"""Founder ops alerts — pings the founder on key business events (new registration,
payment) through a *separate* Telegram bot, so alerts don't mix with user traffic in
the main service bot.

Fire-and-forget by design: a failed alert must never break registration or a payment
webhook. Everything is best-effort and swallows its own errors. Disabled automatically
when the alert bot token is empty.

The founder must have opened a chat with the alert bot once (press Start), otherwise
Telegram refuses to deliver the first message ("bots can't initiate conversations").
"""
from __future__ import annotations

import asyncio
import logging

import httpx

import config

log = logging.getLogger("pingly.alerts")


def enabled() -> bool:
    return bool(config.FOUNDER_ALERT_BOT_TOKEN and config.FOUNDER_ALERT_CHAT_ID)


async def send(text: str) -> None:
    """Deliver one alert. Awaitable, but always safe — never raises."""
    if not enabled():
        return
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{config.FOUNDER_ALERT_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": config.FOUNDER_ALERT_CHAT_ID,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
        if resp.status_code != 200:
            log.warning("founder alert failed %s: %s", resp.status_code, resp.text[:200])
    except httpx.HTTPError:
        log.warning("founder alert request failed", exc_info=True)


def notify(text: str) -> None:
    """Fire-and-forget from anywhere. Inside a running event loop it schedules the
    send as a background task and returns immediately (never delays the response);
    with no loop it runs synchronously. Silently no-ops if disabled."""
    if not enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        # Keep a reference so the task isn't garbage-collected mid-flight.
        task = loop.create_task(send(text))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
    else:
        try:
            asyncio.run(send(text))
        except Exception:
            log.warning("founder alert (sync) failed", exc_info=True)


_bg_tasks: set[asyncio.Task] = set()
