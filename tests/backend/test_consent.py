"""Agreeing to the privacy policy: on the sign-up form, or once inside the app.

What is kept is which version was agreed to and when. An account that has not
agreed to the current version is told so on every /me, and the app asks
before anything else.
"""

import asyncio
import uuid

from bson import ObjectId


def run_db(coro):
    return asyncio.run(coro)


def signup(client, **extra):
    response = client.post("/api/auth/signup", json={
        "email": f"c{uuid.uuid4().hex[:10]}@school.kz", "password": "password123",
        "role": "teacher", **extra})
    assert response.status_code == 201, response.text
    return response.json()["user"]


class TestOnTheForm:
    def test_ticking_the_box_is_recorded_with_the_version(self, backend, client):
        user = signup(client, consent=True)
        assert user["consent_needed"] is False
        stored = run_db(backend.db.db.users.find_one({"_id": ObjectId(user["id"])}))
        assert stored["consent"]["version"] == backend.config.PRIVACY_POLICY_VERSION
        assert stored["consent"]["at"]

    def test_without_it_the_app_is_told_to_ask(self, client):
        assert signup(client)["consent_needed"] is True
        assert client.get("/api/auth/me").json()["user"]["consent_needed"] is True


class TestInsideTheApp:
    def test_agreeing_later_clears_it(self, client):
        signup(client)
        agreed = client.post("/api/auth/consent")
        assert agreed.status_code == 200 and agreed.json()["user"]["consent_needed"] is False
        assert client.get("/api/auth/me").json()["user"]["consent_needed"] is False

    def test_a_new_policy_version_asks_again(self, backend, client, monkeypatch):
        signup(client, consent=True)
        monkeypatch.setattr(backend.config, "PRIVACY_POLICY_VERSION", "2099-01-01")
        from app.security import sessions

        monkeypatch.setattr(sessions, "PRIVACY_POLICY_VERSION", "2099-01-01")
        assert client.get("/api/auth/me").json()["user"]["consent_needed"] is True

    def test_nobody_agrees_without_an_account(self, anon_client):
        assert anon_client.post("/api/auth/consent").status_code == 401


class TestGoogle:
    def test_the_box_travels_through_google(self, backend, anon_client, monkeypatch):
        monkeypatch.setattr(backend.config, "GOOGLE_CLIENT_ID", "id")
        monkeypatch.setattr(backend.config, "GOOGLE_CLIENT_SECRET", "secret")
        before = run_db(backend.db.db.oauth_states.count_documents({}))
        anon_client.get("/api/auth/google/start?role=teacher&consent=1", follow_redirects=False)
        anon_client.get("/api/auth/google/start?role=teacher", follow_redirects=False)
        states = run_db(backend.db.db.oauth_states.find({}).sort("created_at", -1).to_list(None))
        assert len(states) == before + 2
        assert [s["consent"] for s in states[:2]] == [False, True]


class TestDeletion:
    def test_library_videos_lose_their_author(self, backend, client):
        user = signup(client, consent=True)
        run_db(backend.db.db.video_cache.insert_one({"topic_id": "t", "user_id": user["id"], "status": "cached"}))
        assert client.delete("/api/auth/account").status_code in (200, 204)
        assert run_db(backend.db.db.video_cache.count_documents({"user_id": user["id"]})) == 0
