"""Turning a question into a vector, for the semantic layer of the cache.

This lives in the agent and not in the backend for one reason: the Gemini key
is here. Chat goes through OpenRouter now, but OpenRouter serves no embedding
models, so embeddings still call Google directly - and copying the key into a
second service to save a WebSocket round trip is a bad trade.

The agent also answers with the language it detected, because it already owns
that decision for the generated answer. Having the backend detect it again
would be two implementations of one rule, drifting apart in exactly the case
that is hard to get right (Kazakh written without its own letters).

768 dimensions rather than the model's native 3072: the model is trained so a
truncated prefix stays meaningful, and measured on this product's own
questions the two agree to the third decimal while the short one takes a
quarter of the storage.
"""

from __future__ import annotations

import asyncio
import time
from typing import List, Optional

from anyq.config import _LLM_RETRIES, _LLM_RETRY_BASE_DELAY, GEMINI_API_KEY
from anyq.language import _detect_language
from anyq.llm_client import _is_transient_llm_error

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768


def _embed_sync(text: str) -> List[float]:
    from google import genai
    from google.genai import types

    with genai.Client(api_key=GEMINI_API_KEY) as client:
        for attempt in range(_LLM_RETRIES + 1):
            try:
                response = client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=text,
                    config=types.EmbedContentConfig(
                        output_dimensionality=EMBEDDING_DIMENSIONS
                    ),
                )
                return list(response.embeddings[0].values)
            except Exception as exc:  # noqa: BLE001 - re-raised below
                if attempt >= _LLM_RETRIES or not _is_transient_llm_error(exc):
                    raise
                time.sleep(_LLM_RETRY_BASE_DELAY * (2 ** attempt))
    raise RuntimeError("unreachable")


async def embed_question(text: str) -> Optional[dict]:
    """The vector and language for one question, or None if unavailable.

    Returns None rather than raising: the semantic layer is an optimisation,
    and a failure here must degrade to "no semantic hit", never to a failed
    question.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if not GEMINI_API_KEY:
        return None

    try:
        vector = await asyncio.to_thread(_embed_sync, cleaned)
    except Exception as exc:  # noqa: BLE001
        print(f"[embed] failed: {type(exc).__name__}: {str(exc)[-200:]}", flush=True)
        return None

    return {
        "vector": vector,
        "language": _detect_language(cleaned) or "",
        "model": EMBEDDING_MODEL,
        "dimensions": len(vector),
    }
