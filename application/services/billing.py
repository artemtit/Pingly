from __future__ import annotations

import config
from application.repositories import PinglyRepository
from infrastructure import platega

SUBSCRIPTION_DAYS = 30
SUBSCRIPTION_DAYS_YEAR = 365


def _normalize_plan(plan: str | None) -> str:
    p = (plan or "max").lower()
    return p if p in ("pro", "max") else "max"


def _normalize_period(period: str | None) -> str:
    p = (period or "month").lower()
    return p if p in ("month", "year") else "month"


def _days_for_period(period: str) -> int:
    return SUBSCRIPTION_DAYS_YEAR if period == "year" else SUBSCRIPTION_DAYS


def _price_for_plan(plan: str, period: str = "month") -> int:
    """Price for the chosen tier + billing period. With tiers off (the current
    single-tariff reality) the monthly price is the one flat price and the yearly
    price is the flat yearly price — independent of the tier."""
    if period == "year":
        return config.SUBSCRIPTION_PRICE_YEAR_RUB
    if not config.PLANS_ENABLED:
        return config.SUBSCRIPTION_PRICE_RUB
    return config.PRICE_PRO_RUB if plan == "pro" else config.PRICE_MAX_RUB


class BillingService:
    """Platega subscription payments. One-time charge that grants 30 days; the
    Platega API has no card-on-file rebill, so renewal is prompted via reminders."""

    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def start_subscription(self, user: dict, base_url: str, plan: str = "max", period: str = "month") -> tuple[str | None, str | None]:
        """Create a Platega payment for the chosen tier + period and return (redirect_url, error)."""
        base = base_url.rstrip("/")
        plan = _normalize_plan(plan)
        period = _normalize_period(period)
        price = _price_for_plan(plan, period)
        tier_label = "Max" if plan == "max" else "Pro"
        period_label = "1 год" if period == "year" else "1 мес"
        # Stamp the buyer's identity into the description so a payment can be traced
        # back to an account from the Platega dashboard (name · contact · short id).
        ident = (user.get("email") or "").strip()
        if not ident and user.get("tg_username"):
            ident = "@" + str(user["tg_username"]).lstrip("@")
        who = " · ".join(p for p in (
            (user.get("full_name") or "").strip(),
            ident,
            f"#{str(user['id'])[:8].upper()}",
        ) if p)
        try:
            result = await platega.create_payment(
                amount=float(price),
                description=f"Pingly {tier_label}, {period_label} · {who}"[:180],
                return_url=f"{base}/tutor/settings?paid=1",
                failed_url=f"{base}/tutor/settings?paid=0",
                # The plan + period ride along in the payload so the webhook can grant
                # the right tier and duration even if the ledger write below didn't land.
                payload=f"{user['id']}:{plan}:{period}",
            )
        except platega.PlategaError as exc:
            return None, str(exc)
        transaction_id = str(result.get("transactionId") or "")
        redirect = result.get("redirect") or result.get("return")
        if not transaction_id or not redirect:
            return None, "Platega не вернула ссылку на оплату"
        # The ledger row is now REQUIRED for the webhook to activate (it no longer
        # fabricates rows for unknown transaction ids), so make this write reliable
        # with a couple of retries. We still don't block reaching the payment page
        # on a hard failure — Platega retries the webhook, and a tutor who paid but
        # didn't activate can be granted manually in the admin panel.
        for _attempt in range(3):
            try:
                await self.repo.create_subscription_payment(user["id"], transaction_id, price)
                break
            except Exception:
                continue
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
        # Payload is "<user_id>:<plan>:<period>" (plan/period optional for older
        # payments — they default to a monthly Max charge).
        raw_payload = str(body.get("payload") or "")
        parts = raw_payload.split(":")
        payload_uid = parts[0] if parts else raw_payload
        plan = _normalize_plan(parts[1] if len(parts) > 1 else "max")
        period = _normalize_period(parts[2] if len(parts) > 2 else "month")
        user_id = (payment or {}).get("user_id") or payload_uid or None
        # Expected charge: the ledger amount if we have it, else the tier+period price.
        expected_rub = (payment or {}).get("amount_rub")
        if expected_rub is None:
            expected_rub = _price_for_plan(plan, period)
        if status == "CONFIRMED":
            # Defense-in-depth: if the callback reports an amount, it must match the
            # price we charge. The amount is server-set at creation, so a mismatch
            # means a tampered/foreign callback — refuse to grant entitlement.
            if not self._amount_ok(body, expected_rub):
                return False
            if not payment:
                # We never initiated this transaction. A real payment always has a
                # ledger row from start_subscription; a CONFIRMED callback for an
                # unknown id is a forged/foreign request (possible if the webhook
                # secret leaks) — never fabricate a row and grant a subscription.
                # Ack so Platega stops retrying, but do NOT activate.
                return True
            if not user_id:
                # Nothing to activate; acknowledge so Platega stops retrying.
                return True
            # Authoritative idempotency: an atomic "pending -> confirmed" transition
            # on the EXISTING ledger row. activate_subscription runs ONLY when this
            # call actually made the transition, so retried/duplicate CONFIRMED
            # callbacks can never stack extra subscription extensions.
            try:
                transitioned = await self.repo.confirm_subscription_payment_once(transaction_id)
            except Exception:
                # If the ledger is unreachable we cannot guarantee single activation,
                # so we must not activate. Returning False makes Platega retry later.
                return False
            if transitioned:
                activate_uid = transitioned.get("user_id") or user_id
                await self.repo.activate_subscription(
                    activate_uid, _days_for_period(period), plan if config.PLANS_ENABLED else None
                )
                # Pay out the referral bonus on the referred tutor's first real
                # payment. Idempotent in the repo, so renewals never re-trigger it.
                try:
                    await self.repo.grant_referral_reward(activate_uid)
                except Exception:
                    pass
        elif status in ("CANCELED", "CHARGEBACKED"):
            try:
                await self.repo.mark_subscription_payment(transaction_id, "canceled")
            except Exception:
                pass
        return True

    @staticmethod
    def _amount_ok(body: dict, expected_rub: float) -> bool:
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
            return abs(float(raw) - float(expected_rub)) < 0.01
        except (TypeError, ValueError):
            return False
