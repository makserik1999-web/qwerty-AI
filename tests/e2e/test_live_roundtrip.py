"""Live E2E: frontend-route (nginx :3000) full round-trip.

signup -> WS /ws (cookie) -> create_chat -> user_message -> ai_response
(with video_url when the agent renders) -> GET /media/{video} -> 200.

Usage: python logs/e2e_live.py [username]
Requires: httpx, websockets (already in logs/.venv) and the stack running.
"""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.skipif(
    not __import__("os").environ.get("ANYQ_STACK_UP"),
    reason="needs the docker stack on :3000 - run `make up` and set ANYQ_STACK_UP=1",
)]

import json
import time
import uuid

import httpx
import websockets.sync.client

BASE = "http://localhost:3000"
# A fresh account per run. This used to read sys.argv[1] when the file was a
# standalone script; under pytest that argument is a test path, which is not a
# valid username.
username = f"e2e_{uuid.uuid4().hex[:10]}"


def main():
    with httpx.Client(base_url=BASE, timeout=20) as hx:
        r = hx.post("/api/auth/signup", json={"username": username, "password": "password123"})
        print("signup", r.status_code, r.text[:80])
        assert r.status_code == 201, r.text
        cookie = r.headers.get("set-cookie", "").split(";")[0]
        print("cookie set:", cookie[:30], "...")
        assert cookie.startswith("anyq_session="), cookie

        headers = {"Cookie": cookie}
        urls = "ws://localhost:3000/ws"
        with websockets.sync.client.connect(urls, additional_headers=headers, max_size=16 * 1024 * 1024) as ws:
            ws.send(json.dumps({"type": "create_chat", "data": {"title": "Gravity"}}))
            msg = json.loads(ws.recv())
            print("recv:", msg.get("type"))
            chat_id = msg["data"]["id"]
            print("chat_id:", chat_id)

            ws.send(json.dumps({"type": "user_message", "data": {"chat_id": chat_id, "prompt": "Explain gravity"}}))
            # expect message_received ack
            ack = json.loads(ws.recv())
            print("recv:", ack.get("type"))
            assert ack.get("type") == "message_received", ack

            # wait for ai_response (render can take a while in snippet mode)
            deadline = time.time() + 300
            video_url = None
            content = None
            while time.time() < deadline:
                raw = ws.recv()
                m = json.loads(raw)
                print("recv:", m.get("type"), str(m)[:160])
                if m.get("type") == "ai_response":
                    content = m["data"].get("content")
                    video_url = m["data"].get("video_url")
                    break
                if m.get("type") == "error":
                    print("ERROR FRAME:", m)
                    return 1
            assert video_url, "no video_url in ai_response"
            assert video_url.startswith("/media/"), video_url
            print("VIDEO_URL:", video_url)

        # fetch the video over the authenticated route
        r = hx.get(video_url)
        print("GET", video_url, r.status_code, "bytes:", len(r.content))
        assert r.status_code == 200
        assert len(r.content) > 1000, "video too small"

        # and a logged-out request must fail
        r2 = httpx.get(BASE + video_url, timeout=10)
        print("GET without cookie:", r2.status_code)
        assert r2.status_code in (401, 403), r2.status_code

    print("E2E_OK content-prefix:", (content or "")[:60])
    return 0


def test_live_roundtrip():
    """Wraps the original script so pytest reports it as one integration case."""
    assert main() == 0
