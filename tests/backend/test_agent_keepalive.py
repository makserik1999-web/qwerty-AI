"""A dropped agent connection must not destroy a finished render.

Observed once, live: the agent channel closed with "keepalive ping timeout"
early in a request. The agent went on working, rendered a 154-second video,
wrote it to the shared volume - and the answer was discarded, because the
backend had already forgotten who asked. The person was told the agent was
unavailable and the render was spent for nothing.

Two things are held here, and only the second is about keepalive numbers.

THE ONE THAT MATTERS: the pending request survives the disconnect. It is what
turns a lost render into a slow one. The work does not stop because a socket
did; the agent finishes, reconnects and delivers, and the answer is saved and
cached even though the asker was already told it had failed - so asking again
is instant instead of another two minutes.

THE OTHER: the two sides' keepalives have to be ordered, not merely present.
The backend must be the more patient of the two, so the agent - the side that
can actually reconnect and redeliver - notices a dead connection first. The
backend had never had these set at all: uvicorn's defaults are 20s between
pings with 20s to answer, which nobody chose for a peer that spends minutes
rendering.

Not proven here, and worth saying plainly: this does not explain the incident.
A deliberately blocked agent event loop survived 200 seconds in two probes
without the connection closing, so whatever tripped it is still unaccounted
for. What these tests hold is that it costs a rendered video when it happens.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DOCKERFILE = ROOT / "backend" / "Dockerfile"
AGENT_CONFIG = ROOT / "agent" / "anyq" / "config.py"


# ------------------------------------------------------- the two keepalives --


@pytest.fixture(scope="module")
def uvicorn_flags() -> dict:
    text = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    cmd = re.search(r"^CMD\s*\[(.+?)\]", text, re.MULTILINE | re.DOTALL)
    assert cmd, "no CMD found in the backend Dockerfile"
    parts = re.findall(r'"([^"]+)"', cmd.group(1))
    return {
        parts[i]: parts[i + 1]
        for i in range(len(parts) - 1)
        if parts[i].startswith("--")
    }


@pytest.fixture(scope="module")
def agent_timeouts() -> dict:
    text = AGENT_CONFIG.read_text(encoding="utf-8")
    found = {}
    for name in ("WS_PING_INTERVAL_SEC", "WS_PING_TIMEOUT_SEC"):
        match = re.search(rf"{name} = _get_float\([^,]+,\s*([\d.]+)\)", text)
        assert match, f"{name} not found in the agent config"
        found[name] = float(match.group(1))
    return found


def test_the_backend_sets_its_keepalive(uvicorn_flags):
    """Left unset it is 20s/20s, which is uvicorn's default and not a choice."""
    assert "--ws-ping-interval" in uvicorn_flags
    assert "--ws-ping-timeout" in uvicorn_flags


def test_the_backend_is_the_more_patient_side(uvicorn_flags, agent_timeouts):
    """Ordering, not size: the side that can reconnect must notice first.

    If the backend gives up first it drops a connection the agent still thinks
    it has, and the agent finds out only when it tries to send - by which time
    the render is done and the request is gone.
    """
    backend_timeout = float(uvicorn_flags["--ws-ping-timeout"])

    assert backend_timeout > agent_timeouts["WS_PING_TIMEOUT_SEC"], (
        "the backend would give up on the agent before the agent gives up on "
        "the backend, so the reconnect happens later than the drop"
    )


def test_the_tolerance_is_not_absurd(uvicorn_flags):
    """Patient, not deaf: a genuinely dead peer still has to be noticed."""
    assert float(uvicorn_flags["--ws-ping-timeout"]) <= 300


# --------------------------------------------- the request outlives the drop --


class TestAFinishedRenderSurvivesTheDisconnect:
    @pytest.fixture
    def in_flight(self, client, new_user, agent_secret):
        """A question with the agent working on it, then the agent vanishing."""
        from contextlib import contextmanager

        @contextmanager
        def _open():
            new_user()
            with client.websocket_connect("/ws") as ws:
                with client.websocket_connect("/ws/agent") as agent:
                    agent.send_json({"type": "auth", "token": agent_secret})
                    assert agent.receive_json().get("type") == "auth_ok"

                    ws.send_json({"type": "create_chat", "data": {"title": "t"}})
                    chat_id = ws.receive_json()["data"]["id"]
                    ws.send_json({
                        "type": "user_message",
                        "data": {"chat_id": chat_id, "prompt": "что такое инерция"},
                    })
                    assert ws.receive_json().get("type") == "message_received"
                    request_id = agent.receive_json()["request_id"]
                # The agent connection is closed here: this is the incident.
                yield ws, request_id, chat_id

        return _open

    async def test_the_asker_is_told_at_once(self, in_flight):
        """They must not sit watching an indicator for a connection that is gone."""
        with in_flight() as (ws, _, chat_id):
            frame = ws.receive_json()

        assert frame["type"] == "error"
        assert frame["data"]["chat_id"] == chat_id

    async def test_but_the_request_is_kept(self, in_flight, backend):
        """The half that was missing: something has to remember who asked.

        Without this the answer arrives with an unknown request_id and is
        dropped on the floor - which is exactly what happened to a video that
        had already been rendered and written to disk.
        """
        from app.ws.manager import agent_manager

        with in_flight() as (ws, request_id, _):
            ws.receive_json()

            assert request_id in agent_manager.pending_requests, (
                "the rendered answer would have nowhere to go"
            )

    async def test_the_answer_still_lands_when_the_agent_comes_back(
        self, in_flight, client, agent_secret
    ):
        with in_flight() as (ws, request_id, chat_id):
            ws.receive_json()  # the failure notice

            with client.websocket_connect("/ws/agent") as agent:
                agent.send_json({"type": "auth", "token": agent_secret})
                assert agent.receive_json().get("type") == "auth_ok"

                agent.send_json({
                    "request_id": request_id,
                    "status": "complete",
                    "text": "инерция - это...",
                    "video_path": "",
                })
                delivered = ws.receive_json()

        assert delivered["type"] == "ai_response"
        assert delivered["data"]["content"] == "инерция - это..."

    async def test_it_is_written_to_the_chat(self, in_flight, client, agent_secret):
        """So it is there on the next visit, whatever the asker saw at the time."""
        with in_flight() as (ws, request_id, chat_id):
            ws.receive_json()

            with client.websocket_connect("/ws/agent") as agent:
                agent.send_json({"type": "auth", "token": agent_secret})
                agent.receive_json()
                agent.send_json({
                    "request_id": request_id,
                    "status": "complete",
                    "text": "инерция - это...",
                    "video_path": "",
                })
                ws.receive_json()

            history = client.get(f"/api/chats/{chat_id}").json()

        assert [m["role"] for m in history["messages"]] == ["user", "assistant"]


class TestTheAskerIsNotToldTwice:
    async def test_the_sweep_stays_quiet_about_a_reported_request(
        self, client, new_user, agent_secret, backend
    ):
        """Keeping the entry must not turn into a second error half an hour later."""
        from app.ws import manager

        new_user()
        with client.websocket_connect("/ws") as ws:
            with client.websocket_connect("/ws/agent") as agent:
                agent.send_json({"type": "auth", "token": agent_secret})
                agent.receive_json()
                ws.send_json({"type": "create_chat", "data": {"title": "t"}})
                chat_id = ws.receive_json()["data"]["id"]
                ws.send_json({
                    "type": "user_message",
                    "data": {"chat_id": chat_id, "prompt": "q"},
                })
                ws.receive_json()
                request_id = agent.receive_json()["request_id"]

            first = ws.receive_json()
            assert first["type"] == "error"

            # The entry is now stale; the sweep clears it out.
            info = manager.agent_manager.pending_requests[request_id]
            info["created_at"] = 0.0
            await manager._sweep_once()

            assert request_id not in manager.agent_manager.pending_requests

            # Nothing further should have been said. Proven by the next frame
            # being an answer to a ping rather than a second error.
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
