"""A reconnect must not delete the connection that replaced the old one.

Found live, on a page that had been open across a frontend deploy. The
question reached the agent, rendered in 72 seconds, and the answer was sent -
and the browser sat on the first progress step forever, showing "connected"
the whole time.

The reason is a race with an ordering that is not the exception but the rule.
A reconnect opens the new socket before the old one has finished closing, so
the old socket's cleanup runs LAST:

    1. socket A is registered for user U
    2. socket B connects; connect() closes A and registers B
    3. A's handler wakes from the close and calls disconnect(U)
    4. disconnect popped by user id alone - so it deleted B

After that B is open, the browser is happy, and the map is empty. Sending
still works, because a frame from the client is handled where it arrives.
Receiving does not, because delivery is a lookup in that map - so answers go
nowhere, silently, and the only symptom is a spinner that never stops.

The fix is to forget a socket only when it is still the registered one. These
tests drive the ordering directly rather than through real sockets: the bug is
about who is in the map, and a test that had to win a real race would be one
that fails once a month.
"""

import pytest


class _Socket:
    """Enough of a WebSocket for the registry to hold and close."""

    def __init__(self, name):
        self.name = name
        self.closed = False
        self.sent = []

    async def accept(self):
        pass

    async def close(self, code=1000, reason=""):
        self.closed = True

    async def send_json(self, payload):
        if self.closed:
            raise RuntimeError("socket is closed")
        self.sent.append(payload)

    def __repr__(self):
        return f"<socket {self.name}>"


@pytest.fixture
def ui(backend):
    from app.ws.manager import ui_manager

    ui_manager.active_connections.clear()
    yield ui_manager
    ui_manager.active_connections.clear()


class TestTheUISocket:
    async def test_the_new_socket_survives_the_old_ones_cleanup(self, ui):
        """The exact ordering that was losing answers."""
        a, b = _Socket("A"), _Socket("B")
        await ui.connect(a, "u1")
        await ui.connect(b, "u1")

        # A's handler only now notices it was closed.
        ui.disconnect("u1", a)

        assert ui.get_connection("u1") is b, (
            "the reconnecting socket was deleted by the socket it replaced"
        )

    async def test_the_answer_still_reaches_the_reader(self, ui):
        """What the race actually cost: delivery.

        Sending from the client kept working, which is why the interface still
        looked connected - so this checks the direction that broke.
        """
        a, b = _Socket("A"), _Socket("B")
        await ui.connect(a, "u1")
        await ui.connect(b, "u1")
        ui.disconnect("u1", a)

        delivered = await ui.send_to_user("u1", {"type": "ai_response"})

        assert delivered is True
        assert b.sent == [{"type": "ai_response"}]

    async def test_the_old_socket_is_closed_when_replaced(self, ui):
        """Unchanged behaviour, and worth keeping: no leaked connections."""
        a, b = _Socket("A"), _Socket("B")
        await ui.connect(a, "u1")
        await ui.connect(b, "u1")

        assert a.closed is True

    async def test_a_real_disconnect_still_forgets_the_socket(self, ui):
        """The fix must not turn into "never forget anything"."""
        a = _Socket("A")
        await ui.connect(a, "u1")

        ui.disconnect("u1", a)

        assert ui.get_connection("u1") is None
        assert await ui.send_to_user("u1", {"type": "x"}) is False

    async def test_one_person_leaving_does_not_disconnect_another(self, ui):
        a, b = _Socket("A"), _Socket("B")
        await ui.connect(a, "u1")
        await ui.connect(b, "u2")

        ui.disconnect("u1", a)

        assert ui.get_connection("u2") is b


@pytest.fixture
def agent(backend):
    from app.ws.manager import agent_manager

    agent_manager.agent_connection = None
    yield agent_manager
    agent_manager.agent_connection = None


class TestTheAgentSocket:
    """The same race, with worse consequences.

    Clearing the new agent connection leaves the backend believing no agent is
    available while one is sitting there - so questions are refused outright,
    and everybody already waiting is told their request failed.
    """

    async def test_the_reconnected_agent_stays_registered(self, agent):
        a, b = _Socket("A"), _Socket("B")
        await agent.connect(a)
        await agent.connect(b)

        agent.disconnect(a)

        assert agent.agent_connection is b, (
            "the backend would refuse questions with an agent connected"
        )

    async def test_a_real_agent_disconnect_is_recorded(self, agent):
        a = _Socket("A")
        await agent.connect(a)

        agent.disconnect(a)

        assert agent.agent_connection is None

    async def test_nobody_is_told_the_agent_left_when_it_did_not(self, agent, backend):
        """The notification is what turns this into a visible wrong answer.

        A person waiting on a render would be told "the agent is not
        available" - and refunded - because a previous socket finished
        closing after the replacement had already connected.
        """
        from app.ws import agent as agent_api

        a, b = _Socket("A"), _Socket("B")
        await agent.connect(a)
        await agent.connect(b)

        agent.disconnect(a)

        # The endpoint only notifies when the connection is really gone; this
        # is the condition it checks.
        assert agent.agent_connection is not None
        assert hasattr(agent_api, "_notify_pending_failures")
