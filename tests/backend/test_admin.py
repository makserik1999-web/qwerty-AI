"""The admin panel's API, and who is let into it.

Rights are checked by the backend, not by the interface: hiding the admin link
from ordinary accounts protects nothing, because anyone who knows a request's
address can send it. So the first class here does not list the routes it
checks - it reads them off the application. A route added later under
/api/admin is called as a stranger, a teacher, support and admin without
anyone remembering to write that test.

The second rule: nobody becomes staff through the site. Signup and the profile
ignore `staff_role`, and the only writer is the server command, tested at the
bottom.
"""

import asyncio
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

# Routes support may not use. A new admin route has to be added here or to
# nowhere, consciously: the test fails if support's 403s and this set differ.
ADMIN_ONLY = {
    "/api/admin/audit",
    "/api/admin/cache/stats",
    "/api/admin/users/{user_id}/subscription",
    "/api/admin/users/{user_id}/subscription/end",
    "/api/admin/users/{user_id}/extra-videos",
    "/api/admin/plans",
    "/api/admin/plans/{plan_id}",
    "/api/admin/payments",
    "/api/admin/payments/{payment_id}/confirm",
    "/api/admin/payments/{payment_id}/reject",
    "/api/admin/payments/{payment_id}/refund",
    "/api/admin/metrics",
}

# Let through: anything but the guard's own answers. A POST sent here with no
# body is a 422 - the request reached the route, which is all this checks.
GUARD_ANSWERS = (403, 404)


def run_db(coro):
    """mongomock keeps documents in plain dicts, so any loop can await it."""
    return asyncio.run(coro)


@pytest.fixture
def account(backend):
    """A fresh signed-in TestClient, optionally given a staff role in the db.

    Each account gets its own client: one client is one cookie jar, and
    signing up a second person in it would sign the first one out.
    """
    from fastapi.testclient import TestClient

    opened = []

    def _make(role="teacher", staff_role=None):
        client = TestClient(backend.app)
        client.__enter__()
        opened.append(client)
        email = f"a{uuid.uuid4().hex[:10]}@school.kz"
        response = client.post("/api/auth/signup", json={
            "email": email, "password": "password123", "name": "Тест", "role": role,
        })
        assert response.status_code == 201, response.text
        user = response.json()["user"]
        if staff_role:
            set_staff_role(backend, user["id"], staff_role)
        client.user = user
        return client

    yield _make
    for client in opened:
        client.__exit__(None, None, None)


def set_staff_role(backend, user_id, role):
    update = {"$set": {"staff_role": role}} if role else {"$unset": {"staff_role": ""}}
    run_db(backend.db.db.users.update_one({"_id": ObjectId(user_id)}, update))


def admin_routes(backend):
    """(method, concrete path, route template) for every /api/admin route."""
    from fastapi.routing import APIRoute

    found = []
    for route in backend.app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/admin"):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                found.append((method, route.path, route.path))
    assert found, "no /api/admin routes found - the router is not mounted"
    return found


def call(client, method, template, user_id):
    path = (template.replace("{user_id}", user_id).replace("{plan_id}", "trial")
            .replace("{payment_id}", "0" * 24))
    return client.request(method, path)


# ---------------------------------------------------------------- the gate --


class TestEveryAdminRouteIsGuarded:
    def test_a_stranger_gets_404_everywhere(self, backend, anon_client, account):
        someone = account().user["id"]
        for method, template, _ in admin_routes(backend):
            response = call(anon_client, method, template, someone)
            assert response.status_code == 404, f"{method} {template} -> {response.status_code}"

    def test_a_teacher_gets_404_everywhere(self, backend, account):
        teacher = account(role="teacher")
        for method, template, _ in admin_routes(backend):
            response = call(teacher, method, template, teacher.user["id"])
            assert response.status_code == 404, f"{method} {template} -> {response.status_code}"

    def test_a_student_gets_404_everywhere(self, backend, account):
        student = account(role="student")
        for method, template, _ in admin_routes(backend):
            response = call(student, method, template, student.user["id"])
            assert response.status_code == 404, f"{method} {template} -> {response.status_code}"

    def test_support_is_refused_exactly_the_admin_only_routes(self, backend, account):
        support = account(staff_role="support")
        refused = set()
        for method, template, _ in admin_routes(backend):
            response = call(support, method, template, support.user["id"])
            assert response.status_code != 404, f"{method} {template} -> {response.status_code}"
            if response.status_code == 403:
                refused.add(template)
        assert refused == ADMIN_ONLY

    def test_admin_gets_every_route(self, backend, account):
        admin = account(staff_role="admin")
        for method, template, _ in admin_routes(backend):
            response = call(admin, method, template, admin.user["id"])
            assert response.status_code not in GUARD_ANSWERS, f"{method} {template} -> {response.status_code}"
            if method == "GET":
                assert response.status_code == 200, f"{method} {template} -> {response.status_code}"

    def test_an_unknown_staff_value_is_not_staff(self, backend, account):
        """Only the closed set counts; anything else written there is nobody."""
        odd = account(staff_role="superuser")
        assert odd.get("/api/admin/users").status_code == 404

    def test_taking_the_role_away_works_on_the_next_request(self, backend, account):
        admin = account(staff_role="admin")
        assert admin.get("/api/admin/users").status_code == 200

        set_staff_role(backend, admin.user["id"], None)

        # Same session, same cookie: the role is read from the account each time.
        assert admin.get("/api/admin/users").status_code == 404


class TestNobodyBecomesStaffThroughTheSite:
    def test_signup_ignores_a_staff_role(self, backend, anon_client):
        response = anon_client.post("/api/auth/signup", json={
            "email": f"x{uuid.uuid4().hex[:8]}@school.kz", "password": "password123",
            "role": "teacher", "staff_role": "admin",
        })
        assert response.status_code == 201
        user_id = response.json()["user"]["id"]
        stored = run_db(backend.db.db.users.find_one({"_id": ObjectId(user_id)}))
        assert "staff_role" not in stored
        assert anon_client.get("/api/admin/users").status_code == 404

    def test_the_profile_ignores_a_staff_role(self, backend, account):
        teacher = account()
        response = teacher.patch("/api/auth/profile", json={"name": "Жаңа", "staff_role": "admin"})
        assert response.status_code == 200
        stored = run_db(backend.db.db.users.find_one({"_id": ObjectId(teacher.user["id"])}))
        assert "staff_role" not in stored

    def test_me_tells_only_staff_about_their_role(self, account):
        teacher = account()
        assert "staff_role" not in teacher.get("/api/auth/me").json()["user"]

        support = account(staff_role="support")
        assert support.get("/api/auth/me").json()["user"]["staff_role"] == "support"


# ------------------------------------------------------------------ users --


def log_usage(backend, user_id, kind, at=None, **fields):
    doc = {"user_id": user_id, "kind": kind, "ok": True, "video": False, "cached": False,
           "at": at or datetime.now(timezone.utc), **fields}
    run_db(backend.db.db.usage_log.insert_one(doc))


class TestUsers:
    def test_search_finds_by_email_and_never_shows_a_password_hash(self, account):
        admin = account(staff_role="admin")
        target = account()

        body = admin.get("/api/admin/users", params={"q": target.user["email"]}).json()

        assert body["total"] == 1
        row = body["items"][0]
        assert row["id"] == target.user["id"]
        assert "password_hash" not in row

    def test_a_search_is_text_not_a_pattern(self, account):
        """`.*` must match those two characters, not every account."""
        admin = account(staff_role="support")
        body = admin.get("/api/admin/users", params={"q": ".*"}).json()
        assert body["total"] == 0

    def test_usage_is_counted_per_kind(self, backend, account):
        admin = account(staff_role="admin")
        target = account()
        uid = target.user["id"]
        log_usage(backend, uid, "explanation", video=True)
        log_usage(backend, uid, "explanation")
        log_usage(backend, uid, "explanation", cached=True, video=True)
        log_usage(backend, uid, "explanation", ok=False)
        log_usage(backend, uid, "assessment")
        log_usage(backend, uid, "lesson_plan")
        log_usage(backend, uid, "quiz_draft")
        run_db(backend.db.db.quizzes.insert_one(
            {"owner_id": uid, "created_at": datetime.now(timezone.utc)}))

        usage = admin.get(f"/api/admin/users/{uid}").json()["usage"]

        assert usage == {
            "explanations": 2, "videos": 1, "from_library": 1, "failed": 1,
            "assessments": 1, "lesson_plans": 1, "quiz_drafts": 1, "quizzes": 1,
        }

    def test_detail_has_quota_and_recent_activity(self, backend, account):
        admin = account(staff_role="support")
        target = account()
        log_usage(backend, target.user["id"], "assessment")

        detail = admin.get(f"/api/admin/users/{target.user['id']}").json()

        assert detail["quota"]["limit_day"] > 0
        assert detail["recent"][0]["kind"] == "assessment"
        assert detail["last_sign_in"]

    def test_an_unknown_or_malformed_id_is_404(self, account):
        admin = account(staff_role="admin")
        assert admin.get(f"/api/admin/users/{ObjectId()}").status_code == 404
        assert admin.get("/api/admin/users/not-an-id").status_code == 404


# ------------------------------------------------------------------ stats --


class TestStats:
    def test_today_counts_what_happened_today(self, backend, account):
        admin = account(staff_role="admin")
        before = admin.get("/api/admin/stats", params={"days": 7}).json()["days"][-1]

        account()  # one more signup today
        uid = admin.user["id"]
        log_usage(backend, uid, "explanation", video=True)
        log_usage(backend, uid, "assessment")

        body = admin.get("/api/admin/stats", params={"days": 7}).json()
        today = body["days"][-1]
        assert len(body["days"]) == 7
        assert today["signups"] == before["signups"] + 1
        assert today["videos"] == before["videos"] + 1
        assert today["assessments"] == before["assessments"] + 1
        assert body["usage_logged_since"]

    def test_older_events_land_on_their_own_day(self, backend, account):
        admin = account(staff_role="admin")
        three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
        before = admin.get("/api/admin/stats", params={"days": 7}).json()["days"][-4]

        log_usage(backend, admin.user["id"], "lesson_plan", at=three_days_ago)

        after = admin.get("/api/admin/stats", params={"days": 7}).json()["days"][-4]
        assert after["lesson_plans"] == before["lesson_plans"] + 1

    def test_days_are_clamped(self, account):
        admin = account(staff_role="admin")
        assert len(admin.get("/api/admin/stats", params={"days": 9999}).json()["days"]) == 90
        assert len(admin.get("/api/admin/stats", params={"days": 0}).json()["days"]) == 1


# ------------------------------------------------------------ the command --


@pytest.fixture
def staff_cli(backend):
    """Run `python -m app.staff ...` against the test database."""
    from app import staff

    def _run(*argv, answer="", interactive=False):
        out = io.StringIO()
        code = run_db(staff.run(list(argv), confirm=lambda _q: answer,
                                interactive=interactive, out=out))
        return code, out.getvalue()

    return _run


def stored(backend, user_id):
    return run_db(backend.db.db.users.find_one({"_id": ObjectId(user_id)}))


def audit_for(backend, user_id):
    return run_db(backend.db.db.admin_audit.find({"target.user_id": user_id}).to_list(None))


class TestStaffCommand:
    def test_reset_link_sets_a_new_password_without_mail(self, backend, account, staff_cli, anon_client):
        """For the admin who forgot it, or mail that never came."""
        person = account()
        code, out = staff_cli("reset-link", person.user["email"], "--reason", "забыл")
        assert code == 0, out
        link = next(line for line in out.splitlines() if "/reset-password?token=" in line)
        token = link.split("token=", 1)[1].strip()
        reset = anon_client.post("/api/auth/password/reset", json={"token": token, "password": "new-password-1"})
        assert reset.status_code == 200, reset.text
        assert anon_client.post("/api/auth/login", json={"email": person.user["email"],
                                                         "password": "new-password-1"}).status_code == 200
        assert [e["action"] for e in audit_for(backend, person.user["id"])] == ["password.reset_link"]
        # Once.
        assert anon_client.post("/api/auth/password/reset",
                                json={"token": token, "password": "another-pass-2"}).status_code == 400

    def test_reset_link_for_nobody(self, staff_cli):
        code, out = staff_cli("reset-link", "nobody-here@school.kz")
        assert code == 1 and "token=" not in out

    def test_grant_writes_the_role_and_the_audit_log(self, backend, account, staff_cli):
        person = account()
        code, out = staff_cli("grant", person.user["email"], "--role", "admin",
                              "--reason", "СТО", "--yes")

        assert code == 0, out
        assert stored(backend, person.user["id"])["staff_role"] == "admin"
        [entry] = audit_for(backend, person.user["id"])
        assert entry["action"] == "staff.grant"
        assert entry["actor"]["kind"] == "server"
        assert entry["details"] == {"role": "admin", "previous": None}
        assert entry["reason"] == "СТО"
        assert person.get("/api/admin/users").status_code == 200

    def test_without_a_terminal_it_will_not_guess_yes(self, backend, account, staff_cli):
        person = account()
        code, out = staff_cli("grant", person.user["email"], "--role", "admin")

        assert code == 2
        assert "--yes" in out
        assert "staff_role" not in stored(backend, person.user["id"])

    def test_it_shows_the_account_and_asks(self, backend, account, staff_cli):
        person = account()
        code, out = staff_cli("grant", person.user["email"], "--role", "support",
                              answer="n", interactive=True)

        assert code == 1
        assert person.user["email"] in out
        assert "staff_role" not in stored(backend, person.user["id"])

        code, _ = staff_cli("grant", person.user["email"], "--role", "support",
                            answer="y", interactive=True)
        assert code == 0
        assert stored(backend, person.user["id"])["staff_role"] == "support"

    def test_an_unknown_address_changes_nothing(self, staff_cli):
        code, out = staff_cli("grant", "nobody-here@school.kz", "--role", "admin", "--yes")
        assert code == 1
        assert "регистрируется" in out

    def test_the_address_is_matched_case_insensitively(self, backend, account, staff_cli):
        person = account()
        code, _ = staff_cli("grant", person.user["email"].upper(), "--role", "support", "--yes")
        assert code == 0
        assert stored(backend, person.user["id"])["staff_role"] == "support"

    def test_revoke_removes_the_role_and_is_logged(self, backend, account, staff_cli):
        person = account(staff_role="admin")
        code, _ = staff_cli("revoke", person.user["email"], "--yes")

        assert code == 0
        assert "staff_role" not in stored(backend, person.user["id"])
        assert audit_for(backend, person.user["id"])[-1]["action"] == "staff.revoke"
        assert person.get("/api/admin/users").status_code == 404

    def test_list_shows_staff_only(self, account, staff_cli):
        admin = account(staff_role="admin")
        teacher = account()
        code, out = staff_cli("list")
        assert code == 0
        assert admin.user["email"] in out
        assert teacher.user["email"] not in out

    def test_an_unknown_role_is_refused_by_the_parser(self, account, staff_cli):
        person = account()
        with pytest.raises(SystemExit):
            staff_cli("grant", person.user["email"], "--role", "root", "--yes")

    def test_grants_show_up_in_the_audit_route(self, account, staff_cli):
        admin = account(staff_role="admin")
        person = account()
        staff_cli("grant", person.user["email"], "--role", "support", "--yes")

        items = admin.get("/api/admin/audit").json()["items"]
        assert any(i["action"] == "staff.grant" and i["target"]["user_id"] == person.user["id"]
                   for i in items)


# ------------------------------------------------------ what gets counted --


class TestUsageIsLogged:
    def test_an_assessment_is_logged_once_it_exists(self, backend, account, monkeypatch):
        from app.api.assessments import assessment_limiter
        from app.ws.manager import agent_manager

        assessment_limiter._attempts.clear()

        async def fake(spec, timeout):
            return {"questions": [{"text": "Сұрақ бірінші", "marks": 1}], "total_marks": 1}

        monkeypatch.setattr(agent_manager, "request_assessment", fake)
        teacher = account()
        response = teacher.post("/api/assessments", json={
            "subject": "physics", "grade": 8, "topic": "Ньютон заңдары",
            "type": "sor", "difficulty": "medium", "lang": "kk", "count": 1,
        })
        assert response.status_code == 201, response.text

        logged = run_db(backend.db.db.usage_log.find({"user_id": teacher.user["id"]}).to_list(None))
        assert [e["kind"] for e in logged] == ["assessment"]

    def test_a_failed_assessment_is_not_logged(self, backend, account, monkeypatch):
        from app.api.assessments import assessment_limiter
        from app.ws.manager import agent_manager

        assessment_limiter._attempts.clear()

        async def fake(spec, timeout):
            return {"error": "llm_failed"}

        monkeypatch.setattr(agent_manager, "request_assessment", fake)
        teacher = account()
        response = teacher.post("/api/assessments", json={
            "subject": "physics", "grade": 8, "topic": "Ньютон заңдары",
            "type": "sor", "difficulty": "medium", "lang": "kk", "count": 1,
        })
        assert response.status_code >= 400

        assert run_db(backend.db.db.usage_log.count_documents({"user_id": teacher.user["id"]})) == 0

    @pytest.mark.parametrize("reply, expected", [
        ({"status": "complete", "text": "жауап", "video_path": "rendered_1.mp4"},
         {"ok": True, "video": True, "cached": False}),
        ({"status": "complete", "text": "тек мәтін", "video_path": ""},
         {"ok": True, "video": False, "cached": False}),
        ({"status": "error", "error": "render failed"},
         {"ok": False, "video": False, "cached": False}),
    ])
    def test_an_explanation_is_logged_as_it_ended(
        self, backend, client, new_user, agent_secret, reply, expected
    ):
        """Through the real sockets: the user asks, the agent answers."""
        user_id = new_user()["id"]
        question = f"тест сұрағы {uuid.uuid4().hex[:8]}"  # unique: no cache hit
        with client.websocket_connect("/ws/agent") as agent:
            agent.send_json({"type": "auth", "token": agent_secret})
            assert agent.receive_json().get("type") == "auth_ok"
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "create_chat", "data": {"title": "t"}})
                chat_id = ws.receive_json()["data"]["id"]
                ws.send_json({"type": "user_message", "data": {"chat_id": chat_id, "prompt": question}})
                assert ws.receive_json().get("type") == "message_received"
                request_id = agent.receive_json()["request_id"]
                agent.send_json({"request_id": request_id, **reply})
                ws.receive_json()

        [entry] = run_db(backend.db.db.usage_log.find({"user_id": user_id}).to_list(None))
        assert entry["kind"] == "explanation"
        assert {k: entry[k] for k in expected} == expected

    def test_the_log_never_breaks_the_request_it_describes(self, backend, monkeypatch):
        from app.services import usage_log

        class Broken:
            async def insert_one(self, doc):
                raise RuntimeError("disk full")

        monkeypatch.setattr(backend.db.db, "usage_log", Broken(), raising=False)
        run_db(usage_log.log("u1", "assessment"))  # must not raise
