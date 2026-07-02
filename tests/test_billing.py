from __future__ import annotations

import pytest

import config
from application.services import billing
from application.services.billing import BillingService
from infrastructure import platega


# ---------------- price / period / days helpers ----------------

def test_normalize_period_defaults_to_month():
    assert billing._normalize_period(None) == "month"
    assert billing._normalize_period("garbage") == "month"
    assert billing._normalize_period("year") == "year"


def test_normalize_plan_defaults_to_max():
    assert billing._normalize_plan(None) == "max"
    assert billing._normalize_plan("garbage") == "max"
    assert billing._normalize_plan("pro") == "pro"


def test_days_for_period():
    assert billing._days_for_period("month") == billing.SUBSCRIPTION_DAYS == 30
    assert billing._days_for_period("year") == billing.SUBSCRIPTION_DAYS_YEAR == 365


def test_price_for_plan_year_ignores_tiers(monkeypatch):
    monkeypatch.setattr(config, "PLANS_ENABLED", True)
    monkeypatch.setattr(config, "SUBSCRIPTION_PRICE_YEAR_RUB", 9900)
    assert billing._price_for_plan("pro", "year") == 9900
    assert billing._price_for_plan("max", "year") == 9900


def test_price_for_plan_month_flat_when_tiers_off(monkeypatch):
    monkeypatch.setattr(config, "PLANS_ENABLED", False)
    monkeypatch.setattr(config, "SUBSCRIPTION_PRICE_RUB", 990)
    assert billing._price_for_plan("pro", "month") == 990
    assert billing._price_for_plan("max", "month") == 990


def test_price_for_plan_month_tiered_when_tiers_on(monkeypatch):
    monkeypatch.setattr(config, "PLANS_ENABLED", True)
    monkeypatch.setattr(config, "PRICE_PRO_RUB", 590)
    monkeypatch.setattr(config, "PRICE_MAX_RUB", 990)
    assert billing._price_for_plan("pro", "month") == 590
    assert billing._price_for_plan("max", "month") == 990


# ---------------- reconcile_on_return ----------------

class FakeRepo:
    def __init__(self):
        self.pending_payment: dict | None = None
        self.confirm_result: dict | None = None
        self.confirm_calls: list[str] = []
        self.activate_calls: list[tuple] = []
        self.referral_calls: list[str] = []

    async def get_latest_pending_payment_for_user(self, user_id):
        return self.pending_payment

    async def confirm_subscription_payment_once(self, transaction_id):
        self.confirm_calls.append(transaction_id)
        return self.confirm_result

    async def activate_subscription(self, user_id, days, plan=None):
        self.activate_calls.append((user_id, days, plan))
        return {"id": user_id}

    async def grant_referral_reward(self, user_id):
        self.referral_calls.append(user_id)
        return True

    async def get_subscription_payment_by_transaction(self, transaction_id):
        return self.payment_by_tx

    async def mark_subscription_payment(self, transaction_id, status, confirmed=False):
        return None


@pytest.fixture
def repo():
    return FakeRepo()


async def test_reconcile_no_pending_payment_returns_false(repo):
    repo.pending_payment = None
    svc = BillingService(repo)
    assert await svc.reconcile_on_return("user-1") is False


async def test_reconcile_not_confirmed_returns_false(repo, monkeypatch):
    repo.pending_payment = {"transaction_id": "tx1", "amount_rub": 990}

    async def fake_get_transaction(tid):
        return {"status": "PENDING"}

    monkeypatch.setattr(platega, "get_transaction", fake_get_transaction)
    svc = BillingService(repo)
    assert await svc.reconcile_on_return("user-1") is False
    assert repo.confirm_calls == []


async def test_reconcile_activates_on_confirmed(repo, monkeypatch):
    repo.pending_payment = {"transaction_id": "tx1", "amount_rub": 990}
    repo.confirm_result = {"user_id": "user-1"}

    async def fake_get_transaction(tid):
        assert tid == "tx1"
        return {"status": "CONFIRMED", "amount": 990}

    monkeypatch.setattr(platega, "get_transaction", fake_get_transaction)
    svc = BillingService(repo)
    assert await svc.reconcile_on_return("user-1") is True
    assert repo.confirm_calls == ["tx1"]
    assert repo.activate_calls == [("user-1", 30, None)]
    assert repo.referral_calls == ["user-1"]


async def test_reconcile_year_amount_infers_year_period(repo, monkeypatch):
    repo.pending_payment = {"transaction_id": "tx1", "amount_rub": 9900}
    repo.confirm_result = {"user_id": "user-1"}

    async def fake_get_transaction(tid):
        return {"status": "CONFIRMED", "amount": 9900}

    monkeypatch.setattr(platega, "get_transaction", fake_get_transaction)
    monkeypatch.setattr(config, "SUBSCRIPTION_PRICE_YEAR_RUB", 9900)
    svc = BillingService(repo)
    assert await svc.reconcile_on_return("user-1") is True
    assert repo.activate_calls == [("user-1", 365, None)]


async def test_reconcile_amount_mismatch_refuses(repo, monkeypatch):
    repo.pending_payment = {"transaction_id": "tx1", "amount_rub": 990}

    async def fake_get_transaction(tid):
        return {"status": "CONFIRMED", "amount": 1}  # tampered

    monkeypatch.setattr(platega, "get_transaction", fake_get_transaction)
    svc = BillingService(repo)
    assert await svc.reconcile_on_return("user-1") is False
    assert repo.confirm_calls == []


async def test_reconcile_already_activated_by_webhook_returns_false(repo, monkeypatch):
    """confirm_subscription_payment_once returns None when the webhook already
    made the pending->confirmed transition — reconcile must not double-activate."""
    repo.pending_payment = {"transaction_id": "tx1", "amount_rub": 990}
    repo.confirm_result = None

    async def fake_get_transaction(tid):
        return {"status": "CONFIRMED", "amount": 990}

    monkeypatch.setattr(platega, "get_transaction", fake_get_transaction)
    svc = BillingService(repo)
    assert await svc.reconcile_on_return("user-1") is False
    assert repo.activate_calls == []


# ---------------- handle_webhook ----------------

async def test_webhook_rejects_bad_headers(repo, monkeypatch):
    monkeypatch.setattr(platega, "verify_webhook_headers", lambda m, s: False)
    svc = BillingService(repo)
    ok = await svc.handle_webhook("bad-merchant", "bad-secret", {"id": "tx1", "status": "CONFIRMED"})
    assert ok is False


async def test_webhook_unknown_transaction_acks_without_activating(repo, monkeypatch):
    monkeypatch.setattr(platega, "verify_webhook_headers", lambda m, s: True)
    repo.payment_by_tx = None
    monkeypatch.setattr(config, "PLANS_ENABLED", False)
    monkeypatch.setattr(config, "SUBSCRIPTION_PRICE_RUB", 990)
    svc = BillingService(repo)
    ok = await svc.handle_webhook("m", "s", {
        "id": "tx-unknown", "status": "CONFIRMED", "payload": "user-1:max:month",
    })
    assert ok is True  # acked so Platega stops retrying
    assert repo.activate_calls == []


async def test_webhook_confirms_and_activates(repo, monkeypatch):
    monkeypatch.setattr(platega, "verify_webhook_headers", lambda m, s: True)
    repo.payment_by_tx = {"user_id": "user-1", "amount_rub": 990}
    repo.confirm_result = {"user_id": "user-1"}
    monkeypatch.setattr(config, "PLANS_ENABLED", False)
    svc = BillingService(repo)
    ok = await svc.handle_webhook("m", "s", {
        "id": "tx1", "status": "CONFIRMED", "amount": 990, "payload": "user-1:max:month",
    })
    assert ok is True
    assert repo.confirm_calls == ["tx1"]
    assert repo.activate_calls == [("user-1", 30, None)]
    assert repo.referral_calls == ["user-1"]


async def test_webhook_accepts_transactionId_key(repo, monkeypatch):
    """Callback may echo the id as 'transactionId' instead of 'id'."""
    monkeypatch.setattr(platega, "verify_webhook_headers", lambda m, s: True)
    repo.payment_by_tx = {"user_id": "user-1", "amount_rub": 990}
    repo.confirm_result = {"user_id": "user-1"}
    monkeypatch.setattr(config, "PLANS_ENABLED", False)
    svc = BillingService(repo)
    ok = await svc.handle_webhook("m", "s", {
        "transactionId": "tx1", "status": "CONFIRMED", "amount": 990, "payload": "user-1:max:month",
    })
    assert ok is True
    assert repo.confirm_calls == ["tx1"]


async def test_webhook_double_confirm_does_not_double_activate(repo, monkeypatch):
    monkeypatch.setattr(platega, "verify_webhook_headers", lambda m, s: True)
    repo.payment_by_tx = {"user_id": "user-1", "amount_rub": 990}
    repo.confirm_result = None  # already transitioned by a prior call
    monkeypatch.setattr(config, "PLANS_ENABLED", False)
    svc = BillingService(repo)
    ok = await svc.handle_webhook("m", "s", {
        "id": "tx1", "status": "CONFIRMED", "amount": 990, "payload": "user-1:max:month",
    })
    assert ok is True
    assert repo.activate_calls == []


async def test_webhook_amount_mismatch_refuses(repo, monkeypatch):
    monkeypatch.setattr(platega, "verify_webhook_headers", lambda m, s: True)
    repo.payment_by_tx = {"user_id": "user-1", "amount_rub": 990}
    monkeypatch.setattr(config, "PLANS_ENABLED", False)
    svc = BillingService(repo)
    ok = await svc.handle_webhook("m", "s", {
        "id": "tx1", "status": "CONFIRMED", "amount": 1, "payload": "user-1:max:month",
    })
    assert ok is False
    assert repo.activate_calls == []


async def test_webhook_canceled_marks_payment(repo, monkeypatch):
    monkeypatch.setattr(platega, "verify_webhook_headers", lambda m, s: True)
    repo.payment_by_tx = {"user_id": "user-1", "amount_rub": 990}
    calls = []

    async def fake_mark(tid, status, confirmed=False):
        calls.append((tid, status))
        return None

    repo.mark_subscription_payment = fake_mark
    svc = BillingService(repo)
    ok = await svc.handle_webhook("m", "s", {"id": "tx1", "status": "CANCELED"})
    assert ok is True
    assert calls == [("tx1", "canceled")]
