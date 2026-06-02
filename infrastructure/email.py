"""Transactional email via the Resend HTTP API (https://resend.com/docs)."""
from __future__ import annotations

import httpx

import config


class EmailError(Exception):
    pass


async def send_email(to: str, subject: str, html: str) -> None:
    """Send one email. Raises EmailError if not configured or the API rejects it."""
    if not config.RESEND_API_KEY:
        raise EmailError("Resend API key is not configured")
    payload = {
        "from": config.RESEND_FROM,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    headers = {
        "Authorization": f"Bearer {config.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post("https://api.resend.com/emails", json=payload, headers=headers)
    if resp.status_code >= 400:
        raise EmailError(f"Resend {resp.status_code}: {resp.text}")


def verification_html(code: str) -> str:
    """Branded HTML body for the registration confirmation code."""
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:440px;'
        'margin:0 auto;padding:24px;color:#111827;">'
        '<h2 style="margin:0 0 8px;">Подтверждение регистрации в Pingly</h2>'
        '<p style="color:#6B7280;margin:0 0 20px;">Введите этот код, чтобы завершить регистрацию:</p>'
        f'<div style="font-size:34px;font-weight:800;letter-spacing:8px;background:#FFF7ED;'
        f'border:1px solid #FED7AA;border-radius:12px;padding:16px;text-align:center;color:#C2410C;">{code}</div>'
        '<p style="color:#9CA3AF;font-size:13px;margin:20px 0 0;">Код действует 15 минут. '
        'Если вы не регистрировались в Pingly — просто проигнорируйте это письмо.</p>'
        '</div>'
    )
