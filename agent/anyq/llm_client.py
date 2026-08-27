"""Shared LLM client and the transient-error retry wrapper.

Moved verbatim out of science_manim_graph_agent.py.
"""

import asyncio
from typing import Optional

from spoon_ai.llm import LLMManager

from anyq.config import _LLM_RETRIES, _LLM_RETRY_BASE_DELAY


llm = LLMManager()

_TRANSIENT_LLM_MARKERS = (
    "503",
    "unavailable",
    "overloaded",
    "high demand",
    "429",
    "resource_exhausted",
    "rate limit",
    "500",
    "internal error",
    "502",
    "504",
    "deadline exceeded",
    "timeout",
)


def _is_transient_llm_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_LLM_MARKERS)


async def _llm_chat(messages, **kwargs):
    """llm.chat() with backoff retry on transient upstream errors."""
    last_exc: Optional[BaseException] = None
    for attempt in range(_LLM_RETRIES + 1):
        try:
            return await llm.chat(messages, **kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised below
            last_exc = exc
            if attempt >= _LLM_RETRIES or not _is_transient_llm_error(exc):
                raise
            delay = _LLM_RETRY_BASE_DELAY * (2 ** attempt)
            print(
                f"[llm] transient error (attempt {attempt + 1}/{_LLM_RETRIES + 1}), "
                f"retrying in {delay:.0f}s: {exc}",
                flush=True,
            )
            await asyncio.sleep(delay)
    raise last_exc  # pragma: no cover - loop always returns or raises
