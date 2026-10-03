"""Quiz drafts: the backend's half of writing questions for the quiz service.

The quiz service holds no model key, so the editor asks here. What is checked
is the boundary - who may ask, and that only closed-set values and a wrapped
topic reach the agent - plus the one thing deleting an account now has to do
for a service that keeps its own data: say so.
"""

import asyncio
import uuid
from typing import Any, Dict

import pytest

VALID: Dict[str, Any] = {
    "subject": "physics", "grade": 8, "topic": "Ньютон заңдары", "lang": "kk",
    "count": 6, "mix": "mixed", "difficulty": "medium",
}

QUESTIONS = [
    {"type": "choice", "text": "Инерция дегеніміз не?",
     "options": [{"text": "a", "note": ""}, {"text": "b", "note": "x"},
                 {"text": "c", "note": "y"}, {"text": "d", "note": "z"}],
     "correct": 0, "explanation": "", "topic": ""},
]


@pytest.fixture
def agent(backend):
    from app.ws.manager import agent_manager

    sent = []

    class _Socket:
        async def send_json(self, payload):
            sent.append(payload)
            agent_manager.resolve_assessment(
                payload["request_id"], {"questions": QUESTIONS, "requested": 6}
            )

        async def close(self, code=1000, reason=""):
            pass

    agent_manager.agent_connection = _Socket()
    agent_manager.agent_features = {"quiz", "ack"}
    yield sent
    agent_manager.agent_connection = None
    agent_manager.agent_features = set()


@pytest.fixture
def teacher(client):
    response = client.post("/api/auth/signup", json={
        "email": f"q{uuid.uuid4().hex[:10]}@school.kz", "password": "password123",
        "name": "Айгүл", "role": "teacher",
    })
    assert response.status_code == 201, response.text
    return response.json()["user"]


class TestWhoMayAsk:
    def test_signed_out(self, anon_client):
        assert anon_client.post("/api/quiz-drafts", json=VALID).status_code == 401

    def test_a_student(self, client):
        client.post("/api/auth/signup", json={
            "email": f"s{uuid.uuid4().hex[:10]}@school.kz", "password": "password123",
            "name": "Дана", "role": "student",
        })
        assert client.post("/api/quiz-drafts", json=VALID).status_code == 403


class TestWhatReachesTheAgent:
    @pytest.mark.parametrize("field,bad", [
        ("subject", "astrology"), ("lang", "fr"), ("grade", 3), ("mix", "essay"),
        ("difficulty", "insane"), ("count", 0), ("count", 99), ("topic", "  "),
        ("topic", "x" * 300),
    ])
    def test_values_outside_their_set(self, client, teacher, agent, field, bad):
        assert client.post("/api/quiz-drafts", json={**VALID, field: bad}).status_code == 400
        assert not agent

    def test_the_spec_is_the_validated_one(self, client, teacher, agent):
        response = client.post("/api/quiz-drafts", json={**VALID, "avoid": ["  Бар сұрақ  ", ""]})
        assert response.status_code == 200, response.text
        assert response.json()["questions"] == QUESTIONS
        frame = agent[0]
        assert frame["type"] == "quiz"
        assert frame["spec"] == {
            "subject": "physics", "grade": 8, "topic": "Ньютон заңдары", "language": "kk",
            "count": 6, "mix": "mixed", "difficulty": "medium", "avoid": ["Бар сұрақ"],
        }

    def test_avoid_is_capped(self, client, teacher, agent):
        client.post("/api/quiz-drafts", json={**VALID, "avoid": [f"q{i}" for i in range(100)]})
        assert len(agent[0]["spec"]["avoid"]) == 40


class TestWhenTheAgentCannotHelp:
    def test_no_agent(self, client, teacher, backend):
        from app.ws.manager import agent_manager

        agent_manager.agent_connection = None
        assert client.post("/api/quiz-drafts", json=VALID).status_code == 503

    def test_an_agent_without_the_feature(self, client, teacher, backend):
        from app.ws.manager import agent_manager

        class _Old:
            async def send_json(self, payload):
                raise AssertionError("an older agent was sent a quiz frame")

            async def close(self, code=1000, reason=""):
                pass

        agent_manager.agent_connection = _Old()
        agent_manager.agent_features = {"assessment"}
        try:
            assert client.post("/api/quiz-drafts", json=VALID).status_code == 503
        finally:
            agent_manager.agent_connection = None
            agent_manager.agent_features = set()

    def test_the_agent_says_it_failed(self, client, teacher, backend):
        from app.ws.manager import agent_manager

        class _Failing:
            async def send_json(self, payload):
                agent_manager.resolve_assessment(payload["request_id"],
                                                 {"error": "only 1 usable questions of 6"})

            async def close(self, code=1000, reason=""):
                pass

        agent_manager.agent_connection = _Failing()
        agent_manager.agent_features = {"quiz"}
        try:
            assert client.post("/api/quiz-drafts", json=VALID).status_code == 502
        finally:
            agent_manager.agent_connection = None
            agent_manager.agent_features = set()


class TestDeletingAnAccountTellsTheQuizService:
    def test_an_event_is_recorded(self, client, teacher, backend):
        assert client.delete("/api/auth/account").status_code == 200
        events = asyncio.run(backend.db.db.account_events.count_documents(
            {"type": "account_deleted", "user_id": teacher["id"]}))
        assert events == 1
