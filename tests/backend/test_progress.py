"""Saying which stage a request is on, while it is still on it.

Between "the question has been sent" and "here is your video" the backend used
to say nothing at all, for thirty to ninety seconds. The interface draws three
steps for that wait - reading the question, writing the explanation, rendering
the animation - and with no frames to move it, the first one stayed lit for
the whole time. An indicator that never moves reads as stuck, which is a worse
report than no indicator at all.

The stages are reported by the agent from the graph, where the transitions
happen. The alternative - a timer on the client - would be wrong exactly when
it matters: a repair attempt, a slow model, a queue behind another render. It
would keep claiming progress after everything had stopped.

The one that would be easy to get wrong is the last test here: a progress
frame must not consume the pending request, or the answer that follows it has
nowhere to be delivered and the question hangs forever.
"""

import pytest


@pytest.fixture
def asking(client, new_user, agent_secret):
    """A signed-in user with a question in flight, and the agent listening.

    Yields the two sockets plus the request id the backend generated, which is
    what a progress frame has to name.
    """
    from contextlib import contextmanager

    @contextmanager
    def _open(prompt="что такое инерция"):
        new_user()
        with client.websocket_connect("/ws/agent") as agent:
            agent.send_json({"type": "auth", "token": agent_secret})
            assert agent.receive_json().get("type") == "auth_ok"

            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "create_chat", "data": {"title": "t"}})
                chat_id = ws.receive_json()["data"]["id"]

                ws.send_json(
                    {"type": "user_message", "data": {"chat_id": chat_id, "prompt": prompt}}
                )
                assert ws.receive_json().get("type") == "message_received"

                request_id = agent.receive_json()["request_id"]
                yield agent, ws, request_id, chat_id

    return _open


class TestTheStageReachesTheAsker:
    def test_a_stage_is_forwarded(self, asking):
        with asking() as (agent, ws, request_id, chat_id):
            agent.send_json(
                {"type": "progress", "request_id": request_id, "stage": "write"}
            )
            frame = ws.receive_json()

        assert frame["type"] == "progress"
        assert frame["data"]["stage"] == "write"

    def test_it_names_the_chat(self, asking):
        """The interface has one chat on screen; a frame for another is not it."""
        with asking() as (agent, ws, request_id, chat_id):
            agent.send_json(
                {"type": "progress", "request_id": request_id, "stage": "render"}
            )
            frame = ws.receive_json()

        assert frame["data"]["chat_id"] == chat_id

    def test_every_stage_the_interface_draws_gets_through(self, asking):
        with asking() as (agent, ws, request_id, _):
            seen = []
            for stage in ("understand", "write", "render"):
                agent.send_json(
                    {"type": "progress", "request_id": request_id, "stage": stage}
                )
                seen.append(ws.receive_json()["data"]["stage"])

        assert seen == ["understand", "write", "render"]


class TestAProgressFrameIsNotAnAnswer:
    def test_the_request_is_still_pending_after_one(self, asking):
        """The bug this guards: consuming the pending request.

        `get_request_info` pops by default. Popping on a progress frame leaves
        the real answer with an unknown request_id, and the question hangs
        until the deadline with no error and no video.

        Checked against the pending table rather than by waiting for the
        answer, deliberately. The symptom of this bug is an answer that never
        arrives - so a test written as "then the answer arrives" does not fail,
        it hangs, and a hung suite says far less than a red one.
        """
        from app.ws.manager import agent_manager

        with asking() as (agent, ws, request_id, _):
            agent.send_json(
                {"type": "progress", "request_id": request_id, "stage": "write"}
            )
            assert ws.receive_json()["type"] == "progress"

            assert request_id in agent_manager.pending_requests, (
                "the progress frame consumed the request; the answer that "
                "follows it would have nowhere to go"
            )

    def test_the_answer_still_arrives_after_one(self, asking):
        """And end to end, now that the fast check above rules out the hang."""
        from app.ws.manager import agent_manager

        with asking() as (agent, ws, request_id, _):
            agent.send_json(
                {"type": "progress", "request_id": request_id, "stage": "write"}
            )
            assert ws.receive_json()["type"] == "progress"
            assert request_id in agent_manager.pending_requests

            agent.send_json(
                {
                    "request_id": request_id,
                    "status": "complete",
                    "text": "инерция это...",
                    "video_path": "",
                }
            )
            answer = ws.receive_json()

        assert answer["type"] == "ai_response"
        assert answer["data"]["content"] == "инерция это..."

    def test_several_in_a_row_do_not_use_it_up(self, asking):
        from app.ws.manager import agent_manager

        with asking() as (agent, ws, request_id, _):
            for stage in ("understand", "write", "render", "write"):
                agent.send_json(
                    {"type": "progress", "request_id": request_id, "stage": stage}
                )
                ws.receive_json()

            assert request_id in agent_manager.pending_requests

    def test_nothing_is_saved_for_one(self, asking, client):
        """A stage is not a message; the chat must be unchanged by it."""
        with asking() as (agent, ws, request_id, chat_id):
            agent.send_json(
                {"type": "progress", "request_id": request_id, "stage": "write"}
            )
            ws.receive_json()

            history = client.get(f"/api/chats/{chat_id}").json()

        # Only the question. An answer appears when there is one.
        assert [m["role"] for m in history["messages"]] == ["user"]


class TestWhatIsRefused:
    @pytest.mark.parametrize("stage", ["", "done", "RENDER", "write; drop", "x" * 200])
    def test_an_unknown_stage_is_dropped(self, asking, stage):
        """The value reaches an interface that switches on it.

        Forwarding whatever arrives would leave the indicator on a step that
        does not exist, which is how it gets stuck at the end of a run.
        """
        with asking() as (agent, ws, request_id, _):
            agent.send_json(
                {"type": "progress", "request_id": request_id, "stage": stage}
            )
            # Nothing should come back; the answer proves the socket still works.
            agent.send_json(
                {"request_id": request_id, "status": "complete", "text": "ok",
                 "video_path": ""}
            )
            first = ws.receive_json()

        assert first["type"] == "ai_response", f"a bad stage was forwarded: {stage!r}"

    def test_an_unknown_request_is_dropped(self, asking):
        """A guessed id must not let anyone push frames at another person."""
        with asking() as (agent, ws, request_id, _):
            agent.send_json(
                {"type": "progress", "request_id": "not-a-real-request", "stage": "write"}
            )
            agent.send_json(
                {"request_id": request_id, "status": "complete", "text": "ok",
                 "video_path": ""}
            )
            first = ws.receive_json()

        assert first["type"] == "ai_response"

    def test_one_without_a_request_id_is_dropped(self, asking):
        with asking() as (agent, ws, request_id, _):
            agent.send_json({"type": "progress", "stage": "write"})
            agent.send_json(
                {"request_id": request_id, "status": "complete", "text": "ok",
                 "video_path": ""}
            )
            first = ws.receive_json()

        assert first["type"] == "ai_response"
