"""Inviting a colleague: +2 trial videos for them, +1 month for you once they pay.

The reward waits for a confirmed payment, at most six months in any year, and
the admin panel sees who invited whom and which accounts share a device.
"""

import asyncio
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


@pytest.fixture
def account(backend):
    from fastapi.testclient import TestClient

    opened = []

    def _make(role="teacher", ref=None, device=None, phone=False, staff=None):
        client = TestClient(backend.app)
        client.__enter__()
        opened.append(client)
        body = {"email": f"r{uuid.uuid4().hex[:10]}@school.kz", "password": "password123", "role": role}
        if ref:
            body["ref"] = ref
        if device:
            body["device"] = device
        response = client.post("/api/auth/signup", json=body)
        assert response.status_code == 201, response.text
        client.user = response.json()["user"]
        changes = {}
        if phone:
            changes.update({"phone": "7707" + f"{uuid.uuid4().int % 10_000_000:07d}",
                            "phone_verified_at": datetime.now(timezone.utc)})
        if staff:
            changes["staff_role"] = staff
        if changes:
            run_db(backend.db.db.users.update_one({"_id": ObjectId(client.user["id"])}, {"$set": changes}))
        return client

    yield _make
    for client in opened:
        client.__exit__(None, None, None)


def doc(backend, user_id):
    return run_db(backend.db.db.users.find_one({"_id": ObjectId(user_id)}))


def pay(admin, teacher, plan_id="ustaz_month"):
    made = teacher.post("/api/payments", json={"plan_id": plan_id}).json()
    assert admin.post(f"/api/admin/payments/{made['id']}/confirm", json={}).status_code == 200


class TestTheLink:
    def test_a_teacher_gets_a_code_and_a_link(self, account):
        teacher = account()
        mine = teacher.get("/api/referrals").json()
        assert len(mine["code"]) == 6 and mine["link"].endswith(f"/signup?ref={mine['code']}")
        assert teacher.get("/api/referrals").json()["code"] == mine["code"]  # stable

    def test_students_do_not_invite(self, account):
        assert account(role="student").get("/api/referrals").status_code == 403

    def test_signing_up_with_the_code_records_the_inviter(self, backend, account):
        inviter = account()
        code = inviter.get("/api/referrals").json()["code"]
        invitee = account(ref=code)
        assert doc(backend, invitee.user["id"])["referred_by"] == inviter.user["id"]
        assert inviter.get("/api/referrals").json()["invited"] == 1

    def test_an_unknown_code_is_ignored(self, backend, account):
        invitee = account(ref="NOPE99")
        assert "referred_by" not in doc(backend, invitee.user["id"])

    def test_no_invite_from_the_inviters_own_browser(self, backend, account):
        # A tester signing up on the owner's laptop, where the owner's own
        # link was once opened: nobody invited them, and no bonus is due.
        inviter = account(device="owner-laptop")
        code = inviter.get("/api/referrals").json()["code"]
        tester = account(ref=code, device="owner-laptop", phone=True)
        assert "referred_by" not in doc(backend, tester.user["id"])
        assert tester.get("/api/plan").json()["plan"]["available"]["videos"] == 2
        assert inviter.get("/api/referrals").json()["invited"] == 0

    def test_another_browser_is_a_real_invite(self, backend, account):
        inviter = account(device="owner-laptop")
        code = inviter.get("/api/referrals").json()["code"]
        colleague = account(ref=code, device="colleague-phone")
        assert doc(backend, colleague.user["id"])["referred_by"] == inviter.user["id"]


class TestRewards:
    def test_the_invited_teacher_gets_two_more_trial_videos(self, backend, account):
        inviter = account()
        invitee = account(ref=inviter.get("/api/referrals").json()["code"], phone=True)
        plan = invitee.get("/api/plan").json()["plan"]
        assert plan["kind"] == "trial" and plan["available"]["videos"] == 4

    def test_the_inviter_gets_a_month_when_the_invitee_pays(self, backend, account):
        admin = account(staff="admin")
        inviter = account()
        invitee = account(ref=inviter.get("/api/referrals").json()["code"])
        assert inviter.get("/api/plan").json()["plan"]["kind"] != "ustaz"

        pay(admin, invitee)

        plan = inviter.get("/api/plan").json()["plan"]
        assert plan["kind"] == "ustaz"
        assert inviter.get("/api/referrals").json()["paid"] == 1
        entry = run_db(backend.db.db.admin_audit.find_one({"action": "referral.reward",
                                                            "target.user_id": inviter.user["id"]}))
        assert entry and entry["actor"]["kind"] == "system"

    def test_only_the_first_payment_counts(self, backend, account):
        admin = account(staff="admin")
        inviter = account()
        invitee = account(ref=inviter.get("/api/referrals").json()["code"])
        pay(admin, invitee)
        first = doc(backend, inviter.user["id"])["subscription"]["expires_at"]
        pay(admin, invitee)
        assert doc(backend, inviter.user["id"])["subscription"]["expires_at"] == first

    def test_a_school_year_subscriber_keeps_the_school_year(self, backend, account):
        from app.services import plans

        admin = account(staff="admin")
        inviter = account()
        run_db(plans.grant(doc(backend, inviter.user["id"]), plans.USTAZ_YEAR))
        before = doc(backend, inviter.user["id"])["subscription"]
        invitee = account(ref=inviter.get("/api/referrals").json()["code"])
        pay(admin, invitee)
        after = doc(backend, inviter.user["id"])["subscription"]
        assert after["plan_id"] == "ustaz_year" and after["expires_at"] > before["expires_at"]

    def test_extra_videos_are_not_a_first_month(self, backend, account):
        from app.services import plans

        admin = account(staff="admin")
        inviter = account()
        invitee = account(ref=inviter.get("/api/referrals").json()["code"])
        run_db(plans.grant(doc(backend, invitee.user["id"]), plans.USTAZ_MONTH))
        pay(admin, invitee, "videos_10")
        assert inviter.get("/api/referrals").json()["paid"] == 0

    def test_six_months_a_year_at_most(self, backend, account):
        inviter = account()
        now = datetime.now(timezone.utc)
        run_db(backend.db.db.referral_rewards.insert_many([
            {"inviter_id": inviter.user["id"], "invitee_id": f"x{i}", "at": now - timedelta(days=10 * i),
             "months": 1} for i in range(6)]))
        admin = account(staff="admin")
        invitee = account(ref=inviter.get("/api/referrals").json()["code"])
        pay(admin, invitee)
        assert inviter.get("/api/plan").json()["plan"]["kind"] != "ustaz"
        capped = run_db(backend.db.db.referral_rewards.find_one({"invitee_id": invitee.user["id"]}))
        assert capped["capped"] is True and capped["months"] == 0


class TestAbuseSignals:
    def test_staff_see_pairs_and_shared_devices(self, backend, account):
        support = account(staff="support")
        inviter = account(device="dev-A")
        code = inviter.get("/api/referrals").json()["code"]
        invitee = account(ref=code, device="dev-B")
        # Later signed in on the inviter's browser - and a third account made there.
        invitee.post("/api/auth/login", json={"email": invitee.user["email"], "password": "password123",
                                               "device": "dev-A"})
        account(device="dev-A")

        view = support.get("/api/admin/referrals").json()
        pair = next(p for p in view["pairs"] if p["invitee_id"] == invitee.user["id"])
        assert pair["inviter_id"] == inviter.user["id"] and pair["same_device"] is True
        assert any(g["kind"] == "device" and len(g["accounts"]) >= 3 for g in view["crowded"])

    def test_only_hashes_are_stored(self, backend, account):
        user = account(device="my-browser-id")
        stored = doc(backend, user.user["id"])
        assert stored["device_hashes"] and "my-browser-id" not in str(stored)
        assert "testclient" not in str(stored.get("ip_hashes"))

    def test_teachers_cannot_see_it(self, account):
        assert account().get("/api/admin/referrals").status_code == 404
