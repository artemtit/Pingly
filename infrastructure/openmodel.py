"""Tiny OpenModel client (Anthropic Messages format: POST {base}/v1/messages,
header x-api-key). Shared by the web AI assistant and bot-side text analysis.
Returns None on any failure — callers must have a non-AI fallback."""
from __future__ import annotations

import logging

import httpx

import config

log = logging.getLogger("pingly.ai")


async def complete(system: str, user_text: str, max_tokens: int = 400, timeout: float = 15.0) -> str | None:
    if not (config.AI_ENABLED and config.OPENMODEL_API_KEY):
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{config.OPENMODEL_BASE_URL}/v1/messages",
                headers={"x-api-key": config.OPENMODEL_API_KEY, "anthropic-version": "2023-06-01"},
                json={
                    "model": config.OPENMODEL_MODEL,
                    "system": system,
                    "messages": [{"role": "user", "content": user_text}],
                    "max_tokens": max_tokens,
                },
            )
    except httpx.HTTPError:
        log.warning("openmodel request failed", exc_info=True)
        return None
    if resp.status_code != 200:
        log.warning("openmodel returned %s: %s", resp.status_code, resp.text[:200])
        return None
    # The model may emit thinking blocks first — keep only text blocks.
    text = "\n".join(
        b.get("text", "") for b in resp.json().get("content", []) if isinstance(b, dict) and b.get("type") == "text"
    ).strip()
    return text or None
