"""Only teachers start a generation; anyone gets what the library already has.

Before this, a student account made videos like a teacher's - a paid model
call each time, with the price shown to nobody. Watching is free and making is
not, so a student's question is answered from the library when it can be and
refused with a code the interface translates when it cannot.
"""

import asyncio
import uuid

import pytest


def run_db(coro):
    return asyncio.run(coro)


def ask(client, question, frames_expected=1):
    """Send one question over /ws and return the first frames that come back.

    Reads exactly as many as asked for: with the agent faked out, a request
    that reached it never gets an answer, and one more read would block.
    """
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_chat", "data": {"title": "t"}})
        chat_id = ws.receive_json()["data"]["id"]
        ws.send_json({"type": "user_message", "data": {"chat_id": chat_id, "prompt": question}})
        return chat_id, [ws.receive_json() for _ in range(frames_expected)]


class TestAStudent:
    def test_is_refused_a_new_generation_with_a_code(self, backend, client, new_user, monkeypatch):
        from app.ws.manager import agent_manager

        sent = []

        async def fake_send(**kwargs):
            sent.append(kwargs)

        monkeypatch.setattr(agent_manager, "send_to_agent", fake_send)
        student = new_user(role="student")

        chat_id, frames = ask(client, f"неге аспан көк {uuid.uuid4().hex[:6]}")

        [frame] = frames
        assert frame["type"] == "error"
        assert frame["data"]["code"] == "teacher_only"
        assert frame["data"]["chat_id"] == chat_id
        assert sent == []
        # Nothing charged, nothing half-saved.
        assert run_db(backend.db.db.generation_events.count_documents(
            {"user_id": student["id"]})) == 0
        assert run_db(backend.db.db.messages.count_documents({"chat_id": chat_id})) == 0

    def test_still_gets_an_answer_the_library_has(self, backend, client, new_user, monkeypatch):
        from app.services import cache_service

        async def hit(prompt, screenshots, variant=""):
            return {"educator_text": "Жарық шашырайды.", "video_url": "/media/rendered_1.mp4",
                    "tier": "warm", "match": "exact"}

        monkeypatch.setattr(cache_service, "lookup", hit)
        new_user(role="student")

        _, frames = ask(client, "неге аспан көк", frames_expected=2)

        assert frames[0]["type"] == "message_received"
        assert frames[1]["type"] == "ai_response"
        assert frames[1]["data"]["from_cache"] is True

    def test_the_role_comes_from_the_account_not_the_frame(self, backend, client, new_user, monkeypatch):
        """A frame claiming to be a teacher changes nothing."""
        from app.ws.manager import agent_manager

        sent = []

        async def fake_send(**kwargs):
            sent.append(kwargs)

        monkeypatch.setattr(agent_manager, "send_to_agent", fake_send)
        new_user(role="student")

        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "create_chat", "data": {"title": "t"}})
            chat_id = ws.receive_json()["data"]["id"]
            ws.send_json({"type": "user_message", "data": {
                "chat_id": chat_id, "prompt": f"сұрақ {uuid.uuid4().hex[:6]}", "role": "teacher"}})
            frame = ws.receive_json()

        assert frame["data"]["code"] == "teacher_only"
        assert sent == []


class TestATeacher:
    def test_reaches_the_agent(self, backend, client, new_user, monkeypatch):
        from app.ws.manager import agent_manager

        sent = []

        async def fake_send(**kwargs):
            sent.append(kwargs)

        monkeypatch.setattr(agent_manager, "send_to_agent", fake_send)
        monkeypatch.setattr(agent_manager, "agent_connection", object())
        new_user(role="teacher")

        _, frames = ask(client, f"неге аспан көк {uuid.uuid4().hex[:6]}")

        assert frames[0]["type"] == "message_received"
        assert len(sent) == 1


@pytest.fixture(autouse=True)
def _clear_pending(backend):
    from app.ws.manager import agent_manager

    yield
    agent_manager.pending_requests.clear()
