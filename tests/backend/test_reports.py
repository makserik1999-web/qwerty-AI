"""A teacher's "something is wrong here", and support fixing a wrong role.

Reports land in the admin panel and in Telegram; staff mark them done. The
role a person picked at sign-up can be changed by staff - never by the person.
"""

import asyncio
import time
import uuid

import pytest
from bson import ObjectId


def run_db(coro):
    return asyncio.run(coro)


@pytest.fixture
def account(backend):
    from fastapi.testclient import TestClient

    opened = []

    def _make(role="teacher", staff=None):
        c = TestClient(backend.app)
        c.__enter__()
        opened.append(c)
        r = c.post("/api/auth/signup", json={"email": f"rp{uuid.uuid4().hex[:10]}@school.kz",
                                             "password": "password123", "role": role})
        assert r.status_code == 201, r.text
        c.user = r.json()["user"]
        if staff:
            run_db(backend.db.db.users.update_one({"_id": ObjectId(c.user["id"])},
                                                  {"$set": {"staff_role": staff}}))
        return c

    yield _make
    for c in opened:
        c.__exit__(None, None, None)


class TestReports:
    def test_a_report_reaches_the_panel_and_telegram(self, backend, account, monkeypatch):
        from app.services import telegram

        sent = []
        monkeypatch.setattr(backend.config, "TELEGRAM_BOT_TOKEN", "1:x")
        monkeypatch.setattr(backend.config, "TELEGRAM_CHAT_ID", "5")
        monkeypatch.setattr(telegram, "_post", lambda chat, text: sent.append(text))
        teacher = account()
        made = teacher.post("/api/reports", json={"kind": "assessment", "ref_id": "abc",
                                                  "text": "3-тапсырманың жауабы қате", "page": "/app/generate"})
        assert made.status_code == 201, made.text
        for _ in range(50):
            if sent:
                break
            time.sleep(0.02)
        assert sent and "3-тапсырманың жауабы қате" in sent[0] and "/admin?tab=reports" in sent[0]

        support = account(staff="support")
        listed = support.get("/api/admin/reports").json()
        mine = next(r for r in listed["items"] if r["id"] == made.json()["id"])
        assert mine["kind"] == "assessment" and mine["email"] == teacher.user["email"]
        assert support.post(f"/api/admin/reports/{mine['id']}/resolve", json={"reason": "fixed"}).status_code == 200
        assert mine["id"] not in {r["id"] for r in support.get("/api/admin/reports").json()["items"]}
        assert support.post(f"/api/admin/reports/{mine['id']}/resolve", json={}).status_code == 404

    def test_empty_or_unknown_is_refused(self, account):
        teacher = account()
        assert teacher.post("/api/reports", json={"kind": "quiz", "text": "   "}).status_code == 400
        assert teacher.post("/api/reports", json={"kind": "poem", "text": "x"}).status_code == 400

    def test_students_can_report_too(self, account):
        assert account(role="student").post("/api/reports", json={"kind": "explanation", "text": "видео без звука"}
                                             ).status_code == 201

    def test_a_day_has_a_limit(self, account):
        teacher = account()
        for _ in range(20):
            teacher.post("/api/reports", json={"kind": "other", "text": "x"})
        assert teacher.post("/api/reports", json={"kind": "other", "text": "x"}).status_code == 429

    def test_teachers_do_not_read_reports(self, account):
        assert account().get("/api/admin/reports").status_code == 404

    def test_deleting_the_account_keeps_the_report_not_the_person(self, backend, account):
        teacher = account()
        made = teacher.post("/api/reports", json={"kind": "other", "text": "x"}).json()
        teacher.delete("/api/auth/account")
        report = run_db(backend.db.db.problem_reports.find_one({"_id": ObjectId(made["id"])}))
        assert report["user_id"] == "deleted" and report["email"] == ""


class TestRole:
    def test_support_turns_a_student_into_a_teacher(self, backend, account):
        student = account(role="student")
        support = account(staff="support")
        changed = support.post(f"/api/admin/users/{student.user['id']}/role",
                               json={"role": "teacher", "reason": "мұғалім, қате таңдаған"})
        assert changed.status_code == 200
        assert student.get("/api/auth/me").json()["user"]["role"] == "teacher"
        entry = run_db(backend.db.db.admin_audit.find_one({"action": "user.role",
                                                           "target.user_id": student.user["id"]}))
        assert entry["details"] == {"from": "student", "to": "teacher"}

    def test_needs_a_reason_and_a_real_role(self, account):
        student = account(role="student")
        support = account(staff="support")
        assert support.post(f"/api/admin/users/{student.user['id']}/role",
                            json={"role": "teacher", "reason": ""}).status_code == 400
        assert support.post(f"/api/admin/users/{student.user['id']}/role",
                            json={"role": "admin", "reason": "x"}).status_code == 400

    def test_nobody_changes_their_own_role(self, account):
        student = account(role="student")
        assert student.post(f"/api/admin/users/{student.user['id']}/role",
                            json={"role": "teacher", "reason": "x"}).status_code == 404
