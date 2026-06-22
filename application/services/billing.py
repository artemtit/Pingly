from __future__ import annotations

import config
from application.repositories import PinglyRepository
from infrastructure import platega

SUBSCRIPTION_DAYS = 30


def _normalize_plan(plan: str | None) -> str:
    p = (plan or "max").lower()
    return p if p in ("pro", "max") else "max"


def _price_for_plan(plan: str) -> int:
    """Price for the chosen tier. With tiers off, every charge is the single price."""
    if not config.PLANS_ENABLED:
        return config.SUBSCRIPTION_PRICE_RUB
    return config.PRICE_PRO_RUB if plan == "pro" else config.PRICE_MAX_RUB


class BillingService:
    """Platega subscription payments. One-time charge that grants 30 days; the
    Platega API has no card-on-file rebill, so renewal is prompted via reminders."""

    def __init__(self, repo: PinglyRepository) -> None:
        self.repo = repo

    async def start_subscription(self, user: dict, base_url: str, plan: str = "max") -> tuple[str | None, str | None]:
        """Create a Platega payment for the chosen tier and return (redirect_url, error)."""
        base = base_url.rstrip("/")
        plan = _normalize_plan(plan)
        price = _price_for_plan(plan)
        tier_label = "Max" if plan == "max" else "Pro"
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
                description=f"Pingly {tier_label}, 1 мес · {who}"[:180],
                return_url=f"{base}/tutor/settings?paid=1",
                failed_url=f"{base}/tutor/settings?paid=0",
                # The plan rides along in the payload so the webhook can grant the
                # right tier even if the ledger write below didn't land.
                payload=f"{user['id']}:{plan}",
            )
        except platega.PlategaError as exc:
            return None, str(exc)
        transaction_id = str(result.get("transactionId") or "")
        redirect = result.get("redirect") or result.get("return")
        if not transaction_id or not redirect:
            return None, "Platega не вернула ссылку на оплату"
        # Ledger write is best-effort: the payment already exists at Platega and
        # the webhook can still activate via payload, so a ledger hiccup must not
        # block the user from reaching the payment page.
        try:
            await self.repo.create_subscription_payment(user["id"], transaction_id, price)
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
        # Payload is "<user_id>:<plan>" (plan optional for older payments).
        raw_payload = str(body.get("payload") or "")
        payload_uid, plan = raw_payload, "max"
        if ":" in raw_payload:
            payload_uid, plan = raw_payload.rsplit(":", 1)
        plan = _normalize_plan(plan)
        user_id = (payment or {}).get("user_id") or payload_uid or None
        # Expected charge: the ledger amount if we have it, else the tier price.
        expected_rub = (payment or {}).get("amount_rub")
        if expected_rub is None:
            expected_rub = _price_for_plan(plan)
        if status == "CONFIRMED":
            # Defense-in-depth: if the callback reports an amount, it must match the
            # price we charge. The amount is server-set at creation, so a mismatch
            # means a tampered/foreign callback — refuse to grant entitlement.
            if not self._amount_ok(body, expected_rub):
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
                    user_id, transaction_id, expected_rub
                )
                transitioned = await self.repo.confirm_subscription_payment_once(transaction_id)
            except Exception:
                # If the ledger is unreachable we cannot guarantee single activation,
                # so we must not activate. Returning False makes Platega retry later.
                return False
            if transitioned:
                activate_uid = transitioned.get("user_id") or user_id
                await self.repo.activate_subscription(
                    activate_uid, SUBSCRIPTION_DAYS, plan if config.PLANS_ENABLED else None
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
