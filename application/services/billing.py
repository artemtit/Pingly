from __future__ import annotations

import config
from application.repositories import PinglyRepository
from infrastructure import platega

SUBSCRIPTION_DAYS = 30


class BillingService:
    """Platega subscription payments. One-time charge that grants 30 days; the
    Platega API has no card-on-file rebill, so renewal is prompted via reminders."""

    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def start_subscription(self, user: dict, base_url: str) -> tuple[str | None, str | None]:
        """Create a Platega payment and return (redirect_url, error)."""
        base = base_url.rstrip("/")
        try:
            result = await platega.create_payment(
                amount=float(config.SUBSCRIPTION_PRICE_RUB),
                description="Подписка Pingly Pro (1 месяц)",
                return_url=f"{base}/tutor/settings?paid=1",
                failed_url=f"{base}/tutor/settings?paid=0",
                payload=user["id"],
            )
        except platega.PlategaError as exc:
            return None, str(exc)
        transaction_id = str(result.get("transactionId") or "")
        redirect = result.get("redirect") or result.get("return")
        if not transaction_id or not redirect:
            return None, "Platega не вернула ссылку на оплату"
        # Ledger write is best-effort: the payment already exists at Platega and
        # the webhook can still activate via payload=user_id, so a ledger hiccup
        # must not block the user from reaching the payment page.
        try:
            await self.repo.create_subscription_payment(user["id"], transaction_id, config.SUBSCRIPTION_PRICE_RUB)
        except Exception:
            pass
        return redirect, None

    async def handle_webhook(self, merchant_id: str | None, secret: str | None, body: dict) -> bool:
        """Process a Platega callback. Returns True if accepted (always answer 200
        so Platega doesn't retry a request we've already understood)."""
        if not platega.verify_webhook_headers(merchant_id, secret):
            return False
        transaction_id = str(body.get("id") or "")
        status = str(body.get("status") or "")
        if not transaction_id:
            return False
        try:
            payment = await self.repo.get_subscription_payment_by_transaction(transaction_id)
        except Exception:
            payment = None
        user_id = (payment or {}).get("user_id") or body.get("payload")
        if status == "CONFIRMED":
            # Idempotent via the ledger: only activate once per transaction.
            if payment and payment.get("status") == "confirmed":
                return True
            try:
                await self.repo.mark_subscription_payment(transaction_id, "confirmed", confirmed=True)
            except Exception:
                pass
            if user_id:
                await self.repo.activate_subscription(user_id, SUBSCRIPTION_DAYS)
        elif status in ("CANCELED", "CHARGEBACKED"):
            try:
                await self.repo.mark_subscription_payment(transaction_id, "canceled")
            except Exception:
                pass
        return True
