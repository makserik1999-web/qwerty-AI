"""Shared LLM client and the transient-error retry wrapper.

Moved verbatim out of science_manim_graph_agent.py.

Every call is dispatched to a private event loop on its own thread. That
is not tidiness, it is a defect in the SDK we depend on:
spoon_ai/llm/providers/gemini_provider.py calls the SYNCHRONOUS
google-genai client (`client.models.generate_content`) from inside
`async def chat`, so for the whole duration of that request nothing else
on the loop runs - including the websockets keepalive.

Measured: one such call held the loop for 383 seconds, during which a
100ms heartbeat ticked 7 times instead of ~3800. uvicorn pings every 20s
and closes after 20s without a pong, so the backend dropped the agent
mid-request and a finished 172-second answer was computed and thrown
away, with the student told the agent was unavailable.

This path is reached whenever OpenRouter fails and the fallback to the
native Gemini provider fires - and always, for every call, when
DEFAULT_LLM_PROVIDER=gemini.
"""

import asyncio
import threading
from typing import Any, Dict, Optional

from spoon_ai.llm import LLMManager

from anyq.config import (
    _LLM_RETRIES,
    _LLM_RETRY_BASE_DELAY,
    DEFAULT_LLM_PROVIDER,
    LLM_REASONING_EFFORT,
)

llm = LLMManager()

# Sent with every chat call as an OpenAI `extra_body`, which spoon_ai passes
# through untouched (openai_compatible_provider filters only model,
# max_tokens, temperature, tools and tool_choice out of **kwargs).
#
# Built once: the value cannot change without a restart, and rebuilding a
# dict per request would only hide that.
_REASONING_KWARGS: Dict[str, Any] = {}
if LLM_REASONING_EFFORT and DEFAULT_LLM_PROVIDER == "openrouter":
    _REASONING_KWARGS = {"extra_body": {"reasoning": {"effort": LLM_REASONING_EFFORT}}}

# The loop every provider call runs on. One loop, not one per call: the
# async HTTP client spoon_ai builds internally is bound to the loop that
# first creates it, and handing it a different one later raises
# "attached to a different loop". `llm` is touched nowhere else in the
# agent, so this stays the only loop that ever sees it.
_provider_loop: Optional[asyncio.AbstractEventLoop] = None
_provider_loop_lock = threading.Lock()


def _get_provider_loop() -> asyncio.AbstractEventLoop:
    """The private loop, started on first use."""
    global _provider_loop
    with _provider_loop_lock:
        if _provider_loop is None:
            loop = asyncio.new_event_loop()
            # Daemon: the agent exits by process exit, and this loop has
            # nothing to flush that outliving the process would save.
            threading.Thread(
                target=loop.run_forever,
                name="anyq-llm",
                daemon=True,
            ).start()
            _provider_loop = loop
    return _provider_loop


async def _chat_off_the_main_loop(messages, **kwargs):
    """Run one llm.chat() elsewhere, awaiting only its result here.

    Cancellation still works: wrap_future forwards it to the concurrent
    future, which cancels the coroutine on the other loop - so the
    REQUEST_DEADLINE_SEC timeout in agent_ws_client keeps its meaning.
    """
    future = asyncio.run_coroutine_threadsafe(
        llm.chat(messages, **kwargs), _get_provider_loop()
    )
    return await asyncio.wrap_future(future)


_TRANSIENT_LLM_MARKERS = (
    "503",
    "unavailable",
    "overloaded",
    "high demand",
    "resource_exhausted",
    "rate limit",
    "429 too many requests",
    "500 internal",
    "502 bad gateway",
    "504 gateway timeout",
    "deadline exceeded",
    "timed out",
)


def _is_transient_llm_error(exc: BaseException) -> bool:
    # Match against the tail of the message only - the actual API error reason
    # lives at the end; short arbitrary substrings like "500" or "timeout"
    # inside user-echoed text caused false retries.
    msg = str(exc).strip().lower()[-300:]
    return any(marker in msg for marker in _TRANSIENT_LLM_MARKERS)


async def _llm_chat(messages, **kwargs):
    """llm.chat() with backoff retry on transient upstream errors."""
    # A caller that passes its own extra_body means it, so never override it.
    if _REASONING_KWARGS and "extra_body" not in kwargs:
        kwargs = {**kwargs, **_REASONING_KWARGS}
    last_exc: Optional[BaseException] = None
    for attempt in range(_LLM_RETRIES + 1):
        try:
            return await _chat_off_the_main_loop(messages, **kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised below
            last_exc = exc
            if attempt >= _LLM_RETRIES or not _is_transient_llm_error(exc):
                raise
            delay = _LLM_RETRY_BASE_DELAY * (2 ** attempt)
            print(
                f"[llm] transient error (attempt {attempt + 1}/{_LLM_RETRIES + 1}), "
                f"retrying in {delay:.0f}s: {type(exc).__name__}: {str(exc)[-200:]}",
                flush=True,
            )
            await asyncio.sleep(delay)
    raise last_exc  # pragma: no cover - loop always returns or raises
