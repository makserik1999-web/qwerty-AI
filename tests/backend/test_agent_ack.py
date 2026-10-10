"""A successful send is not a delivered request.

Found live. The agent container was restarted; it spent twenty-five seconds
reconnecting, and a question arrived in the middle of that window. The backend
still held the old socket - the websocket ping timeout is ninety seconds, so
nothing had declared it dead yet - and `send_json` on it did not fail. It
cannot: a TCP connection whose far end has gone still takes bytes into the
kernel buffer, and the write returns.

So the backend charged the quota, entered the request in pending_requests as a
generation in progress, and told the person to wait. No machine was working on
it. `GENERATION_MAX_CONCURRENT=1` then refused every later question with "your
previous video is still being made" - for the full half-hour TTL, because the
sweep is the only thing that ever clears an entry nobody answers.

The fix is that the agent says "I have it" the moment the frame comes off the
wire, and the send is not finished until that arrives. These tests drive the
managers directly: the bug is about what a write proves, and a test that had
to arrange a real half-dead socket would be one that fails once a month.
"""

import asyncio

import pytest


class _DeadSocket:
    """The socket at the heart of the incident: writable, and nobody home.

    Not a mock of a failure - a mock of a SUCCESS. Every send returns cleanly
    and no reply ever comes, which is exactly what the kernel does for a
    connection whose far end has gone.
    """

    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=1000, reason=""):
        pass


class _LiveSocket:
    """An agent that answers, as a real one does, before doing the work."""

    def __init__(self, manager):
        self.manager = manager
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)
        request_id = payload.get("request_id")
        if request_id and "type" not in payload:
            self.manager.resolve_ack(request_id)

    async def close(self, code=1000, reason=""):
        pass


@pytest.fixture
def agent(backend):
    from app.ws.manager import agent_manager

    agent_manager.agent_connection = None
    agent_manager.agent_features = set()
    agent_manager.pending_acks.clear()
    agent_manager.pending_requests.clear()
    yield agent_manager
    agent_manager.agent_connection = None
    agent_manager.agent_features = set()
    agent_manager.pending_acks.clear()
    agent_manager.pending_requests.clear()


async def _send(agent, request_id="r1"):
    await agent.send_to_agent(
        request_id=request_id, user_id="u1", chat_id="c1",
        text="почему лед не тает в воде", screenshots=[],
    )


async def _wait_until_waiting(agent):
    """Let the sender reach its await. Bounded, so a regression fails rather
    than hanging the suite: without the fix nothing is ever registered here."""
    for _ in range(1000):
        if agent.pending_acks:
            return
        await asyncio.sleep(0)
    raise AssertionError("the send never waited for a confirmation")


# ------------------------------------------------- what a write does not prove --


class TestASendIsNotADelivery:
    async def test_a_dead_socket_is_reported_as_a_failure(self, agent, monkeypatch):
        """The whole incident in one assertion.

        Without the ack this returns quietly and the request is lost.
        """
        import app.ws.manager as manager

        monkeypatch.setattr(manager, "AGENT_ACK_TIMEOUT_SEC", 0.05)
        agent.agent_connection = _DeadSocket()
        agent.agent_features = {"ack"}

        with pytest.raises(manager.AgentDeliveryError):
            await _send(agent)

    async def test_the_frame_was_written_all_the_same(self, agent, monkeypatch):
        """Proof the test is not just a socket that refuses to send.

        The write succeeded. That is the point: success here means nothing.
        """
        import app.ws.manager as manager

        monkeypatch.setattr(manager, "AGENT_ACK_TIMEOUT_SEC", 0.05)
        socket = _DeadSocket()
        agent.agent_connection = socket
        agent.agent_features = {"ack"}

        with pytest.raises(manager.AgentDeliveryError):
            await _send(agent)

        assert socket.sent, "the send did not even happen - wrong failure"
        assert socket.sent[0]["request_id"] == "r1"

    async def test_nothing_is_left_waiting_afterwards(self, agent, monkeypatch):
        """A failed send must not leak the future it was waiting on."""
        import app.ws.manager as manager

        monkeypatch.setattr(manager, "AGENT_ACK_TIMEOUT_SEC", 0.05)
        agent.agent_connection = _DeadSocket()
        agent.agent_features = {"ack"}

        with pytest.raises(manager.AgentDeliveryError):
            await _send(agent)

        assert agent.pending_acks == {}


class TestAnAgentThatAnswers:
    async def test_a_confirmed_request_goes_through(self, agent):
        agent.agent_connection = _LiveSocket(agent)
        agent.agent_features = {"ack"}

        await _send(agent)  # no exception is the assertion

        assert agent.pending_acks == {}

    async def test_the_question_is_still_what_gets_sent(self, agent):
        """The ack is added to the exchange, not substituted for it."""
        socket = _LiveSocket(agent)
        agent.agent_connection = socket
        agent.agent_features = {"ack"}

        await _send(agent)

        assert socket.sent[0]["text"] == "почему лед не тает в воде"

    async def test_an_ack_that_arrives_first_is_not_missed(self, agent):
        """The agent replies off the wire; it can beat the sender's own await.

        Registering the future after the send would drop that reply as
        unknown and time out a request that had in fact landed.
        """
        agent.agent_connection = _LiveSocket(agent)  # acks inside send_json
        agent.agent_features = {"ack"}

        await _send(agent)


class TestAnOlderAgent:
    async def test_it_is_not_waited_for(self, agent, monkeypatch):
        """No `ack` in the handshake means no confirmation is ever coming.

        Waiting for one would fail every request against a build that works.
        """
        import app.ws.manager as manager

        monkeypatch.setattr(manager, "AGENT_ACK_TIMEOUT_SEC", 0.05)
        agent.agent_connection = _DeadSocket()
        agent.agent_features = {"embed"}

        await _send(agent)  # no exception, and no wait


# --------------------------------------------- not making people wait to be told --


class TestTheConnectionGoingAway:
    async def test_a_drop_releases_the_sender_at_once(self, agent, monkeypatch):
        """The socket is known to be dead; sitting out the timeout is the bug again."""
        import app.ws.manager as manager

        monkeypatch.setattr(manager, "AGENT_ACK_TIMEOUT_SEC", 30)
        socket = _DeadSocket()
        agent.agent_connection = socket
        agent.agent_features = {"ack"}

        task = asyncio.create_task(_send(agent))
        await _wait_until_waiting(agent)

        agent.disconnect(socket)

        with pytest.raises(manager.AgentDeliveryError):
            await asyncio.wait_for(task, timeout=1)

    async def test_a_reconnect_releases_it_too(self, agent, monkeypatch):
        """A reconnecting agent did not read the frames written to the old socket."""
        import app.ws.manager as manager

        monkeypatch.setattr(manager, "AGENT_ACK_TIMEOUT_SEC", 30)
        agent.agent_connection = _DeadSocket()
        agent.agent_features = {"ack"}

        task = asyncio.create_task(_send(agent))
        await _wait_until_waiting(agent)

        await agent.connect(_DeadSocket())

        with pytest.raises(manager.AgentDeliveryError):
            await asyncio.wait_for(task, timeout=1)


# ------------------------------------------------------- what the user is told --


class TestTheCostOfTheLostRequest:
    """The half-hour lockout, which is what made this worth fixing.

    An entry in pending_requests is a generation in progress as far as the
    quota is concerned. One that nobody is working on blocks the next question
    just as effectively as a real one.
    """

    async def test_an_unanswered_request_would_block_the_next_one(self, agent):
        import time

        agent.pending_requests["ghost"] = {
            "user_id": "u1", "chat_id": "c1", "created_at": time.monotonic(),
        }

        assert agent.in_flight_for("u1") == 1, (
            "this is what refuses the user's next question for the full TTL"
        )
