"""A whole quiz run against the live stack, through nginx.

Everything the browser does, without a browser: a teacher signs in, keeps a
quiz, opens a run; three phones join by code, the teacher starts, the phones
answer, the teacher ends it and reads the results - including the one shared
wrong answer the results exist to point out. Then the boundaries: the quiz
service is not reachable around nginx's rules, and the agent channel is still
shut.

Needs `docker compose up -d`. Leaves one teacher account behind, deleted at
the end, which is also how the account outbox gets exercised for real.
"""

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from http.cookiejar import CookieJar

import pytest

pytestmark = pytest.mark.e2e

BASE = os.getenv("ANYQ_BASE_URL", "http://localhost:3000")


class Client:
    def __init__(self, cookies: bool = True):
        handlers = [urllib.request.HTTPCookieProcessor(CookieJar())] if cookies else []
        self.opener = urllib.request.build_opener(*handlers)

    def call(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            BASE + path, data=data, method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                return error.code, json.loads(raw)
            except ValueError:
                return error.code, raw.decode(errors="replace")


@pytest.fixture(scope="module")
def stack():
    try:
        urllib.request.urlopen(BASE + "/health", timeout=5)
    except Exception:  # noqa: BLE001
        pytest.skip(f"no stack at {BASE}")


@pytest.fixture(scope="module")
def teacher(stack):
    client = Client()
    status, body = client.call("POST", "/api/auth/signup", {
        "email": f"quiz{uuid.uuid4().hex[:10]}@school.kz", "password": "password123",
        "name": "Quiz E2E", "role": "teacher",
    })
    assert status == 201, body
    yield client
    client.call("DELETE", "/api/auth/account")


QUESTIONS = [
    {"type": "choice", "text": "2 кг денеге 10 Н күш әсер етеді. Үдеу?",
     "options": [{"text": "5 м/с²"}, {"text": "20 м/с²", "note": "Көбейтті"},
                 {"text": "0,2 м/с²"}, {"text": "12 м/с²"}],
     "correct": 0, "explanation": "a = F/m"},
    {"type": "short", "text": "Тыныштықтағы дененің үдеуі?", "answer": "0", "unit": "м/с²"},
]


def test_a_whole_run(teacher):
    status, quiz = teacher.call("POST", "/api/quiz/quizzes", {
        "title": "E2E", "subject": "physics", "grade": 8, "lang": "kk", "questions": QUESTIONS,
    })
    assert status == 201, quiz
    assert quiz["problems"] == {}

    status, run = teacher.call("POST", f"/api/quiz/quizzes/{quiz['id']}/sessions", {
        "settings": {"shuffleQuestions": False, "shuffleOptions": False, "timeLimitMin": 5},
        "classLabel": "8 Ә",
    })
    assert status == 201, run
    code = run["code"]

    phone = Client(cookies=False)
    status, found = phone.call("GET", f"/api/play/code/{code}")
    assert status == 200 and found["questionCount"] == 2

    tokens = []
    for name in ("Дана", "Ерлан", "Әлия"):
        status, joined = phone.call("POST", f"/api/play/code/{code}/join", {"name": name})
        assert status == 201, joined
        tokens.append(joined["token"])

    status, started = teacher.call("POST", f"/api/quiz/sessions/{run['id']}/start")
    assert status == 200 and started["status"] == "running"
    # Waited out by asking, not by sleeping: the countdown is measured on the
    # server's clock, and a freshly started Docker VM's clock was seen running
    # 8% slow and then jumping - a fixed sleep raced it.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        _, state = phone.call("GET", "/api/play/state", headers={"X-Player-Token": tokens[0]})
        if state["status"] == "playing":
            break
        time.sleep(0.3)

    picks = ["20 м/с²", "20 м/с²", "5 м/с²"]
    for token, pick in zip(tokens, picks, strict=True):
        headers = {"X-Player-Token": token}
        status, state = phone.call("GET", "/api/play/state", headers=headers)
        assert status == 200 and state["status"] == "playing", state
        assert "correct" not in json.dumps(state["question"])
        option = next(o["id"] for o in state["question"]["options"] if o["text"] == pick)
        status, reply = phone.call("POST", "/api/play/answer",
                                   {"questionId": state["question"]["id"], "optionId": option},
                                   headers=headers)
        assert status == 200, reply
        assert reply["correct"] is (pick == "5 м/с²")
        status, reply = phone.call("POST", "/api/play/answer",
                                   {"questionId": reply["state"]["question"]["id"], "text": "0"},
                                   headers=headers)
        assert status == 200 and reply["state"]["status"] == "finished"

    status, ended = teacher.call("POST", f"/api/quiz/sessions/{run['id']}/end")
    assert status == 200 and ended["status"] == "ended"
    assert phone.call("GET", f"/api/play/code/{code}")[0] == 404

    status, results = teacher.call("GET", f"/api/quiz/sessions/{run['id']}/results")
    assert status == 200
    assert results["summary"]["players"] == 3
    # Two of three picked 20 m/s² - below the "at least three" a shared
    # misunderstanding needs, so it is reported per question but not as one.
    first = results["questions"][0]
    assert [o["count"] for o in first["options"]] == [1, 2, 0, 0]
    assert results["players"][0]["name"] == "Әлия"


def test_a_student_cannot_reach_teacher_routes(stack):
    phone = Client(cookies=False)
    assert phone.call("GET", "/api/quiz/quizzes")[0] == 401


def test_the_agent_channel_is_still_shut(stack):
    assert Client(cookies=False).call("GET", "/ws/agent")[0] == 403


def test_drafts_still_go_to_the_backend(stack):
    """/api/quiz-drafts must not be caught by the /api/quiz/ prefix: the quiz
    service has no such route and would answer 404, the backend answers 401."""
    status, _ = Client(cookies=False).call("POST", "/api/quiz-drafts", {})
    assert status in (401, 422)
