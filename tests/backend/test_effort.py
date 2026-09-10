"""Choosing how much is spent on a video, and the cache not undoing that.

Effort is a bundle rather than a number: it selects a manim render profile
(480p15, 720p30 or 1080p60 - frames as well as pixels) and how many times a
failing script may be repaired. Measured on one 37-second scene, rendering
alone: 11.4 seconds at the low profile against 68.8 at the high one.

What it deliberately does NOT change is how hard the model thinks about the
Manim script. That was measured too, and it goes the wrong way: at the
provider's default reasoning effort the script rendered 2 times out of 4,
at "low" it rendered 4 of 4, because the deliberation is spent inventing API
that is not in the prompt. A top setting that broke rendering would be a
control selling a downgrade.

As with narration and length, the failure worth guarding is not a video that
came out a little different. It is somebody choosing 1080p and being handed a
stored 480p copy because the question matched.
"""

import pytest


class TestTheChoiceReachesTheCacheKey:
    def test_two_efforts_are_two_entries(self, backend):
        from app.services.cache_service import render_variant

        assert render_variant(True, "aigul", "medium", "low") != render_variant(
            True, "aigul", "medium", "high"
        )

    def test_effort_separates_silent_videos_too(self, backend):
        """The picture quality is a choice whether or not it speaks."""
        from app.services.cache_service import render_variant

        assert render_variant(False, "aigul", "short", "low") != render_variant(
            False, "aigul", "short", "high"
        )

    def test_length_and_voice_still_separate_within_one_effort(self, backend):
        from app.services.cache_service import render_variant

        assert render_variant(True, "aigul", "short", "high") != render_variant(
            True, "aigul", "long", "high"
        )
        assert render_variant(True, "aigul", "short", "high") != render_variant(
            True, "daulet", "short", "high"
        )

    def test_omitting_it_reproduces_the_earlier_fragment(self, backend):
        """Entries stored before efforts existed stay reachable."""
        from app.services.cache_service import render_variant

        assert render_variant(True, "aigul") == "voice=aigul"
        assert render_variant(True, "aigul", "short") == "voice=aigul,len=short"


class TestOnlyRealLevelsGetThrough:
    """The value picks a render profile and reaches a hash."""

    @pytest.mark.parametrize("nonsense", ["", "ultra", "1080p", "high; DROP", "../x"])
    def test_nonsense_becomes_the_default(self, client, new_user, agent_secret, nonsense):
        from app.config import EFFORT_DEFAULT

        new_user()
        with client.websocket_connect("/ws/agent") as agent:
            agent.send_json({"type": "auth", "token": agent_secret})
            assert agent.receive_json().get("type") == "auth_ok"

            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "create_chat", "data": {"title": "x"}})
                chat_id = ws.receive_json()["data"]["id"]
                ws.send_json({
                    "type": "user_message",
                    "data": {"chat_id": chat_id, "prompt": "что такое сила",
                             "effort": nonsense},
                })
                assert ws.receive_json().get("type") == "message_received"

                assert agent.receive_json()["effort"] == EFFORT_DEFAULT

    @pytest.mark.parametrize("cased", ["HIGH", " High ", "LoW"])
    def test_casing_and_spacing_are_forgiven(self, client, new_user, agent_secret, cased):
        """A real choice typed differently is still that choice.

        Substituting the default here would be worse than rejecting it: the
        person picked a quality, the video comes back another quality, and
        nothing says why.
        """
        new_user()
        with client.websocket_connect("/ws/agent") as agent:
            agent.send_json({"type": "auth", "token": agent_secret})
            assert agent.receive_json().get("type") == "auth_ok"

            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "create_chat", "data": {"title": "x"}})
                chat_id = ws.receive_json()["data"]["id"]
                ws.send_json({
                    "type": "user_message",
                    "data": {"chat_id": chat_id, "prompt": "что такое сила",
                             "effort": cased},
                })
                assert ws.receive_json().get("type") == "message_received"

                assert agent.receive_json()["effort"] == cased.strip().lower()

    def test_the_backend_and_the_agent_agree_on_the_names(self, backend):
        """The backend validates names; the agent owns what they mean.

        If the lists drift, a level the interface offers is silently replaced
        by the default at the far end - a control that appears to work and
        does nothing.
        """
        from pathlib import Path

        from app.config import EFFORT_LEVELS

        agent_config = (
            Path(__file__).resolve().parents[2] / "agent" / "anyq" / "config.py"
        ).read_text(encoding="utf-8")

        for name in EFFORT_LEVELS:
            assert f'"{name}"' in agent_config, (
                f"the backend offers {name!r} and the agent has no profile for it"
            )
