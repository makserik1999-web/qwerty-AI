"""Choosing how long the video runs, and the cache not undoing that choice.

There is no duration parameter in Manim or anywhere in this pipeline. A video
lasts exactly as long as its animations, and with narration on those are
pinned to the speech (`run_time=tracker.duration`), so the length is decided
by how much the script is told to SAY. Measured over twelve renders: 11.8 to
13.3 spoken characters per second, mean 12.7, spread about six percent. The
three buckets are those seconds converted back into a character budget.

The interesting failure is not "the video came out forty-five seconds instead
of forty". It is a person choosing "short" and being handed a stored
ninety-second answer because the question matched - the choice silently
undone by the cache, with nothing on screen to say so. That is what most of
this file is about.
"""

import pytest


class TestTheChoiceReachesTheCacheKey:
    """A stored answer belongs to the length it was made for.

    `render_variant` is what keeps two people who asked the same question but
    wanted different videos from being served each other's. It already did
    that for narration; length is the second thing that changes what gets
    made rather than what gets asked.
    """

    def test_two_lengths_are_two_entries(self, backend):
        from app.services.cache_service import render_variant

        short = render_variant(True, "aigul", "short")
        long_ = render_variant(True, "aigul", "long")

        assert short != long_, (
            "one cache entry would serve both, so whoever asked second would "
            "get the length the first person chose"
        )

    def test_length_still_separates_silent_videos(self, backend):
        """With the voice off the length is still a choice, and still theirs."""
        from app.services.cache_service import render_variant

        assert render_variant(False, "aigul", "short") != render_variant(
            False, "aigul", "long"
        )

    def test_the_voice_still_separates_within_one_length(self, backend):
        """The new fragment must not swallow the old one."""
        from app.services.cache_service import render_variant

        assert render_variant(True, "aigul", "medium") != render_variant(
            True, "daulet", "medium"
        )

    def test_omitting_the_length_reproduces_the_old_fragment(self, backend):
        """Entries stored before lengths existed stay reachable.

        The default argument is not decoration: without it every stored answer
        would have been retired the moment this shipped, and the first person
        to ask each question again would pay for a render we already had.
        """
        from app.services.cache_service import render_variant

        assert render_variant(True, "aigul") == "voice=aigul"
        assert render_variant(False, "aigul") == "silent"


class TestOnlyRealLengthsGetThrough:
    """The value picks a character budget and reaches a hash.

    Free text here would let one client mint unlimited cache entries for a
    single question - the same reason the voice is checked against a closed
    set before it goes anywhere.
    """

    @pytest.mark.parametrize("nonsense", ["", "tiny", "SHORT; DROP", "12s", "../etc"])
    def test_nonsense_becomes_the_default(self, client, new_user, agent_secret, nonsense):
        from app.config import VIDEO_LENGTH_DEFAULT

        new_user()
        with client.websocket_connect("/ws/agent") as agent:
            agent.send_json({"type": "auth", "token": agent_secret})
            assert agent.receive_json().get("type") == "auth_ok"

            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "create_chat", "data": {"title": "x"}})
                chat_id = ws.receive_json()["data"]["id"]
                ws.send_json({
                    "type": "user_message",
                    "data": {
                        "chat_id": chat_id,
                        "prompt": "что такое сила",
                        "video_length": nonsense,
                    },
                })
                assert ws.receive_json().get("type") == "message_received"

                sent = agent.receive_json()

        assert sent["video_length"] == VIDEO_LENGTH_DEFAULT

    def test_a_chosen_length_is_forwarded_verbatim(self, client, new_user, agent_secret):
        new_user()
        with client.websocket_connect("/ws/agent") as agent:
            agent.send_json({"type": "auth", "token": agent_secret})
            assert agent.receive_json().get("type") == "auth_ok"

            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "create_chat", "data": {"title": "x"}})
                chat_id = ws.receive_json()["data"]["id"]
                ws.send_json({
                    "type": "user_message",
                    "data": {
                        "chat_id": chat_id,
                        "prompt": "что такое сила",
                        "video_length": "short",
                    },
                })
                assert ws.receive_json().get("type") == "message_received"

                assert agent.receive_json()["video_length"] == "short"

    def test_the_backend_and_the_agent_agree_on_the_names(self, backend):
        """Two closed sets, one meaning.

        The agent owns the character budgets; the backend only validates the
        names. If the lists drift, a length the interface offers would be
        silently replaced by the default at the far end - a control that
        appears to work and does nothing.
        """
        from pathlib import Path

        from app.config import VIDEO_LENGTHS

        agent_config = (
            Path(__file__).resolve().parents[2] / "agent" / "anyq" / "config.py"
        ).read_text(encoding="utf-8")

        for name in VIDEO_LENGTHS:
            assert f'"{name}"' in agent_config, (
                f"the backend offers {name!r} and the agent has no budget for it"
            )
