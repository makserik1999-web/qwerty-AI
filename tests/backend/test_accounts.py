"""Real accounts: a confirmed email, a password that can be reset, Google, a phone.

Each flow is driven through the HTTP API the interface uses. Mail and SMS are
captured instead of sent, and Google's token endpoint is replaced by a
function returning the id_token Google would - everything after that point is
the real code.
"""

import asyncio
import base64
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from bson import ObjectId


def run_db(coro):
    return asyncio.run(coro)


@pytest.fixture
def outbox(backend, monkeypatch):
    """Every email the backend tries to send, as (to, subject, text)."""
    from app.services import mailer

    sent = []
    monkeypatch.setattr(mailer, "send_later",
                        lambda to, subject, text, html=None: sent.append((to, subject, text)))
    return sent


def link_token(text, path):
    match = re.search(rf"{re.escape(path)}\?token=([A-Za-z0-9_\-]+)", text)
    assert match, text
    return match.group(1)


@pytest.fixture
def account(backend):
    """A fresh TestClient signed up as a teacher; returns (client, user, password)."""
    from fastapi.testclient import TestClient

    opened = []

    def _make(email=None, role="teacher"):
        client = TestClient(backend.app)
        client.__enter__()
        opened.append(client)
        email = email or f"a{uuid.uuid4().hex[:10]}@school.kz"
        response = client.post("/api/auth/signup", json={
            "email": email, "password": "password123", "name": "Тест", "role": role})
        assert response.status_code == 201, response.text
        return client, response.json()["user"]

    yield _make
    for client in opened:
        client.__exit__(None, None, None)


def stored(backend, user_id):
    return run_db(backend.db.db.users.find_one({"_id": ObjectId(user_id)}))


# ------------------------------------------------------------ confirmation --


class TestEmailConfirmation:
    def test_signup_mails_a_link_and_the_account_starts_unconfirmed(self, account, outbox):
        client, user = account()
        assert user["email_verified"] is False
        [(to, _, text)] = [m for m in outbox if m[0] == user["email"]]
        assert "/verify-email?token=" in text

    def test_the_link_confirms_the_address_once(self, account, outbox, anon_client):
        client, user = account()
        token = link_token(outbox[-1][2], "/verify-email")

        # Opened somewhere with no session at all - a phone, usually.
        assert anon_client.post("/api/auth/email/verify", json={"token": token}).status_code == 200
        assert client.get("/api/auth/me").json()["user"]["email_verified"] is True

        again = anon_client.post("/api/auth/email/verify", json={"token": token})
        assert again.status_code == 400 and again.json()["code"] == "link_invalid"

    def test_a_made_up_token_is_refused(self, anon_client):
        response = anon_client.post("/api/auth/email/verify", json={"token": "x" * 43})
        assert response.status_code == 400

    def test_an_expired_link_is_refused(self, backend, account, outbox, anon_client):
        _, user = account()
        token = link_token(outbox[-1][2], "/verify-email")
        run_db(backend.db.db.auth_tokens.update_many(
            {"user_id": user["id"]},
            {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}}))
        assert anon_client.post("/api/auth/email/verify", json={"token": token}).status_code == 400

    def test_changing_the_address_unconfirms_it_and_mails_the_new_one(self, account, outbox, anon_client):
        client, user = account()
        old_token = link_token(outbox[-1][2], "/verify-email")
        anon_client.post("/api/auth/email/verify", json={"token": old_token})

        new_email = f"n{uuid.uuid4().hex[:8]}@school.kz"
        me = client.patch("/api/auth/profile", json={"email": new_email}).json()["user"]

        assert me["email_verified"] is False
        assert outbox[-1][0] == new_email

    def test_a_link_for_the_old_address_cannot_confirm_the_new_one(self, account, outbox, anon_client):
        client, user = account()
        old_token = link_token(outbox[-1][2], "/verify-email")
        client.patch("/api/auth/profile", json={"email": f"n{uuid.uuid4().hex[:8]}@school.kz"})

        response = anon_client.post("/api/auth/email/verify", json={"token": old_token})
        assert response.status_code == 400
        assert response.json()["code"] in ("link_stale", "link_invalid")
        assert client.get("/api/auth/me").json()["user"]["email_verified"] is False

    def test_resend_needs_a_session_and_is_rationed(self, account, outbox, anon_client):
        from app.api.email_auth import resend_limiter

        resend_limiter._attempts.clear()
        assert anon_client.post("/api/auth/email/resend").status_code == 401
        client, user = account()
        codes = [client.post("/api/auth/email/resend").status_code for _ in range(6)]
        assert codes[:5] == [200] * 5 and codes[5] == 429
        resend_limiter._attempts.clear()

    def test_resend_for_a_confirmed_address_sends_nothing(self, account, outbox, anon_client):
        client, user = account()
        anon_client.post("/api/auth/email/verify", json={"token": link_token(outbox[-1][2], "/verify-email")})
        before = len(outbox)
        assert client.post("/api/auth/email/resend").json()["already"] is True
        assert len(outbox) == before


class TestUnconfirmedCannotGenerate:
    """Only with REQUIRE_VERIFIED_EMAIL=1 - off, nothing changes."""

    SPEC = {"subject": "physics", "grade": 8, "topic": "Ньютон заңдары",
            "type": "sor", "difficulty": "medium", "lang": "kk", "count": 1}

    @pytest.fixture(autouse=True)
    def _agent(self, backend, monkeypatch):
        from app.api.assessments import assessment_limiter
        from app.ws.manager import agent_manager

        assessment_limiter._attempts.clear()

        async def fake(spec, timeout):
            return {"questions": [{"text": "Сұрақ бірінші", "marks": 1}], "total_marks": 1}

        monkeypatch.setattr(agent_manager, "request_assessment", fake)

    def test_off_by_default(self, account):
        client, _ = account()
        assert client.post("/api/assessments", json=self.SPEC).status_code == 201
        assert client.get("/api/auth/me").json()["user"]["verify_needed"] is False

    def test_on_the_app_is_told_to_show_only_the_confirm_page(self, backend, account, outbox,
                                                               anon_client, monkeypatch):
        monkeypatch.setattr(backend.config, "REQUIRE_VERIFIED_EMAIL", True)
        client, user = account()
        assert user["verify_needed"] is True
        assert client.get("/api/auth/me").json()["user"]["verify_needed"] is True
        anon_client.post("/api/auth/email/verify", json={"token": link_token(outbox[-1][2], "/verify-email")})
        assert client.get("/api/auth/me").json()["user"]["verify_needed"] is False

    def test_on_it_refuses_with_a_code(self, backend, account, monkeypatch):
        monkeypatch.setattr(backend.config, "REQUIRE_VERIFIED_EMAIL", True)
        client, _ = account()
        response = client.post("/api/assessments", json=self.SPEC)
        assert response.status_code == 403
        assert response.json()["code"] == "email_unverified"

    def test_on_a_confirmed_account_goes_through(self, backend, account, outbox, anon_client, monkeypatch):
        monkeypatch.setattr(backend.config, "REQUIRE_VERIFIED_EMAIL", True)
        client, _ = account()
        anon_client.post("/api/auth/email/verify", json={"token": link_token(outbox[-1][2], "/verify-email")})
        assert client.post("/api/assessments", json=self.SPEC).status_code == 201

    def test_on_the_video_socket_refuses_with_a_code(self, backend, account, monkeypatch):
        from app.ws.manager import agent_manager

        monkeypatch.setattr(backend.config, "REQUIRE_VERIFIED_EMAIL", True)
        sent = []

        async def fake_send(**kwargs):
            sent.append(kwargs)

        monkeypatch.setattr(agent_manager, "send_to_agent", fake_send)
        client, _ = account()
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "create_chat", "data": {"title": "t"}})
            chat_id = ws.receive_json()["data"]["id"]
            ws.send_json({"type": "user_message", "data": {
                "chat_id": chat_id, "prompt": f"сұрақ {uuid.uuid4().hex[:6]}"}})
            frame = ws.receive_json()
        assert frame["data"]["code"] == "email_unverified"
        assert sent == []


# ------------------------------------------------------------------ reset --


class TestPasswordReset:
    @pytest.fixture(autouse=True)
    def _limits(self, backend):
        from app.api.email_auth import forgot_email_limiter, forgot_ip_limiter

        forgot_email_limiter._attempts.clear()
        forgot_ip_limiter._attempts.clear()
        yield
        forgot_email_limiter._attempts.clear()
        forgot_ip_limiter._attempts.clear()

    def test_an_unknown_address_gets_the_same_answer_and_no_mail(self, anon_client, outbox):
        response = anon_client.post("/api/auth/password/forgot", json={"email": "nobody@school.kz"})
        assert response.status_code == 200 and response.json() == {"ok": True}
        assert outbox == []

    def test_the_link_sets_a_new_password_and_ends_other_sessions(self, account, outbox, anon_client):
        client, user = account()
        anon_client.post("/api/auth/password/forgot", json={"email": user["email"]})
        token = link_token(outbox[-1][2], "/reset-password")

        response = anon_client.post("/api/auth/password/reset", json={"token": token, "password": "newpass456"})

        assert response.status_code == 200
        # The browser that reset it is signed in; the old session is gone.
        assert anon_client.get("/api/auth/me").status_code == 200
        assert client.get("/api/auth/me").status_code == 401
        assert response.json()["user"]["email_verified"] is True
        login = anon_client.post("/api/auth/login", json={"email": user["email"], "password": "password123"})
        assert login.status_code == 401
        login = anon_client.post("/api/auth/login", json={"email": user["email"], "password": "newpass456"})
        assert login.status_code == 200

    def test_a_link_works_once(self, account, outbox, anon_client):
        _, user = account()
        anon_client.post("/api/auth/password/forgot", json={"email": user["email"]})
        token = link_token(outbox[-1][2], "/reset-password")
        assert anon_client.post("/api/auth/password/reset", json={"token": token, "password": "newpass456"}).status_code == 200
        again = anon_client.post("/api/auth/password/reset", json={"token": token, "password": "another789"})
        assert again.status_code == 400

    def test_a_short_password_is_refused_before_the_link_is_spent(self, account, outbox, anon_client):
        _, user = account()
        anon_client.post("/api/auth/password/forgot", json={"email": user["email"]})
        token = link_token(outbox[-1][2], "/reset-password")
        short = anon_client.post("/api/auth/password/reset", json={"token": token, "password": "short"})
        assert short.status_code == 400
        ok = anon_client.post("/api/auth/password/reset", json={"token": token, "password": "longenough1"})
        assert ok.status_code == 200

    def test_requests_are_rationed_per_address(self, account, anon_client, outbox):
        _, user = account()
        codes = [anon_client.post("/api/auth/password/forgot", json={"email": user["email"]}).status_code
                 for _ in range(4)]
        assert codes == [200, 200, 200, 429]


# ----------------------------------------------------------------- Google --


CLIENT_ID = "test-client.apps.googleusercontent.com"


def make_id_token(**claims):
    def part(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{part({'alg': 'RS256'})}.{part(claims)}.signature"


@pytest.fixture
def google(backend, monkeypatch):
    """Google configured, with its token endpoint answering what we choose."""
    from app.api import google_auth

    monkeypatch.setattr(backend.config, "GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(backend.config, "GOOGLE_CLIENT_SECRET", "secret")
    answer = {}

    async def fake_exchange(code, verifier):
        assert code == "the-code"
        assert verifier  # PKCE verifier from the stored flow
        return {"id_token": make_id_token(**answer["claims"](answer["nonce"]))}

    monkeypatch.setattr(google_auth, "exchange_code", fake_exchange)
    return answer


def google_round_trip(client, backend, google, *, email, sub=None, role="", name="Айгүл", **overrides):
    """start -> (Google) -> callback; returns the callback response."""
    start = client.get("/api/auth/google/start", params={"role": role}, follow_redirects=False)
    assert start.status_code == 302
    params = parse_qs(urlparse(start.headers["location"]).query)
    state, nonce = params["state"][0], params["nonce"][0]
    google["nonce"] = nonce

    def claims(n):
        base = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": sub or uuid.uuid4().hex,
                "email": email, "email_verified": True, "name": name, "exp": time.time() + 600, "nonce": n}
        base.update(overrides)
        return base

    google["claims"] = claims
    return client.get("/api/auth/google/callback", params={"code": "the-code", "state": state},
                      follow_redirects=False)


class TestGoogle:
    def test_not_offered_until_configured(self, anon_client):
        assert anon_client.get("/api/auth/providers").json()["google"] is False
        assert anon_client.get("/api/auth/google/start", follow_redirects=False).status_code == 404

    def test_start_sends_the_browser_to_google_with_pkce(self, backend, anon_client, google):
        response = anon_client.get("/api/auth/google/start", follow_redirects=False)
        location = urlparse(response.headers["location"])
        params = parse_qs(location.query)
        assert location.netloc == "accounts.google.com"
        assert params["client_id"] == [CLIENT_ID]
        assert params["code_challenge_method"] == ["S256"]
        assert params["redirect_uri"][0].endswith("/api/auth/google/callback")
        assert "anyq_oauth_state=" in response.headers["set-cookie"]

    def test_a_new_teacher_is_created_confirmed_and_signed_in(self, backend, anon_client, google):
        email = f"g{uuid.uuid4().hex[:8]}@gmail.com"
        response = google_round_trip(anon_client, backend, google, email=email, role="teacher")

        assert response.status_code == 302 and response.headers["location"] == "/app/explain"
        me = anon_client.get("/api/auth/me").json()["user"]
        assert me["email"] == email and me["role"] == "teacher"
        assert me["email_verified"] is True and me["has_password"] is False

    def test_without_a_role_a_new_person_is_sent_to_sign_up(self, backend, anon_client, google):
        email = f"g{uuid.uuid4().hex[:8]}@gmail.com"
        response = google_round_trip(anon_client, backend, google, email=email)
        assert "/signup?auth_error=google_choose_role" in response.headers["location"]
        assert run_db(backend.db.db.users.find_one({"email": email})) is None

    def test_the_same_google_account_signs_into_the_same_account(self, backend, anon_client, google):
        email, sub = f"g{uuid.uuid4().hex[:8]}@gmail.com", uuid.uuid4().hex
        google_round_trip(anon_client, backend, google, email=email, sub=sub, role="teacher")
        first = anon_client.get("/api/auth/me").json()["user"]["id"]
        anon_client.post("/api/auth/logout")
        google_round_trip(anon_client, backend, google, email=email, sub=sub)
        assert anon_client.get("/api/auth/me").json()["user"]["id"] == first

    def test_an_unconfirmed_account_with_that_address_is_taken_over_clean(
        self, backend, account, anon_client, google
    ):
        """Someone registered your address first and set a password. Google proves
        it is yours: you get the account, their password and sessions do not."""
        squatter, user = account()
        google_round_trip(anon_client, backend, google, email=user["email"])

        assert anon_client.get("/api/auth/me").json()["user"]["id"] == user["id"]
        assert squatter.get("/api/auth/me").status_code == 401
        assert "password_hash" not in stored(backend, user["id"])

    def test_a_confirmed_account_is_linked_and_keeps_its_password(
        self, backend, account, outbox, anon_client, google
    ):
        owner, user = account()
        anon_client.post("/api/auth/email/verify", json={"token": link_token(outbox[-1][2], "/verify-email")})
        google_round_trip(anon_client, backend, google, email=user["email"])

        assert owner.get("/api/auth/me").status_code == 200
        assert stored(backend, user["id"]).get("password_hash")

    def test_a_state_that_is_not_this_browsers_is_refused(self, backend, anon_client, google):
        anon_client.get("/api/auth/google/start", follow_redirects=False)
        response = anon_client.get("/api/auth/google/callback",
                                   params={"code": "the-code", "state": "someone-elses"},
                                   follow_redirects=False)
        assert "auth_error=google_state" in response.headers["location"]

    @pytest.mark.parametrize("override, reason", [
        ({"aud": "another-app"}, "audience"),
        ({"iss": "https://evil.example"}, "issuer"),
        ({"email_verified": False}, "email_unverified"),
        ({"exp": time.time() - 3600}, "expired"),
    ])
    def test_bad_claims_are_refused(self, backend, anon_client, google, override, reason):
        response = google_round_trip(anon_client, backend, google,
                                     email=f"g{uuid.uuid4().hex[:8]}@gmail.com", role="teacher", **override)
        assert "auth_error=google_failed" in response.headers["location"]
        assert anon_client.get("/api/auth/me").status_code == 401

    def test_a_wrong_nonce_is_refused(self, backend):
        from app.api.google_auth import check_claims

        backend.config.GOOGLE_CLIENT_ID = CLIENT_ID
        try:
            claims = {"iss": "accounts.google.com", "aud": CLIENT_ID, "sub": "1", "email": "a@b.kz",
                      "email_verified": True, "exp": time.time() + 60, "nonce": "one"}
            assert check_claims(claims, "one") is None
            assert check_claims(claims, "two") == "nonce"
        finally:
            backend.config.GOOGLE_CLIENT_ID = ""

    @pytest.mark.parametrize("value", ["//evil.example/x", "https://evil.example", "/\\evil"])
    def test_next_cannot_leave_the_site(self, value):
        from app.api.google_auth import _safe_next

        assert _safe_next(value) == "/app/explain"


# ------------------------------------------------------------------ phone --


@pytest.fixture
def texts(backend, monkeypatch):
    """Every SMS sent, as (phone, text)."""
    from app.services import sms

    sent = []

    async def fake(phone, text):
        sent.append((phone, text))
        return True

    monkeypatch.setattr(sms, "send", fake)
    return sent


def sent_code(texts):
    return re.search(r"\b(\d{6})\b", texts[-1][1]).group(1)


def free_number():
    return "+7 707 " + f"{uuid.uuid4().int % 10_000_000:07d}"


class TestPhoneNumbers:
    @pytest.mark.parametrize("raw, expected", [
        ("+7 (707) 123-45-67", "77071234567"),
        ("87071234567", "77071234567"),
        ("7071234567", "77071234567"),
        ("77471234567", "77471234567"),
        ("+7 912 345 67 89", None),   # Russia: not sent, not a KZ mobile
        ("12345", None),
        ("+1 202 555 0100", None),
    ])
    def test_normalize(self, raw, expected):
        from app.services.sms import normalize_phone

        assert normalize_phone(raw) == expected


class TestPhoneConfirmation:
    def test_a_code_confirms_the_number(self, account, texts):
        client, _ = account()
        phone = free_number()
        start = client.post("/api/auth/phone/start", json={"phone": phone})
        assert start.status_code == 200, start.text

        response = client.post("/api/auth/phone/verify", json={"phone": phone, "code": sent_code(texts)})

        assert response.status_code == 200
        me = client.get("/api/auth/me").json()["user"]
        assert me["phone_verified"] is True and me["phone"].startswith("77")

    def test_a_wrong_code_counts_down_and_then_stops(self, account, texts):
        client, _ = account()
        phone = free_number()
        client.post("/api/auth/phone/start", json={"phone": phone})
        right = sent_code(texts)
        wrong = "000000" if right != "000000" else "111111"
        answers = [client.post("/api/auth/phone/verify", json={"phone": phone, "code": wrong}) for _ in range(5)]
        assert [a.json()["attempts_left"] for a in answers] == [4, 3, 2, 1, 0]
        final = client.post("/api/auth/phone/verify", json={"phone": phone, "code": right})
        assert final.status_code == 429  # even the right code: the record is spent

    def test_asking_again_within_a_minute_is_refused(self, account, texts):
        client, _ = account()
        phone = free_number()
        client.post("/api/auth/phone/start", json={"phone": phone})
        again = client.post("/api/auth/phone/start", json={"phone": phone})
        assert again.status_code == 429 and again.json()["code"] == "sms_wait"
        assert len(texts) == 1

    def test_a_number_belongs_to_one_account(self, account, texts):
        first, _ = account()
        second, _ = account()
        phone = free_number()
        first.post("/api/auth/phone/start", json={"phone": phone})
        first.post("/api/auth/phone/verify", json={"phone": phone, "code": sent_code(texts)})

        response = second.post("/api/auth/phone/start", json={"phone": phone})
        assert response.status_code == 409 and response.json()["code"] == "phone_taken"

    def test_a_foreign_number_is_never_texted(self, account, texts):
        client, _ = account()
        response = client.post("/api/auth/phone/start", json={"phone": "+44 7700 900123"})
        assert response.status_code == 400 and response.json()["code"] == "phone_invalid"
        assert texts == []

    def test_the_daily_cap_stops_everyone(self, backend, account, texts, monkeypatch):
        monkeypatch.setattr(backend.config, "SMS_DAILY_MAX", 0)
        client, _ = account()
        response = client.post("/api/auth/phone/start", json={"phone": free_number()})
        assert response.status_code == 503 and response.json()["code"] == "sms_paused"
        assert texts == []

    def test_only_a_hash_of_the_code_is_stored(self, backend, account, texts):
        client, user = account()
        client.post("/api/auth/phone/start", json={"phone": free_number()})
        record = run_db(backend.db.db.phone_codes.find_one({"user_id": user["id"]}))
        assert sent_code(texts) not in json.dumps(record, default=str)

    def test_it_needs_a_session(self, anon_client, texts):
        assert anon_client.post("/api/auth/phone/start", json={"phone": free_number()}).status_code == 401


class TestSmsProviders:
    def test_smsc_request_and_reply(self, backend, monkeypatch):
        from app.services import sms

        monkeypatch.setattr(backend.config, "SMSC_LOGIN", "akron")
        monkeypatch.setattr(backend.config, "SMSC_PASSWORD", "pw")
        params = sms._smsc_params("77071234567", "код 123456")
        assert params["phones"] == "77071234567" and params["fmt"] == "3" and params["charset"] == "utf-8"
        assert sms._smsc_ok({"id": 5, "cnt": 1})
        assert not sms._smsc_ok({"error": "no money", "error_code": 3})

    def test_mobizon_request_and_reply(self, backend, monkeypatch):
        from app.services import sms

        monkeypatch.setattr(backend.config, "MOBIZON_API_KEY", "key")
        params = sms._mobizon_params("77071234567", "код 123456")
        assert params["recipient"] == "77071234567" and params["apiKey"] == "key"
        assert sms._mobizon_ok({"code": 0, "data": {"messageId": "1"}})
        assert not sms._mobizon_ok({"code": 1, "message": "Invalid recipient"})

    def test_a_provider_without_credentials_does_not_send(self, backend, monkeypatch):
        from app.services import sms

        monkeypatch.setattr(backend.config, "SMS_PROVIDER", "smsc")
        monkeypatch.setattr(backend.config, "SMSC_LOGIN", "")
        assert sms.configured() is False
        assert run_db(sms.send("77071234567", "x")) is False


class TestDeletingAnAccountFreesItsNumber:
    def test_the_number_can_be_confirmed_again(self, account, texts):
        first, _ = account()
        phone = free_number()
        first.post("/api/auth/phone/start", json={"phone": phone})
        first.post("/api/auth/phone/verify", json={"phone": phone, "code": sent_code(texts)})
        first.delete("/api/auth/account")

        second, _ = account()
        assert second.post("/api/auth/phone/start", json={"phone": phone}).status_code == 200
