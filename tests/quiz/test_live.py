"""The live channels, and what reaches them when something happens."""

import asyncio

import pytest
from quizkit import player
from starlette.websockets import WebSocketDisconnect


def _receive_until(socket, kind, limit=10):
    for _ in range(limit):
        message = socket.receive_json()
        if message.get("type") == kind:
            return message
    raise AssertionError(f"no {kind!r} message")


class TestTheTeachersBoard:
    def test_it_needs_the_teacher(self, as_, open_session):
        _, session = open_session()
        anon = as_(None)
        with pytest.raises(WebSocketDisconnect),                 anon.websocket_connect(f"/ws/quiz/host/{session['id']}") as socket:
            socket.receive_json()

    def test_another_teacher_is_refused(self, as_, open_session):
        _, session = open_session()
        other = as_("other-token")
        with pytest.raises(WebSocketDisconnect),                 other.websocket_connect(f"/ws/quiz/host/{session['id']}") as socket:
            socket.receive_json()

    def test_a_foreign_page_cannot_open_it_with_the_cookie(self, client, open_session):
        """A WebSocket upgrade is not covered by CORS; this is what stands in."""
        _, session = open_session()
        with pytest.raises(WebSocketDisconnect),                 client.websocket_connect(f"/ws/quiz/host/{session['id']}",
                                         headers={"Origin": "https://evil.example"}) as socket:
            socket.receive_json()

    def test_it_hears_joins_and_answers(self, client, open_session, join):
        _, session = open_session()
        with client.websocket_connect(f"/ws/quiz/host/{session['id']}",
                                      headers={"Origin": "http://localhost:3000"}) as board:
            assert board.receive_json()["type"] == "snapshot"

            token, _ = join(session["code"], "Дана")
            joined = _receive_until(board, "joined")
            assert joined["player"]["name"] == "Дана"

            client.post(f"/api/quiz/sessions/{session['id']}/start")
            assert _receive_until(board, "status")["status"] == "running"

            me = player(client, token)
            state = me.state().json()
            option = next(o["id"] for o in state["question"]["options"] if o["text"] == "4")
            me.answer(questionId=state["question"]["id"], optionId=option)
            answer = _receive_until(board, "answer")
            assert answer["correct"] is True and answer["optionId"] == option
            assert answer["player"]["answered"] == 1


class TestAStudentsPhone:
    def test_the_token_comes_first(self, client):
        with client.websocket_connect("/ws/quiz/play") as socket:
            socket.send_json({"type": "hello", "token": "nobody"})
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()

    def test_it_is_told_when_the_teacher_starts(self, client, open_session, join):
        _, session = open_session()
        token, _ = join(session["code"])
        with client.websocket_connect("/ws/quiz/play") as phone:
            phone.send_json({"type": "hello", "token": token})
            first = phone.receive_json()
            assert first["type"] == "state" and first["state"]["status"] == "lobby"

            client.post(f"/api/quiz/sessions/{session['id']}/start")
            started = _receive_until(phone, "status")
            assert started["status"] == "running" and started["startsAt"]

    def test_it_hears_others_arrive(self, client, open_session, join):
        _, session = open_session()
        token, _ = join(session["code"], "A")
        with client.websocket_connect("/ws/quiz/play") as phone:
            phone.send_json({"type": "hello", "token": token})
            phone.receive_json()
            join(session["code"], "B")
            assert _receive_until(phone, "lobby")["players"] == 2

    def test_a_removed_student_is_told_and_cut_off(self, client, open_session, join):
        _, session = open_session()
        token, state = join(session["code"])
        with client.websocket_connect("/ws/quiz/play") as phone:
            phone.send_json({"type": "hello", "token": token})
            phone.receive_json()
            client.delete(f"/api/quiz/sessions/{session['id']}/players/{state['player']['id']}")
            assert _receive_until(phone, "kicked")["type"] == "kicked"

    def test_a_phone_on_an_unlisted_address_still_connects(self, client, open_session, join):
        """A class joining a stack on the school network arrives from an
        address nobody allowlisted. The token is the credential here, not a
        cookie, so the Origin proves nothing and must not shut them out."""
        _, session = open_session()
        token, _ = join(session["code"])
        with client.websocket_connect("/ws/quiz/play",
                                      headers={"Origin": "http://192.168.1.20:3000"}) as phone:
            phone.send_json({"type": "hello", "token": token})
            assert phone.receive_json()["type"] == "state"

    def test_ping(self, client, open_session, join):
        _, session = open_session()
        token, _ = join(session["code"])
        with client.websocket_connect("/ws/quiz/play") as phone:
            phone.send_json({"type": "hello", "token": token})
            phone.receive_json()
            phone.send_json({"type": "ping"})
            assert phone.receive_json()["type"] == "pong"


class TestADeletedAccount:
    """The backend records the deletion in `account_events`; this service
    removes what that account owned, and only that."""

    def _event(self, quiz, user_id):
        from quiz_service.db import now

        asyncio.run(quiz.db.db.account_events.insert_one(
            {"type": "account_deleted", "user_id": user_id, "created_at": now()}
        ))

    def _count(self, quiz, name, query):
        return asyncio.run(quiz.db.db[name].count_documents(query))

    def test_its_quizzes_runs_and_answers_go(self, as_, client, open_session, join, quiz):
        from quiz_service import events

        _, session = open_session()
        join(session["code"])
        as_("other-token")
        other = client.post("/api/quiz/quizzes", json={"title": "Бөтен"}).json()

        self._event(quiz, "teacher-1")
        assert asyncio.run(events.consume_once()) == 1

        assert self._count(quiz, "quizzes", {"owner_id": "teacher-1"}) == 0
        assert self._count(quiz, "quiz_sessions", {"owner_id": "teacher-1"}) == 0
        assert self._count(quiz, "quiz_players", {"session_id": session["id"]}) == 0
        assert client.get(f"/api/quiz/quizzes/{other['id']}").status_code == 200

    def test_an_event_is_handled_once(self, quiz):
        from quiz_service import events

        self._event(quiz, "teacher-1")
        assert asyncio.run(events.consume_once()) == 1
        assert asyncio.run(events.consume_once()) == 0

    def test_the_open_code_dies_with_it(self, client, open_session, quiz):
        from quiz_service import events

        _, session = open_session()
        self._event(quiz, "teacher-1")
        asyncio.run(events.consume_once())
        assert client.get(f"/api/play/code/{session['code']}").status_code == 404
