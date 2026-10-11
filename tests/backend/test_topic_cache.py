"""Videos filed by topic, served instead of rendering, rated, and moderated.

The agent here is a test socket that answers the backend's "classify"
request and its render request by hand, so each test says exactly what the
classifier decided and what came back.
"""

import asyncio
import uuid

import pytest
from bson import ObjectId

TOPIC = "geom-8-pythagoras"


def run_db(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clean(backend):
    # The wording cache answers a repeated question before the topic layer is
    # even asked, so it is emptied too - these tests are about topics.
    for name in ("video_cache", "video_ratings", "library_entries", "question_stats"):
        run_db(backend.db.db[name].delete_many({}))
    yield
    run_db(backend.db.db.video_cache.delete_many({}))


@pytest.fixture
def media(backend):
    """Make video files exist, so the cache will serve them."""

    def _make(name):
        (backend.MEDIA_DIR / name).write_bytes(b"video")
        return name

    return _make


def ask(client, agent_secret, question, *, classification, reply=None, force=False):
    """One question through /ws with a classifying agent. Returns (frames the
    asker got, the render request the agent got or None).

    `reply` is the agent's answer to a render; without one the test expects
    the question to be answered from the cache and never reach the renderer.
    """
    # Each wording once: a repeated one is answered by the wording cache
    # before the topic layer is asked, and these tests are about topics.
    question = f"{question} {uuid.uuid4().hex[:6]}"
    with client.websocket_connect("/ws/agent") as agent:
        agent.send_json({"type": "auth", "token": agent_secret, "features": ["classify", "ack"]})
        assert agent.receive_json().get("type") == "auth_ok"
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "create_chat", "data": {"title": "t"}})
            chat_id = ws.receive_json()["data"]["id"]
            ws.send_json({"type": "user_message", "data": {
                "chat_id": chat_id, "prompt": question, **({"force_regenerate": True} if force else {})}})
            asked = agent.receive_json()
            assert asked["type"] == "classify"
            agent.send_json({"type": "classify_result", "request_id": asked["request_id"], **classification})
            first = ws.receive_json()
            if first.get("type") != "message_received":
                return [first], None
            if reply is None:
                return [first, ws.receive_json()], None
            render = agent.receive_json()
            agent.send_json({"type": "ack", "request_id": render["request_id"]})
            agent.send_json({"request_id": render["request_id"], **reply})
            return [first, ws.receive_json()], render


GENERIC = {"specificity": "generic", "topic_id": TOPIC, "language": "kk"}
SPECIFIC = {"specificity": "specific", "topic_id": TOPIC, "language": "kk"}


def done(video):
    return {"status": "complete", "text": "Пифагор теоремасы...", "video_path": video,
            "duration": 42.0, "has_audio": True}


class TestFilingAndServing:
    def test_a_general_question_is_rendered_then_filed(self, backend, client, new_user, agent_secret, media):
        new_user()
        frames, render = ask(client, agent_secret, "Пифагор теоремасы деген не?",
                             classification=GENERIC, reply=done(media("pyth_a.mp4")))
        assert render is not None
        answer = frames[-1]["data"]
        assert answer["video_cache_id"]
        entry = run_db(backend.db.db.video_cache.find_one({"_id": ObjectId(answer["video_cache_id"])}))
        assert entry["topic_id"] == TOPIC and entry["status"] == "cached" and entry["lang"] == "kk"
        assert entry["duration"] == 42.0 and entry["has_audio"] is True
        assert entry["title"] == "Пифагор теоремасы"

    def test_the_next_general_question_gets_the_filed_video(self, backend, client, new_user, agent_secret, media):
        new_user()
        ask(client, agent_secret, "Пифагор теоремасы деген не?", classification=GENERIC,
            reply=done(media("pyth_b.mp4")))
        frames, render = ask(client, agent_secret, "Пифагор теоремасын түсіндірші", classification=GENERIC)
        assert render is None
        answer = frames[-1]["data"]
        assert answer["from_cache"] is True and answer["cache_match"] == "topic"
        assert answer["video_url"] == "/media/pyth_b.mp4"
        assert answer["matched_question"] == "Пифагор теоремасы"

    def test_a_specific_question_is_never_filed_or_served(self, backend, client, new_user, agent_secret, media):
        new_user()
        ask(client, agent_secret, "Пифагор теоремасы деген не?", classification=GENERIC,
            reply=done(media("pyth_c.mp4")))
        frames, render = ask(client, agent_secret, "Катеттері 3 және 4, гипотенузасы қанша?",
                             classification=SPECIFIC, reply=done(media("pyth_spec.mp4")))
        assert render is not None
        assert "video_cache_id" not in frames[-1]["data"]
        assert run_db(backend.db.db.video_cache.count_documents({})) == 1

    def test_my_own_new_one_renders_even_when_one_is_filed(self, backend, client, new_user, agent_secret, media):
        new_user()
        ask(client, agent_secret, "Пифагор?", classification=GENERIC, reply=done(media("pyth_d.mp4")))
        frames, render = ask(client, agent_secret, "Пифагор?", classification=GENERIC,
                             reply=done(media("pyth_e.mp4")), force=True)
        assert render is not None
        assert run_db(backend.db.db.video_cache.count_documents({"topic_id": TOPIC})) == 2

    def test_a_student_watches_a_filed_video_for_free(self, backend, client, new_user, agent_secret, media):
        new_user(role="teacher")
        ask(client, agent_secret, "Пифагор?", classification=GENERIC, reply=done(media("pyth_f.mp4")))
        new_user(role="student")
        frames, render = ask(client, agent_secret, "Пифагор теоремасы", classification=GENERIC)
        assert render is None and frames[-1]["type"] == "ai_response"

    def test_a_rejected_video_is_not_served(self, backend, client, new_user, agent_secret, media):
        new_user()
        ask(client, agent_secret, "Пифагор?", classification=GENERIC, reply=done(media("pyth_g.mp4")))
        run_db(backend.db.db.video_cache.update_many({}, {"$set": {"status": "rejected"}}))
        frames, render = ask(client, agent_secret, "Пифагор?", classification=GENERIC,
                             reply=done(media("pyth_h.mp4")))
        assert render is not None

    def test_a_video_whose_file_is_gone_is_skipped(self, backend, client, new_user, agent_secret, media):
        new_user()
        name = media("pyth_gone.mp4")
        ask(client, agent_secret, "Пифагор?", classification=GENERIC, reply=done(name))
        (backend.MEDIA_DIR / name).unlink()
        frames, render = ask(client, agent_secret, "Пифагор?", classification=GENERIC,
                             reply=done(media("pyth_i.mp4")))
        assert render is not None


class TestVersions:
    def _filed(self, backend, n, **fields):
        from app.services import topic_cache

        ids = []
        for _ in range(n):
            name = f"ver_{uuid.uuid4().hex[:6]}.mp4"
            (backend.MEDIA_DIR / name).write_bytes(b"v")
            ids.append(run_db(topic_cache.add(topic_id=TOPIC, lang="kk", video_url=f"/media/{name}",
                                              text="t", user_id="u", duration=1.0, has_audio=True)))
        if fields:
            run_db(backend.db.db.video_cache.update_one({"_id": ObjectId(ids[0])}, {"$set": fields}))
        return ids

    def test_three_versions_then_no_more(self, backend):
        ids = self._filed(backend, 4)
        assert ids[3] is None
        assert run_db(backend.db.db.video_cache.count_documents({"status": "cached"})) == 3

    def test_a_disliked_version_makes_room(self, backend):
        from app.services import topic_cache

        ids = self._filed(backend, 3, rating_down=2)
        new = run_db(topic_cache.add(topic_id=TOPIC, lang="kk", video_url="/media/rendered_1.mp4",
                                     text="t", user_id="u", duration=1.0, has_audio=True))
        assert new is not None
        replaced = run_db(backend.db.db.video_cache.find_one({"_id": ObjectId(ids[0])}))
        assert replaced["status"] == "rejected"

    def test_the_best_rated_is_served(self, backend):
        from app.services import topic_cache

        ids = self._filed(backend, 3)
        run_db(backend.db.db.video_cache.update_one({"_id": ObjectId(ids[1])}, {"$set": {"rating_up": 5}}))
        best = run_db(topic_cache.best(TOPIC, "kk"))
        assert str(best["_id"]) == ids[1]

    def test_another_language_is_another_shelf(self, backend):
        from app.services import topic_cache

        self._filed(backend, 1)
        assert run_db(topic_cache.best(TOPIC, "ru")) is None


class TestRating:
    def test_one_vote_per_person_and_it_can_change(self, backend, client, new_user):
        from app.services import topic_cache

        new_user()
        vid = run_db(topic_cache.add(topic_id=TOPIC, lang="kk", video_url="/media/rendered_1.mp4",
                                     text="t", user_id="u", duration=1.0, has_audio=True))
        assert client.post(f"/api/videos/{vid}/rate", json={"value": "up"}).json() == {"up": 1, "down": 0, "mine": 1}
        assert client.post(f"/api/videos/{vid}/rate", json={"value": "up"}).json()["up"] == 1
        assert client.post(f"/api/videos/{vid}/rate", json={"value": "down"}).json() == {"up": 0, "down": 1, "mine": -1}
        assert client.post(f"/api/videos/{vid}/rate", json={"value": "none"}).json() == {"up": 0, "down": 0, "mine": 0}

    def test_a_rejected_video_cannot_be_rated(self, backend, client, new_user):
        from app.services import topic_cache

        new_user()
        vid = run_db(topic_cache.add(topic_id=TOPIC, lang="kk", video_url="/media/rendered_1.mp4",
                                     text="t", user_id="u", duration=1.0, has_audio=True))
        run_db(backend.db.db.video_cache.update_one({"_id": ObjectId(vid)}, {"$set": {"status": "rejected"}}))
        assert client.post(f"/api/videos/{vid}/rate", json={"value": "up"}).status_code == 404


class TestModeration:
    @pytest.fixture
    def staff_client(self, backend):
        from fastapi.testclient import TestClient

        def _make(role):
            c = TestClient(backend.app)
            c.__enter__()
            r = c.post("/api/auth/signup", json={"email": f"m{uuid.uuid4().hex[:8]}@school.kz",
                                                 "password": "password123", "role": "teacher"})
            run_db(backend.db.db.users.update_one({"_id": ObjectId(r.json()["user"]["id"])},
                                                  {"$set": {"staff_role": role}}))
            return c

        return _make

    def _vid(self):
        from app.services import topic_cache

        return run_db(topic_cache.add(topic_id=TOPIC, lang="kk", video_url="/media/rendered_1.mp4",
                                      text="t", user_id="u", duration=1.0, has_audio=False))

    def test_support_publishes_and_it_reaches_the_showcase(self, backend, staff_client, client, new_user):
        support = staff_client("support")
        vid = self._vid()
        new_user(role="student")
        assert client.get("/api/showcase").json()["items"] == []
        assert support.post(f"/api/admin/videos/{vid}/publish", json={}).status_code == 200
        items = client.get("/api/showcase").json()["items"]
        assert [i["id"] for i in items] == [vid]
        assert run_db(backend.db.db.admin_audit.find_one({"action": "video.publish"}))

    def test_the_queue_and_the_silent_filter(self, staff_client):
        support = staff_client("support")
        vid = self._vid()
        body = support.get("/api/admin/videos", params={"status": "cached", "silent": True}).json()
        assert vid in [i["id"] for i in body["items"]] and body["counts"]["cached"] >= 1

    def test_a_wrong_topic_is_corrected(self, backend, staff_client):
        support = staff_client("support")
        vid = self._vid()
        response = support.put(f"/api/admin/videos/{vid}", json={"topic_id": "geom-8-pythagoras-converse"})
        assert response.status_code == 200
        assert response.json()["topic_id"] == "geom-8-pythagoras-converse"
        assert support.put(f"/api/admin/videos/{vid}", json={"topic_id": "made-up"}).status_code == 400

    def test_delete_removes_it_and_its_votes(self, backend, staff_client):
        support = staff_client("support")
        vid = self._vid()
        assert support.post(f"/api/admin/videos/{vid}/delete", json={}).status_code == 200
        assert run_db(backend.db.db.video_cache.count_documents({})) == 0

    def test_teachers_cannot_moderate(self, client, new_user):
        new_user()
        vid = self._vid()
        assert client.post(f"/api/admin/videos/{vid}/publish", json={}).status_code == 404


class TestTheTopicList:
    def test_the_agent_and_the_backend_have_the_same_list(self):
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        agent = json.loads((root / "agent/anyq/topics.json").read_text(encoding="utf-8"))
        backend = json.loads((root / "backend/app/data/topics.json").read_text(encoding="utf-8"))
        assert agent == backend, "edit agent/anyq/topics.json and backend/app/data/topics.json together"

    def test_ids_are_unique_and_well_formed(self):
        import json
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        topics = json.loads((root / "backend/app/data/topics.json").read_text(encoding="utf-8"))["topics"]
        ids = [t["id"] for t in topics]
        assert len(ids) == len(set(ids))
        for t in topics:
            assert re.fullmatch(r"[a-z]+-\d{1,2}-[a-z0-9-]+", t["id"]), t["id"]
            assert t["kk"] and t["ru"] and 5 <= t["grade"] <= 11
