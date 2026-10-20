"""The answer language a teacher chooses - Kazakh, Russian or English.

Chosen, it travels to the agent and into the cache key, so an English answer
is never handed a stored Kazakh video and the other way round. Not chosen,
nothing changes: the agent answers in the question's own language and the
key is the one every older entry was stored under.
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


def ask(client, agent_secret, question, *, language=None, features=("ack",), classification=None):
    """One question through /ws, answered by a test agent. Returns the render
    request the agent was sent and the answer the asker got."""
    with client.websocket_connect("/ws/agent") as agent:
        agent.send_json({"type": "auth", "token": agent_secret, "features": list(features)})
        assert agent.receive_json()["type"] == "auth_ok"
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "create_chat", "data": {"title": "t"}})
            chat_id = ws.receive_json()["data"]["id"]
            ws.send_json({"type": "user_message", "data": {
                "chat_id": chat_id, "prompt": question,
                **({"output_language": language} if language is not None else {})}})
            if classification is not None:
                asked = agent.receive_json()
                agent.send_json({"type": "classify_result", "request_id": asked["request_id"], **classification})
            first = ws.receive_json()
            assert first["type"] == "message_received", first
            frame = agent.receive_json()
            agent.send_json({"type": "ack", "request_id": frame["request_id"]})
            agent.send_json({"request_id": frame["request_id"], "status": "complete",
                             "text": "answer", "video_path": ""})
            return frame, ws.receive_json()


class TestTheChoiceTravels:
    def test_english_reaches_the_agent(self, client, new_user, agent_secret):
        new_user()
        frame, _ = ask(client, agent_secret, f"Why is the sky blue {uuid.uuid4().hex[:6]}", language="en")
        assert frame["output_language"] == "en"

    def test_no_choice_sends_nothing(self, client, new_user, agent_secret):
        """An older agent sees exactly the request it always did."""
        new_user()
        frame, _ = ask(client, agent_secret, f"Аспан неге көк {uuid.uuid4().hex[:6]}")
        assert "output_language" not in frame

    @pytest.mark.parametrize("bad", ["fr", "EN-us", "<script>", 7])
    def test_anything_else_is_the_questions_own_language(self, client, new_user, agent_secret, bad):
        new_user()
        frame, _ = ask(client, agent_secret, f"q {uuid.uuid4().hex[:6]}", language=bad)
        assert "output_language" not in frame


class TestTheCacheKeepsLanguagesApart:
    def test_the_variant_names_the_language(self, backend):
        from app.services import cache_service

        assert cache_service.render_variant(True, "aigul", "medium", "low", "en").endswith(",lang=en")

    def test_no_language_is_the_old_key(self, backend):
        from app.services import cache_service

        assert cache_service.render_variant(True, "aigul", "medium", "low") == \
            cache_service.render_variant(True, "aigul", "medium", "low", "")

    def test_a_topic_video_in_kazakh_is_not_served_to_an_english_request(self, backend, client, new_user,
                                                                         agent_secret):
        from app.services import topic_cache

        (backend.MEDIA_DIR / "rendered_kk_topic.mp4").write_bytes(b"video")
        run_db(topic_cache.add(topic_id=TOPIC, lang="kk", video_url="/media/rendered_kk_topic.mp4",
                               text="Пифагор", user_id="u", duration=40.0, has_audio=True))
        new_user()
        generic = {"specificity": "generic", "topic_id": TOPIC, "language": "kk"}
        # Asked in Kazakh, answer wanted in English: rendered, not served from the Kazakh shelf.
        frame, _ = ask(client, agent_secret, f"Пифагор теоремасы {uuid.uuid4().hex[:4]}", language="en",
                       features=("ack", "classify"), classification=generic)
        assert frame.get("output_language") == "en" and frame.get("text")
