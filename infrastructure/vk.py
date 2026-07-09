"""Stateless VK message sender — the VK mirror of web.app._send_telegram.

Lets any process (web cabinet, the Telegram-bot handlers, the scheduler) push a
message to a VK user without holding the long-poll VkBot instance from vk_bot.py.
Fire-and-forget over a short-lived aiohttp session. No-op (returns False) unless a
community token is configured, so call sites don't need to guard on VK_ENABLED.
"""
from __future__ import annotations

import json
import random

import aiohttp

import config

_SEND_URL = "https://api.vk.com/method/messages.send"
API_VERSION = "5.199"


async def send_message(peer_id: int, text: str, keyboard: dict | None = None) -> bool:
    """Send one VK message. Returns True on success, False on any failure or when
    VK isn't configured. Never raises — safe as a fire-and-forget notification."""
    if not config.VK_TOKEN:
        return False
    params = {
        "peer_id": peer_id,
        "message": text,
        "random_id": random.randint(1, 2_000_000_000),
        "access_token": config.VK_TOKEN,
        "v": API_VERSION,
    }
    if keyboard:
        params["keyboard"] = json.dumps(keyboard)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(_SEND_URL, data=params) as resp:
                data = await resp.json()
        return "error" not in data
    except Exception:
        return False
