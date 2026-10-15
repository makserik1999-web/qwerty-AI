"""Paying through Kaspi: order, "I have paid", and a person confirming it.

Nothing is applied on the teacher's word: only a staff confirmation gives the
plan, once, and every decision is logged.
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

pytestmark = pytest.mark.real_plans


def run_db(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def kaspi(backend, monkeypatch):
    monkeypatch.setattr(backend.config, "KASPI_PAY_PHONE", "+7 707 000 00 00")
    monkeypatch.setattr(backend.config, "KASPI_PAY_NAME", "Иса Ә.")


@pytest.fixture
def account(backend):
    from fastapi.testclient import TestClient

    opened = []

    def _make(role="teacher", staff=None):
        client = TestClient(backend.app)
        client.__enter__()
        opened.append(client)
        response = client.post("/api/auth/signup", json={
            "email": f"pay{uuid.uuid4().hex[:10]}@school.kz", "password": "password123",
            "name": "Тест", "role": role})
        assert response.status_code == 201, response.text
        client.user = response.json()["user"]
        if staff:
            run_db(backend.db.db.users.update_one({"_id": ObjectId(client.user["id"])},
                                                  {"$set": {"staff_role": staff}}))
        return client

    yield _make
    for client in opened:
        client.__exit__(None, None, None)


def order(client, plan_id="ustaz_month"):
    response = client.post("/api/payments", json={"plan_id": plan_id})
    assert response.status_code == 201, response.text
    return response.json()


class TestTheTeachersSide:
    def test_not_offered_without_kaspi_details(self, backend, account, monkeypatch):
        monkeypatch.setattr(backend.config, "KASPI_PAY_PHONE", "")
        client = account()
        assert client.get("/api/payments").json()["enabled"] is False
        assert client.post("/api/payments", json={"plan_id": "ustaz_month"}).status_code == 503

    def test_an_order_has_a_code_the_price_and_the_details(self, account):
        client = account()
        made = order(client)
        assert made["code"].startswith("AK-") and len(made["code"]) == 8
        assert made["amount"] == 4990 and made["status"] == "awaiting"
        listing = client.get("/api/payments").json()
        assert listing["details"]["phone"] == "+7 707 000 00 00"
        assert listing["items"][0]["code"] == made["code"]

    def test_asking_twice_returns_the_same_open_order(self, account):
        client = account()
        assert order(client)["code"] == order(client)["code"]

    def test_saying_it_is_paid_applies_nothing(self, account):
        client = account()
        made = order(client)
        response = client.post(f"/api/payments/{made['id']}/submitted")
        assert response.json()["status"] == "submitted"
        assert client.get("/api/plan").json()["plan"]["kind"] == "free"

    def test_extra_videos_need_a_running_ustaz(self, account):
        client = account()
        response = client.post("/api/payments", json={"plan_id": "videos_10"})
        assert response.status_code == 400 and response.json()["code"] == "addon_needs_ustaz"

    def test_students_do_not_buy_plans(self, account):
        client = account(role="student")
        assert client.post("/api/payments", json={"plan_id": "ustaz_month"}).status_code == 403

    def test_someone_elses_order_is_not_found(self, account):
        owner, other = account(), account()
        made = order(owner)
        assert other.post(f"/api/payments/{made['id']}/submitted").status_code == 404

    def test_an_unpaid_order_expires(self, backend, account):
        client = account()
        made = order(client)
        run_db(backend.db.db.payments.update_one(
            {"_id": ObjectId(made["id"])},
            {"$set": {"created_at": datetime.now(timezone.utc) - timedelta(days=5)}}))
        assert client.get("/api/payments").json()["items"][0]["status"] == "expired"

    def test_the_price_is_the_one_at_ordering(self, backend, account):
        client = account()
        made = order(client)
        run_db(backend.db.db.plans.update_one({"_id": "ustaz_month"}, {"$set": {"price": 9999}}, upsert=True))
        try:
            assert client.get("/api/payments").json()["items"][0]["amount"] == made["amount"] == 4990
        finally:
            run_db(backend.db.db.plans.delete_one({"_id": "ustaz_month"}))


class TestTheTeamsSide:
    def test_confirming_applies_the_plan_once_and_is_logged(self, backend, account):
        admin = account(staff="admin")
        teacher = account()
        made = order(teacher)
        teacher.post(f"/api/payments/{made['id']}/submitted")

        assert admin.post(f"/api/admin/payments/{made['id']}/confirm", json={}).status_code == 200
        plan = teacher.get("/api/plan").json()["plan"]
        assert plan["kind"] == "ustaz" and plan["plan_id"] == "ustaz_month"

        again = admin.post(f"/api/admin/payments/{made['id']}/confirm", json={})
        assert again.status_code == 409
        entry = run_db(backend.db.db.admin_audit.find_one({"action": "payment.confirm",
                                                            "target.payment": made["code"]}))
        assert entry and entry["details"]["amount"] == 4990

    def test_the_school_year_runs_to_june(self, account):
        admin = account(staff="admin")
        teacher = account()
        made = order(teacher, "ustaz_year")
        admin.post(f"/api/admin/payments/{made['id']}/confirm", json={})
        expires = teacher.get("/api/plan").json()["plan"]["subscription"]["expires_at"]
        local = datetime.fromisoformat(expires) + timedelta(hours=5)
        assert (local.month, local.day) == (6, 1)

    def test_extra_videos_are_added(self, backend, account):
        from app.services import plans

        admin = account(staff="admin")
        teacher = account()
        user = run_db(backend.db.db.users.find_one({"_id": ObjectId(teacher.user["id"])}))
        run_db(plans.grant(user, plans.USTAZ_MONTH))
        made = order(teacher, "videos_10")
        admin.post(f"/api/admin/payments/{made['id']}/confirm", json={})
        assert teacher.get("/api/plan").json()["plan"]["extra_videos"] == 10

    def test_a_rejection_needs_a_reason_and_the_teacher_sees_it(self, account):
        admin = account(staff="admin")
        teacher = account()
        made = order(teacher)
        assert admin.post(f"/api/admin/payments/{made['id']}/reject", json={"reason": ""}).status_code == 400
        admin.post(f"/api/admin/payments/{made['id']}/reject", json={"reason": "Перевод не найден"})
        mine = teacher.get("/api/payments").json()["items"][0]
        assert mine["status"] == "rejected" and mine["reason"] == "Перевод не найден"
        assert teacher.get("/api/plan").json()["plan"]["kind"] == "free"

    def test_a_refund_can_take_the_plan_back(self, account):
        admin = account(staff="admin")
        teacher = account()
        made = order(teacher)
        admin.post(f"/api/admin/payments/{made['id']}/confirm", json={})
        response = admin.post(f"/api/admin/payments/{made['id']}/refund",
                              json={"reason": "Ата-ана сұрады", "take_back": True})
        assert response.status_code == 200
        assert teacher.get("/api/plan").json()["plan"]["kind"] != "ustaz"

    def test_support_does_not_handle_money(self, account):
        support = account(staff="support")
        teacher = account()
        made = order(teacher)
        assert support.get("/api/admin/payments").status_code == 403
        assert support.post(f"/api/admin/payments/{made['id']}/confirm", json={}).status_code == 403

    def test_revenue_counts_confirmed_money(self, account):
        admin = account(staff="admin")
        before = sum(r["amount"] for r in admin.get("/api/admin/payments").json()["revenue"])
        teacher = account()
        made = order(teacher)
        admin.post(f"/api/admin/payments/{made['id']}/confirm", json={})
        after = sum(r["amount"] for r in admin.get("/api/admin/payments").json()["revenue"])
        assert after == before + 4990

    def test_staff_are_emailed_when_a_payment_is_reported(self, backend, account, monkeypatch):
        from app.services import mailer

        sent = []
        monkeypatch.setattr(backend.config, "PAYMENT_NOTIFY_EMAILS", ["team@akron.kz"])
        monkeypatch.setattr(mailer, "send_later", lambda to, subject, text, html=None: sent.append((to, subject)))
        teacher = account()
        made = order(teacher)
        teacher.post(f"/api/payments/{made['id']}/submitted")
        assert ("team@akron.kz", f"Akron: оплата {made['code']} ждёт проверки") in sent

    def test_a_reported_payment_reaches_telegram(self, backend, account, monkeypatch):
        """Where somebody actually sees it: the code, the money, and the link."""
        from app.services import telegram

        sent = []
        monkeypatch.setattr(backend.config, "TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setattr(backend.config, "TELEGRAM_CHAT_ID", "42")
        monkeypatch.setattr(backend.config, "PAYMENT_TELEGRAM_CHAT_ID", "")
        monkeypatch.setattr(telegram, "_post", lambda chat, text: sent.append((chat, text)))
        teacher = account()
        made = order(teacher, "ustaz_year")
        teacher.post(f"/api/payments/{made['id']}/submitted")
        for _ in range(50):
            if sent:
                break
            time.sleep(0.02)
        assert sent, "nothing was sent to Telegram"
        chat, text = sent[0]
        assert chat == "42"
        assert made["code"] in text and "29 900 ₸" in text and "/admin?tab=payments" in text

    def test_payments_can_have_their_own_chat(self, backend, monkeypatch):
        from app.services import telegram

        monkeypatch.setattr(backend.config, "TELEGRAM_CHAT_ID", "42")
        monkeypatch.setattr(backend.config, "PAYMENT_TELEGRAM_CHAT_ID", "77")
        assert telegram.payments_chat() == "77"

    def test_no_bot_no_message(self, backend, account, monkeypatch):
        from app.services import telegram

        monkeypatch.setattr(backend.config, "TELEGRAM_BOT_TOKEN", "")
        monkeypatch.setattr(telegram, "_post", lambda chat, text: (_ for _ in ()).throw(AssertionError("sent")))
        teacher = account()
        made = order(teacher)
        assert teacher.post(f"/api/payments/{made['id']}/submitted").status_code == 200

