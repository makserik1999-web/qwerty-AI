"""The quiz service on an in-memory Mongo, with identity faked at its seam.

The service asks the backend who a cookie belongs to. Here that question is
answered from a table instead (identity.use_resolver), which is the one place
the service lets anything in from outside - so these tests exercise every
line of it except the HTTP call itself.

One TestClient serves teachers and students alike. Teachers are told apart by
the cookie they send and students by their token header, and keeping them on
one client keeps every socket and every request on one event loop - which is
what the live hub needs, since a request on one loop cannot write to a socket
owned by another.
"""

import contextlib
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from quizkit import choice, short

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "quiz") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "quiz"))

COOKIE = "anyq_session"

USERS = {
    "teacher-token": {"id": "teacher-1", "name": "Айгүл", "role": "teacher"},
    "other-token": {"id": "teacher-2", "name": "Ерлан", "role": "teacher"},
    "student-token": {"id": "student-1", "name": "Дана", "role": "student"},
}


@pytest.fixture(scope="session")
def quiz():
    from mongomock_motor import AsyncMongoMockClient
    from quiz_service import db as database
    from quiz_service import identity
    from quiz_service.main import app

    client = AsyncMongoMockClient()
    database.db.client = client
    database.db.db = client["quiz_test"]

    async def resolver(token):
        return USERS.get(token)

    identity.use_resolver(resolver)

    @contextlib.asynccontextmanager
    async def _no_lifespan(_app):
        yield

    app.router.lifespan_context = _no_lifespan
    return SimpleNamespace(app=app, db=database.db, identity=identity)


@pytest.fixture(autouse=True)
def _fresh(quiz):
    """Every test starts with empty collections and unspent limits.

    The in-memory database lives for the whole run, and caps like "three open
    sessions per teacher" would otherwise be spent by whichever tests ran
    before this one.
    """
    import asyncio

    from quiz_service.api import play

    async def wipe():
        for name in ("quizzes", "quiz_sessions", "quiz_players", "account_events"):
            await quiz.db.db[name].delete_many({})

    asyncio.run(wipe())
    play.join_window.clear()
    play.lookup_window.clear()
    yield


@pytest.fixture(autouse=True)
def _no_countdown(quiz, monkeypatch):
    """Most tests answer straight after Start; the countdown has its own."""
    from quiz_service.api import play, sessions

    monkeypatch.setattr(sessions, "COUNTDOWN_SEC", 0)
    monkeypatch.setattr(play, "COUNTDOWN_SEC", 0)


@pytest.fixture
def client(quiz):
    from fastapi.testclient import TestClient

    with TestClient(quiz.app) as c:
        c.cookies.set(COOKIE, "teacher-token")
        yield c


@pytest.fixture
def as_(client):
    """Switch who the shared client is: as_("other-token"), as_(None)."""

    def _switch(token):
        client.cookies.clear()
        if token:
            client.cookies.set(COOKIE, token)
        return client

    return _switch


@pytest.fixture
def make_quiz(client):
    def _make(questions=None, **fields):
        body = {
            "title": f"Квиз {uuid.uuid4().hex[:6]}",
            "subject": "physics",
            "grade": 8,
            "lang": "kk",
            "questions": questions if questions is not None else [choice(), short()],
            **fields,
        }
        response = client.post("/api/quiz/quizzes", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest.fixture
def open_session(client, make_quiz):
    """A quiz, opened, with settings that make tests deterministic."""

    def _open(questions=None, **settings):
        quiz = make_quiz(questions)
        chosen = {"shuffleQuestions": False, "shuffleOptions": False, **settings}
        response = client.post(f"/api/quiz/quizzes/{quiz['id']}/sessions",
                               json={"settings": chosen, "classLabel": "8 Ә"})
        assert response.status_code == 201, response.text
        return quiz, response.json()

    return _open


@pytest.fixture
def join(client):
    def _join(code, name="Дана"):
        response = client.post(f"/api/play/code/{code}/join", json={"name": name})
        assert response.status_code == 201, response.text
        body = response.json()
        return body["token"], body["state"]

    return _join
