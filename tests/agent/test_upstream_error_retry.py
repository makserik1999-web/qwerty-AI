"""A 200 that says the model never ran was being taken for an answer.

Found while investigating assessments failing. OpenRouter returns a perfectly
ordinary 200 with `finish_reason: "error"` when the provider behind the model
fails mid-generation: the content is empty and NOTHING RAISES. The retry
wrapper in _llm_chat only ever saw exceptions, so it never saw this - and one
momentary upstream failure became a hard failure of the whole request.

Measured over 23 assessments through the full stack: three came back this way,
all inside one eleven-minute window, and zero in the thirty calls after it.
That is a transient condition, which is precisely the kind the product already
knows how to handle - it just could not see this one.

What it cost, per caller, because every one of them reads an empty reply as
something the model meant:

    classify_intent        no JSON -> is_science False -> a physics question
                           answered "this is not a science question"
    educator_answer        an empty explanation, carried into the video
    generate_manim_script  RuntimeError, the request fails
    generate_assessment    "model returned no questions", a 502 to the teacher
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "agent", REPO_ROOT / "tests" / "stubs"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from anyq import llm_client  # noqa: E402


class _Reply:
    """What a provider hands back: content, and a reason it stopped."""

    def __init__(self, content="", finish_reason="stop"):
        self.content = content
        self.finish_reason = finish_reason


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """The backoff is real seconds; the behaviour under test is not about them."""
    monkeypatch.setattr(llm_client, "_LLM_RETRY_BASE_DELAY", 0)


def _answers(*replies):
    """A fake provider that returns each reply in turn, counting the calls."""
    calls = []

    async def fake(messages, **kwargs):
        calls.append(messages)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    return fake, calls


# ------------------------------------------------ the reply that means nothing --


class TestAnUpstreamErrorIsNotAnAnswer:
    async def test_it_is_retried(self, monkeypatch):
        """Without the fix this returns the empty reply and the caller acts on
        it. The assertion is the second call."""
        fake, calls = _answers(_Reply("", "error"), _Reply('{"ok": 1}', "stop"))
        monkeypatch.setattr(llm_client, "_chat_off_the_main_loop", fake)

        reply = await llm_client._llm_chat([])

        assert len(calls) == 2, "the failed reply was taken for an answer"
        assert reply.content == '{"ok": 1}'

    async def test_it_gives_up_rather_than_looping(self, monkeypatch):
        fake, calls = _answers(_Reply("", "error"))
        monkeypatch.setattr(llm_client, "_chat_off_the_main_loop", fake)

        with pytest.raises(llm_client.UpstreamLLMError):
            await llm_client._llm_chat([])

        assert len(calls) == llm_client._LLM_RETRIES + 1

    async def test_the_error_says_what_happened(self, monkeypatch):
        """It reaches a log, and "no content" is not a diagnosis."""
        fake, _ = _answers(_Reply("", "error"))
        monkeypatch.setattr(llm_client, "_chat_off_the_main_loop", fake)

        with pytest.raises(llm_client.UpstreamLLMError, match="finish_reason=error"):
            await llm_client._llm_chat([])


class TestWhatIsNotRetried:
    """Retrying the wrong things is how a momentary failure becomes a bill."""

    async def test_a_normal_answer_is_returned_at_once(self, monkeypatch):
        fake, calls = _answers(_Reply("hello", "stop"))
        monkeypatch.setattr(llm_client, "_chat_off_the_main_loop", fake)

        assert (await llm_client._llm_chat([])).content == "hello"
        assert len(calls) == 1

    async def test_a_truncated_answer_is_kept(self, monkeypatch):
        """`length` means the model ran and hit the cap. Asking again would
        truncate again, at the same place, for the same money."""
        fake, calls = _answers(_Reply("half a thing", "length"))
        monkeypatch.setattr(llm_client, "_chat_off_the_main_loop", fake)

        assert (await llm_client._llm_chat([])).content == "half a thing"
        assert len(calls) == 1

    async def test_an_empty_answer_that_finished_normally_is_kept(self, monkeypatch):
        """The model ran and chose to say nothing. That is an answer about the
        question, not a failure of the provider."""
        fake, calls = _answers(_Reply("", "stop"))
        monkeypatch.setattr(llm_client, "_chat_off_the_main_loop", fake)

        assert (await llm_client._llm_chat([])).content == ""
        assert len(calls) == 1

    async def test_a_content_filter_is_kept(self, monkeypatch):
        fake, calls = _answers(_Reply("", "content_filter"))
        monkeypatch.setattr(llm_client, "_chat_off_the_main_loop", fake)

        await llm_client._llm_chat([])
        assert len(calls) == 1

    async def test_a_reply_with_no_finish_reason_at_all_is_kept(self, monkeypatch):
        """Not every provider sets one, and absence is not an error."""

        class Bare:
            content = "fine"

        async def fake(messages, **kwargs):
            return Bare()

        monkeypatch.setattr(llm_client, "_chat_off_the_main_loop", fake)
        assert (await llm_client._llm_chat([])).content == "fine"


class TestItJoinsTheExistingRetryPath:
    def test_the_new_error_counts_as_transient(self):
        assert llm_client._is_transient_llm_error(llm_client.UpstreamLLMError("x"))

    def test_an_ordinary_error_still_does_not(self):
        assert not llm_client._is_transient_llm_error(ValueError("bad argument"))

    def test_a_503_still_does(self):
        assert llm_client._is_transient_llm_error(RuntimeError("503 unavailable"))

    @pytest.mark.parametrize(
        "reason,expected",
        [("error", True), ("ERROR", True), ("stop", False), ("length", False),
         ("", False), (None, False)],
    )
    def test_only_error_is_treated_as_upstream_failure(self, reason, expected):
        assert llm_client._is_upstream_error(_Reply("", reason)) is expected
