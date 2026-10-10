"""Quotas against the running stack.

The unit tests cover the arithmetic. This checks the wiring: that the refusal
actually reaches the socket, that it arrives instead of a render, and - the
part worth guarding - that an answer already in the library is still served to
a user with nothing left. A quota that blocks cached answers would punish
exactly the behaviour that keeps the service up.

No LLM is spent here: the budget is exhausted by writing counter rows
directly, which is what the backend counts.
"""

import json
import subprocess
import time
import uuid

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not __import__("os").environ.get("ANYQ_STACK_UP"),
        reason="needs the docker stack - run `make up` and set ANYQ_STACK_UP=1",
    ),
]

BASE = "http://localhost:3000"
WS = "ws://localhost:3000/ws"
PASSWORD = "password123"


def _mongo(script: str) -> str:
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "mongo", "mongosh", "anyq_db",
         "--quiet", "--eval", script],
        capture_output=True, timeout=60,
    ).stdout.decode("utf-8", "replace").strip()


@pytest.fixture
def account():
    import httpx

    username = f"q_{uuid.uuid4().hex[:8]}"
    client = httpx.Client(base_url=BASE, timeout=30)
    assert client.post(
        "/api/auth/signup", json={"username": username, "password": PASSWORD}
    ).status_code == 201
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    yield client, user_id
    _mongo(f"db.generation_events.deleteMany({{user_id: '{user_id}'}});")
    client.close()


def _exhaust(user_id: str, count: int) -> None:
    """Spend the budget without spending an LLM call."""
    _mongo(
        f"const now = new Date(); const rows = [];"
        f"for (let i = 0; i < {count}; i++) rows.push({{user_id: '{user_id}', "
        "  request_id: 'seed-' + i, created_at: now, "
        "  expires_at: new Date(now.getTime() + 2*864e5)});"
        "db.generation_events.insertMany(rows);"
    )


def _ask(client, question: str, timeout: float = 25.0) -> dict:
    """Send one question over the socket and return the first terminal frame."""
    from websockets.sync.client import connect

    cookie = f"anyq_session={client.cookies['anyq_session']}"
    with connect(WS, additional_headers={"Cookie": cookie}) as ws:
        ws.send(json.dumps({"type": "create_chat", "data": {"title": "Quota"}}))
        chat_id = json.loads(ws.recv())["data"]["id"]
        ws.send(json.dumps({
            "type": "user_message",
            "data": {"chat_id": chat_id, "prompt": question, "screenshots": []},
        }))

        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = json.loads(ws.recv())
            if frame.get("type") in ("error", "ai_response"):
                return frame
    pytest.fail("no terminal frame within the timeout")


def test_the_budget_endpoint_starts_full(account):
    client, _ = account

    body = client.get("/api/quota").json()

    assert body["used_hour"] == 0
    assert body["remaining_hour"] == body["limit_hour"]


def test_an_exhausted_budget_refuses_a_new_generation(account):
    client, user_id = account
    limit = client.get("/api/quota").json()["limit_day"]
    _exhaust(user_id, limit)

    frame = _ask(client, f"Explain {uuid.uuid4().hex[:10]}")

    assert frame["type"] == "error"
    assert "today" in frame["data"]["message"].lower()
    # The refusal carries the numbers, so the UI need not guess.
    assert frame["data"]["quota"]["remaining_day"] == 0


def test_a_refusal_says_what_still_works(account):
    client, user_id = account
    _exhaust(user_id, client.get("/api/quota").json()["limit_day"])

    frame = _ask(client, f"Explain {uuid.uuid4().hex[:10]}")

    assert "library" in frame["data"]["message"].lower()


def test_a_library_answer_is_served_with_no_budget_left(account):
    """The case that matters most: the cache must outlive the quota."""
    client, user_id = account

    # Seed an answer for a question nobody else asks, then spend everything.
    video = subprocess.run(
        ["docker", "compose", "exec", "-T", "backend", "sh", "-c",
         "ls -S /app/media/outputs/*.mp4 2>/dev/null | head -1"],
        capture_output=True, timeout=60,
    ).stdout.decode().strip().rsplit("/", 1)[-1]
    if not video.endswith(".mp4"):
        pytest.skip("no rendered video in the media volume")

    topic = f"topic{uuid.uuid4().hex[:8]}"
    import hashlib
    key = hashlib.sha256(f"{topic}|v1".encode()).hexdigest()
    payload = json.dumps({"key": key, "norm": topic, "video": f"/media/{video}"})
    _mongo(
        f"const p = {payload}; const now = new Date();"
        "db.library_entries.updateOne({cache_key: p.key}, {$set: {cache_key: p.key,"
        "  normalized_question: p.norm, educator_text: 'From the library.',"
        "  video_url: p.video, tier: 'warm', pipeline_version: 'v1',"
        "  expires_at: new Date(Date.now() + 30*864e5), last_hit_at: now},"
        "$setOnInsert: {created_at: now, hits: 0}}, {upsert: true});"
    )
    _exhaust(user_id, client.get("/api/quota").json()["limit_day"])
    spent_before = client.get("/api/quota").json()["used_hour"]

    frame = _ask(client, f"Explain {topic}")

    assert frame["type"] == "ai_response", frame
    assert frame["data"]["from_cache"] is True
    assert client.get("/api/quota").json()["used_hour"] == spent_before, \
        "a library answer must not cost a generation"
