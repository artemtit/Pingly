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
            # Defense-in-depth: if the callback reports an amount, it must match the
            # price we charge. The amount is server-set at creation, so a mismatch
            # means a tampered/foreign callback — refuse to grant entitlement.
            if not self._amount_ok(body):
                return False
            if not user_id:
                # Nothing to activate; acknowledge so Platega stops retrying.
                return True
            # Authoritative idempotency: ensure a ledger row exists, then perform an
            # atomic "pending -> confirmed" transition. activate_subscription runs
            # ONLY when this call actually made the transition, so retried/duplicate
            # CONFIRMED callbacks can never stack extra 30-day extensions.
            try:
                await self.repo.upsert_subscription_payment_pending(
                    user_id, transaction_id, config.SUBSCRIPTION_PRICE_RUB
                )
                transitioned = await self.repo.confirm_subscription_payment_once(transaction_id)
            except Exception:
                # If the ledger is unreachable we cannot guarantee single activation,
                # so we must not activate. Returning False makes Platega retry later.
                return False
            if transitioned:
                activate_uid = transitioned.get("user_id") or user_id
                await self.repo.activate_subscription(activate_uid, SUBSCRIPTION_DAYS)
        elif status in ("CANCELED", "CHARGEBACKED"):
            try:
                await self.repo.mark_subscription_payment(transaction_id, "canceled")
            except Exception:
                pass
        return True

    @staticmethod
    def _amount_ok(body: dict) -> bool:
        """True if the callback's amount equals the expected price, or if no amount
        is present (older callbacks omit it; the amount is server-set at creation)."""
        raw = body.get("amount")
        if raw is None:
            details = body.get("paymentDetails")
            if isinstance(details, dict):
                raw = details.get("amount")
        if raw is None:
            return True
        try:
            return abs(float(raw) - float(config.SUBSCRIPTION_PRICE_RUB)) < 0.01
        except (TypeError, ValueError):
            return False
