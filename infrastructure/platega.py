"""Thin async client for the Platega payment API (https://docs.platega.io)."""
from __future__ import annotations

import httpx

import config


class PlategaError(Exception):
    pass


def _headers() -> dict[str, str]:
    return {
        "X-MerchantId": config.PLATEGA_MERCHANT_ID,
        "X-Secret": config.PLATEGA_SECRET,
        "Content-Type": "application/json",
    }


async def create_payment(
    amount: float,
    description: str,
    return_url: str,
    failed_url: str,
    payload: str,
    currency: str = "RUB",
    payment_method: int | None = None,
) -> dict:
    """Create a transaction. Returns dict with transactionId, redirect, status.

    POST {API}/transaction/process — see docs "Создание ссылки на оплату".
    """
    if not config.PLATEGA_MERCHANT_ID or not config.PLATEGA_SECRET:
        raise PlategaError("Platega credentials are not configured")
    body = {
        "paymentMethod": payment_method or config.PLATEGA_PAYMENT_METHOD,
        "paymentDetails": {"amount": amount, "currency": currency},
        "description": description,
        "return": return_url,
        "failedUrl": failed_url,
        "payload": payload,
    }
    url = f"{config.PLATEGA_API_URL.rstrip('/')}/transaction/process"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json=body, headers=_headers())
    if resp.status_code >= 400:
        raise PlategaError(f"Platega {resp.status_code}: {resp.text}")
    return resp.json()


def verify_webhook_headers(merchant_id: str | None, secret: str | None) -> bool:
    """Platega authenticates the callback with the same X-MerchantId/X-Secret."""
    return bool(
        merchant_id and secret
        and merchant_id == config.PLATEGA_MERCHANT_ID
        and secret == config.PLATEGA_SECRET
    )
