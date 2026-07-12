"""Tiny DeepSeek client (OpenAI-compatible chat completions: POST
{base}/chat/completions, header Authorization: Bearer <key>). Shared by the web
AI assistant and bot-side text analysis. Returns None on any failure — callers
must have a non-AI fallback."""
from __future__ import annotations

import logging

import httpx

import config

log = logging.getLogger("pingly.ai")


def extract_text(data: dict) -> str:
    """Pull the final answer out of an OpenAI-style chat completion. The
    deepseek-reasoner model keeps the chain-of-thought in `reasoning_content`
    and the answer in `content` — we only want `content`."""
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    return (msg.get("content") or "").strip()


async def complete(system: str, user_text: str, max_tokens: int = 400, timeout: float = 15.0) -> str | None:
    if not (config.AI_ENABLED and config.DEEPSEEK_API_KEY):
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{config.DEEPSEEK_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"},
                json={
                    "model": config.DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_text},
                    ],
                    "max_tokens": max_tokens,
                },
            )
    except httpx.HTTPError:
        log.warning("deepseek request failed", exc_info=True)
        return None
    if resp.status_code != 200:
        log.warning("deepseek returned %s: %s", resp.status_code, resp.text[:200])
        return None
    return extract_text(resp.json()) or None
