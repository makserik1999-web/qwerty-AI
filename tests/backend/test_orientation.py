"""Portrait (9:16) videos: asked for, carried to the agent, filed apart.

A phone video and a classroom video of the same question are two different
videos, so the choice is in the wording cache's key and the topic library
keeps the two on separate shelves. Landscape stays what every video before
the choice was: no field, no key fragment, every old entry still reachable.
"""

import asyncio
import uuid

import pytest

TOPIC = "geom-8-pythagoras"


def run_db(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clean(backend):
    for name in ("video_cache", "library_entries", "question_stats"):
        run_db(backend.db.db[name].delete_many({}))
    yield
    run_db(backend.db.db.video_cache.delete_many({}))


def _file(backend, orientation=None):
    from app.services import topic_cache

    name = f"or_{uuid.uuid4().hex[:6]}.mp4"
    (backend.MEDIA_DIR / name).write_bytes(b"v")
    extra = {"orientation": orientation} if orientation else {}
    return run_db(topic_cache.add(topic_id=TOPIC, lang="kk", video_url=f"/media/{name}", text="t",
                                  user_id="u", duration=1.0, has_audio=True, **extra))


class TestTheKey:
    def test_portrait_is_its_own_variant(self, backend):
        from app.services.cache_service import render_variant

        landscape = render_variant(True, "aigul", "medium", "medium", "kk")
        assert render_variant(True, "aigul", "medium", "medium", "kk", "landscape") == landscape
        assert render_variant(True, "aigul", "medium", "medium", "kk", "portrait") == landscape + ",frame=portrait"


class TestTheShelves:
    def test_each_orientation_is_served_its_own(self, backend):
        from app.services import topic_cache

        flat = _file(backend)
        tall = _file(backend, "portrait")
        assert str(run_db(topic_cache.best(TOPIC, "kk"))["_id"]) == flat
        assert str(run_db(topic_cache.best(TOPIC, "kk", orientation="portrait"))["_id"]) == tall

    def test_no_portrait_video_means_a_render(self, backend):
        from app.services import topic_cache

        _file(backend)
        assert run_db(topic_cache.best(TOPIC, "kk", orientation="portrait")) is None

    def test_phone_videos_do_not_take_the_classroom_places(self, backend):
        for _ in range(3):
            assert _file(backend)
        assert _file(backend, "portrait") is not None
        assert _file(backend) is None  # the landscape shelf is full

    def test_the_library_says_which_way_up(self, backend):
        from app.services import topic_cache

        entry = run_db(topic_cache.get(_file(backend, "portrait")))
        assert topic_cache.public_view(entry)["orientation"] == "portrait"


class TestTheRequest:
    def _ask(self, client, agent_secret, **extra):
        with client.websocket_connect("/ws/agent") as agent:
            agent.send_json({"type": "auth", "token": agent_secret})
            assert agent.receive_json().get("type") == "auth_ok"
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "create_chat", "data": {"title": "t"}})
                chat_id = ws.receive_json()["data"]["id"]
                ws.send_json({"type": "user_message", "data": {
                    "chat_id": chat_id, "prompt": f"сұрақ {uuid.uuid4().hex[:8]}", **extra}})
                assert ws.receive_json()["type"] == "message_received"
                sent = agent.receive_json()
                agent.send_json({"request_id": sent["request_id"], "status": "error", "error": "x"})
                ws.receive_json()
                return sent

    def test_portrait_reaches_the_agent(self, client, new_user, agent_secret):
        new_user()
        assert self._ask(client, agent_secret, orientation="portrait")["orientation"] == "portrait"

    def test_landscape_and_nonsense_send_nothing(self, client, new_user, agent_secret):
        new_user()
        assert "orientation" not in self._ask(client, agent_secret)
        assert "orientation" not in self._ask(client, agent_secret, orientation="diagonal")
