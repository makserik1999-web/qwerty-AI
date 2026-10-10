"""A blocking provider must not stop the agent's event loop.

spoon_ai's Gemini provider calls the synchronous google-genai client from
inside `async def chat`. On the agent's own loop that freezes everything for
the length of the request: measured at 383 seconds, during which a 100ms
heartbeat ticked 7 times instead of ~3800.

What that costs is not abstract. uvicorn pings every 20s and closes a socket
after 20s without a pong, so the backend dropped the agent mid-request; the
answer finished computing 90 seconds later and was thrown away, and the
student was told the agent was unavailable.

The provider is a third-party package we do not patch, so the calls are moved
off the loop instead. These tests pin that down with a provider that really
blocks - a mock that merely awaits would pass no matter what we did.
"""

import asyncio
import threading
import time

import pytest


@pytest.fixture
def client(agent_import_path):
    import anyq.llm_client as module

    return module


# --------------------------------------------------------------- the defect --


class TestABlockingProviderCannotFreezeTheCaller:
    async def test_the_loop_keeps_running_during_a_blocking_call(self, client,
                                                                 monkeypatch):
        """The regression test. time.sleep, not asyncio.sleep - that is the bug."""
        BLOCK = 1.0
        ticks = []

        async def blocking_chat(messages, **kwargs):
            time.sleep(BLOCK)
            return "done"

        monkeypatch.setattr(client.llm, "chat", blocking_chat, raising=False)

        async def heartbeat():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.02)

        beat = asyncio.create_task(heartbeat())
        try:
            assert await client._llm_chat([]) == "done"
        finally:
            beat.cancel()

        # Anything close to BLOCK/0.02 means the loop stayed free. Before the
        # fix this was 1 or 2 ticks, all from before the call started.
        assert len(ticks) > BLOCK / 0.02 * 0.5, (
            f"only {len(ticks)} heartbeats during a {BLOCK}s call - the loop was blocked"
        )

    async def test_the_gap_between_heartbeats_stays_small(self, client, monkeypatch):
        """Counting ticks alone would pass if they all bunched up at one end."""
        ticks = []

        async def blocking_chat(messages, **kwargs):
            time.sleep(0.6)
            return "done"

        monkeypatch.setattr(client.llm, "chat", blocking_chat, raising=False)

        async def heartbeat():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.02)

        beat = asyncio.create_task(heartbeat())
        try:
            await client._llm_chat([])
        finally:
            beat.cancel()

        gaps = [b - a for a, b in zip(ticks, ticks[1:], strict=False)]
        assert gaps and max(gaps) < 0.3, f"loop stalled for {max(gaps):.2f}s"


# ------------------------------------------------------------ how it is done --


class TestTheProviderLoop:
    async def test_the_call_runs_on_a_different_loop(self, client, monkeypatch):
        seen = {}
        caller_loop = asyncio.get_running_loop()

        async def note_loop(messages, **kwargs):
            seen["loop"] = asyncio.get_running_loop()
            seen["thread"] = threading.current_thread().name
            return "ok"

        monkeypatch.setattr(client.llm, "chat", note_loop, raising=False)

        assert await client._llm_chat([]) == "ok"
        assert seen["loop"] is not caller_loop
        assert seen["thread"] == "anyq-llm"

    async def test_every_call_shares_one_loop(self, client, monkeypatch):
        """A fresh loop per call would break the SDK's cached async HTTP client."""
        loops = []

        async def note_loop(messages, **kwargs):
            loops.append(asyncio.get_running_loop())
            return "ok"

        monkeypatch.setattr(client.llm, "chat", note_loop, raising=False)

        for _ in range(3):
            await client._llm_chat([])

        assert len({id(loop) for loop in loops}) == 1

    async def test_the_thread_is_a_daemon(self, client, monkeypatch):
        """Otherwise a stuck provider call would keep the agent from exiting."""
        async def ok(messages, **kwargs):
            return "ok"

        monkeypatch.setattr(client.llm, "chat", ok, raising=False)
        await client._llm_chat([])

        threads = [t for t in threading.enumerate() if t.name == "anyq-llm"]
        assert threads and all(t.daemon for t in threads)


# --------------------------------------------------------------- still works --


class TestNothingElseChanged:
    async def test_the_result_is_returned_unchanged(self, client, monkeypatch):
        marker = object()

        async def ok(messages, **kwargs):
            return marker

        monkeypatch.setattr(client.llm, "chat", ok, raising=False)

        assert await client._llm_chat([]) is marker

    async def test_arguments_still_reach_the_provider(self, client, monkeypatch):
        seen = {}

        async def ok(messages, **kwargs):
            seen["messages"] = messages
            seen["kwargs"] = kwargs
            return "ok"

        monkeypatch.setattr(client.llm, "chat", ok, raising=False)
        await client._llm_chat(["m1"], temperature=0.3)

        assert seen["messages"] == ["m1"]
        assert seen["kwargs"]["temperature"] == 0.3

    async def test_a_provider_error_still_reaches_the_caller(self, client, monkeypatch):
        async def boom(messages, **kwargs):
            raise ValueError("upstream said no")

        monkeypatch.setattr(client.llm, "chat", boom, raising=False)

        with pytest.raises(ValueError, match="upstream said no"):
            await client._llm_chat([])

    async def test_a_transient_error_is_still_retried(self, client, monkeypatch):
        """The retry wrapper must survive the move to another loop."""
        calls = []

        async def flaky(messages, **kwargs):
            calls.append(1)
            if len(calls) < 2:
                raise RuntimeError("503 unavailable")
            return "recovered"

        monkeypatch.setattr(client.llm, "chat", flaky, raising=False)
        monkeypatch.setattr(client, "_LLM_RETRY_BASE_DELAY", 0.01)

        assert await client._llm_chat([]) == "recovered"
        assert len(calls) == 2

    async def test_a_cancelled_request_does_not_hang(self, client, monkeypatch):
        """agent_ws_client wraps every request in REQUEST_DEADLINE_SEC."""
        async def slow(messages, **kwargs):
            await asyncio.sleep(30)
            return "too late"

        monkeypatch.setattr(client.llm, "chat", slow, raising=False)

        started = time.monotonic()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(client._llm_chat([]), timeout=0.2)
        assert time.monotonic() - started < 5
