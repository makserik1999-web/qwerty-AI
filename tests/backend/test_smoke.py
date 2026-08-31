"""Backend smoke suite: auth, chats, media, the UI socket and the agent channel.

Converted from the linear `logs/backend_smoke.py` script. Every test signs up
its own user, so the tests are independent and order does not matter.
"""

import uuid

import pytest
from starlette.websockets import WebSocketDisconnect


def _is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4
    except Exception:
        return False


# ============== 1. unauthenticated access ==============
def test_chats_list_requires_auth(anon_client):
    assert anon_client.get("/api/chats").status_code == 401


def test_single_chat_requires_auth(anon_client):
    response = anon_client.get("/api/chats/012345678901234567890123")
    assert response.status_code == 401


def test_media_requires_auth(anon_client):
    assert anon_client.get("/media/rendered_1.mp4").status_code == 401


def test_ws_without_cookie_is_rejected(anon_client):
    # The backend closes the socket during the handshake (code 1008).
    with pytest.raises(WebSocketDisconnect), anon_client.websocket_connect("/ws") as ws:
        ws.receive_json()


# ============== 2. signup ==============
def test_signup_sets_session_cookie(client, new_user):
    user = new_user()
    assert "anyq_session" in client.cookies
    assert user["id"]


def test_duplicate_signup_is_rejected(client, new_user):
    user = new_user()
    response = client.post(
        "/api/auth/signup",
        json={"username": user["username"], "password": "password123"},
    )
    assert response.status_code == 409, response.text


def test_short_password_is_rejected(client):
    response = client.post(
        "/api/auth/signup",
        json={"username": f"u_{uuid.uuid4().hex[:12]}", "password": "short"},
    )
    assert response.status_code == 400, response.text


# ============== 3-5. me / logout / login ==============
def test_me_returns_the_signed_up_user(client, new_user):
    user = new_user()
    response = client.get("/api/auth/me")
    assert response.status_code == 200, response.text
    assert response.json()["user"]["username"] == user["username"]
    assert response.json()["user"]["id"] == user["id"]


def test_logout_revokes_the_session(client, new_user):
    new_user()
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_login_rejects_a_wrong_password(client, new_user):
    user = new_user()
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login",
        json={"username": user["username"], "password": "wrongpass"},
    )
    assert response.status_code == 401, response.text


def test_login_with_correct_password_restores_access(client, new_user):
    user = new_user()
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login",
        json={"username": user["username"], "password": user["password"]},
    )
    assert response.status_code == 200, response.text
    assert client.get("/api/auth/me").status_code == 200


# ============== 6. chats over HTTP ==============
def test_new_user_has_no_chats(client, new_user):
    new_user()
    response = client.get("/api/chats")
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_invalid_chat_id_is_a_400_not_a_crash(client, new_user):
    new_user()
    assert client.get("/api/chats/not-an-objectid").status_code == 400


# ============== 7. media ==============
def test_media_is_served_to_an_authenticated_user(client, new_user):
    new_user()
    assert client.get("/media/rendered_1.mp4").status_code == 200


def test_media_path_traversal_is_rejected(client, new_user):
    new_user()
    assert client.get("/media/../../etc/passwd").status_code == 404


def test_missing_media_is_a_404(client, new_user):
    new_user()
    assert client.get("/media/missing.mp4").status_code == 404


# ============== 8. UI websocket ==============
def test_ws_creates_a_chat(client, new_user):
    new_user()
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_chat", "data": {"title": "Physics chat"}})
        message = ws.receive_json()
    assert message["type"] == "chat_created"
    assert message["data"]["id"]


def test_ws_invalid_chat_id_returns_an_error_frame(client, new_user):
    new_user()
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_message", "data": {"chat_id": "zzz", "prompt": "hi"}})
        error = ws.receive_json()
    assert error["type"] == "error"


def test_ws_reports_a_missing_agent_before_saving(client, new_user):
    new_user()
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_chat", "data": {"title": "No agent"}})
        chat_id = ws.receive_json()["data"]["id"]

        ws.send_json({"type": "user_message", "data": {"chat_id": chat_id, "prompt": "hello"}})
        error = ws.receive_json()

    assert error["type"] == "error"
    assert "Agent" in error["data"]["message"]


# ============== 9. agent channel ==============
def test_agent_with_a_wrong_secret_is_rejected(client):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/agent") as agent:
        agent.send_json({"type": "auth", "token": "wrong"})
        agent.receive_json()


def test_agent_roundtrip_delivers_the_answer_to_the_user(client, new_user, agent_secret):
    new_user()
    with client.websocket_connect("/ws/agent") as agent:
        agent.send_json({"type": "auth", "token": agent_secret})
        assert agent.receive_json().get("type") == "auth_ok"

        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "create_chat", "data": {"title": "Agent chat"}})
            chat_id = ws.receive_json()["data"]["id"]

            ws.send_json(
                {"type": "user_message", "data": {"chat_id": chat_id, "prompt": "Explain gravity"}}
            )
            assert ws.receive_json().get("type") == "message_received"

            request = agent.receive_json()
            request_id = request.get("request_id")
            assert request_id, request
            # The id must be generated server-side and be unguessable.
            assert _is_uuid4(request_id), request_id
            assert request.get("text") == "Explain gravity"

            agent.send_json(
                {
                    "request_id": request_id,
                    "status": "complete",
                    "text": "Gravity explanation",
                    "video_path": "",
                }
            )
            answer = ws.receive_json()

    assert answer["type"] == "ai_response"
    assert answer["data"]["chat_id"] == chat_id
    assert answer["data"]["content"] == "Gravity explanation"


def test_agent_error_status_reaches_the_user_with_chat_id(client, new_user, agent_secret):
    new_user()
    with client.websocket_connect("/ws/agent") as agent:
        agent.send_json({"type": "auth", "token": agent_secret})
        agent.receive_json()

        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "create_chat", "data": {"title": "Err chat"}})
            chat_id = ws.receive_json()["data"]["id"]

            ws.send_json({"type": "user_message", "data": {"chat_id": chat_id, "prompt": "boom"}})
            ws.receive_json()  # message_received

            request = agent.receive_json()
            agent.send_json(
                {
                    "request_id": request["request_id"],
                    "status": "error",
                    "text": "",
                    "video_path": "",
                    "error": "render failed",
                }
            )
            error = ws.receive_json()

    assert error["type"] == "error"
    assert error["data"].get("chat_id") == chat_id
    assert "failed" in error["data"]["message"]


# ============== 10. cross-user isolation ==============
def test_a_user_cannot_read_another_users_chat(backend, client, new_user):
    from fastapi.testclient import TestClient

    new_user()  # alice, on `client`

    with TestClient(backend.app) as other:
        response = other.post(
            "/api/auth/signup",
            json={"username": f"u_{uuid.uuid4().hex[:12]}", "password": "password123"},
        )
        assert response.status_code == 201, response.text

        with other.websocket_connect("/ws") as ws:
            ws.send_json({"type": "create_chat", "data": {"title": "Carol chat"}})
            foreign_chat_id = ws.receive_json()["data"]["id"]

    assert client.get(f"/api/chats/{foreign_chat_id}").status_code == 404
