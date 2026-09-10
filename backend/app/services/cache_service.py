"""Deciding what may enter the cache, and serving what is already in it.

The admission rules matter more than the lookup. A cache that stores every
answer fills the disk with questions nobody will ask twice; one that stores
none saves nothing. So: count every question, keep only answers that are
expensive to produce and safe to repeat.
"""

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

from app import config
from app.cache import semantic
from app.cache.normalize import cache_key, normalize_question
from app.config import (
    CACHE_EMBED_TIMEOUT_SEC,
    CACHE_MAX_QUESTION_LEN,
    CACHE_SEMANTIC_ENABLED,
    PIPELINE_VERSION,
)
from app.repositories import library

# Signals that a question is personal rather than a general topic. A cached
# answer to "check my homework" would be wrong for the next person asking it.
#
# Written as patterns rather than a phrase list because Russian declines both
# halves: "моя задача", "мою задачу" and "моей задачи" are the same request,
# and a literal list catches only whichever form someone happened to write.
_PERSONAL_PATTERNS = (
    # Russian: any form of мой/моя/моё + any form of the usual homework nouns.
    re.compile(
        r"\bмо[йяеёюих]\w*\s+(задач|задани|контрольн|домашк|пример|вариант|тест|работ|эссе)",
        re.IGNORECASE | re.UNICODE,
    ),
    # Kazakh: менің + a noun carrying the 1st-person possessive suffix.
    re.compile(r"\bменің\s+\w*(тапсырма|жұмыс|есеб|бақылау)", re.IGNORECASE | re.UNICODE),
    re.compile(r"\b(үй\s+жұмысым|тапсырмам)\b", re.IGNORECASE | re.UNICODE),
    # English: possessive + the same set of nouns.
    re.compile(
        r"\bmy\s+(homework|assignment|test|essay|problem|exercise|task|paper)",
        re.IGNORECASE,
    ),
)


def cacheable_request(prompt: str, screenshots: List[Any]) -> Tuple[bool, str]:
    """Whether this question may be answered from, or written to, the cache.

    Returns (allowed, reason) - the reason is for metrics and logs, never for
    the user.
    """
    if screenshots:
        # A screenshot makes the request unique by definition: the answer is
        # about that image, not about the words next to it.
        return False, "has_screenshots"

    normalized = normalize_question(prompt)
    if not normalized:
        return False, "empty_after_normalisation"
    if len(normalized) > CACHE_MAX_QUESTION_LEN:
        # Long prompts are personal problems, not "frequently asked questions".
        return False, "too_long"

    if any(pattern.search(normalized) for pattern in _PERSONAL_PATTERNS):
        return False, "looks_personal"

    return True, "ok"


def render_variant(narration: bool, voice: str, length: str = "") -> str:
    """What the request chose about the video, as a cache-key fragment.

    Two people asking the same question get the same answer only if they asked
    for the same thing to be made. Narration is the first setting where that
    stops being automatic: the words are identical, the video is not.

    Length is the second, and it matters even with the voice off: somebody who
    asked for a thirty-second explanation must not be handed a stored
    ninety-second one just because the question matched. That is the whole
    point of choosing.

    Neither value is interpolated blindly - callers pass values already
    checked against NARRATION_VOICES and VIDEO_LENGTHS, because this string
    ends up in a hash and free text there means unlimited keys for one
    question.

    An empty `length` reproduces the pre-length fragment exactly, so a caller
    that does not care about length still reaches entries stored before this
    existed.
    """
    key = f"voice={voice}" if narration else "silent"
    return f"{key},len={length}" if length else key


def key_for(prompt: str, variant: str = "") -> Tuple[str, str]:
    """The (normalised question, cache key) pair for a prompt."""
    normalized = normalize_question(prompt)
    return normalized, cache_key(normalized, PIPELINE_VERSION, variant)


async def lookup(prompt: str, screenshots: List[Any],
                 variant: str = "") -> Optional[Dict[str, Any]]:
    """Return a stored answer for this question, or None.

    Also records the question in the counters, because a miss is exactly the
    signal that decides whether the answer about to be generated is worth
    keeping.
    """
    allowed, _ = cacheable_request(prompt, screenshots)
    if not allowed:
        return None

    normalized, key = key_for(prompt, variant)
    hits = await library.record_question(key, normalized)

    entry = await library.get_entry(key)
    if entry and _usable(entry):
        await library.touch_entry(key, hits)
        entry["match"] = "exact"
        return entry

    # Nothing with this exact wording. Ask whether the same question is
    # already answered under different words - which costs a round trip to
    # the agent, so it runs only after the free lookup has failed.
    return await _semantic_lookup(prompt, normalized, variant)


def _usable(entry: Dict[str, Any]) -> bool:
    """An entry is only servable while the video it points at still exists.

    Retention may have collected it since; a dead player is worse than the
    wait for a fresh render.
    """
    video_url = entry.get("video_url")
    return not video_url or _media_present(video_url)


async def _semantic_lookup(prompt: str, normalized: str,
                           variant: str = "") -> Optional[Dict[str, Any]]:
    if not CACHE_SEMANTIC_ENABLED:
        return None

    # Imported here rather than at module scope: the manager is part of the
    # WebSocket layer, and the cache is used from it.
    from app.ws.manager import agent_manager

    embedding = await agent_manager.request_embedding(prompt, CACHE_EMBED_TIMEOUT_SEC)
    if not embedding or not embedding.get("vector") or not embedding.get("language"):
        return None

    match = await semantic.find_similar(
        embedding["vector"], embedding["language"], PIPELINE_VERSION, variant
    )
    if not match or not _usable(match):
        return None

    await library.touch_entry(match["cache_key"], question_hits=1)
    match["match"] = "semantic"
    # The stored question was worded differently, so the reader is told which
    # one was answered - they can see it is not what they meant and ask again.
    match["matched_question"] = match.get("normalized_question", "")
    return match


def _media_present(video_url: str) -> bool:
    filename = video_url.rsplit("/", 1)[-1]
    if not config._SAFE_MEDIA_RE.fullmatch(filename):
        return False
    return (config.MEDIA_DIR / filename).is_file()


async def remember(
    prompt: str,
    screenshots: List[Any],
    text: str,
    video_url: Optional[str],
    variant: str = "",
) -> bool:
    """Store a freshly generated answer, if it qualifies. Returns whether it did.

    Only answers that produced a VIDEO are kept. That is where the minutes and
    the tokens go, and it is an unambiguous signal that the pipeline succeeded:
    a text-only reply may be a polite refusal, a degraded-mode notice or an
    off-topic rejection, none of which should be handed to the next person.
    """
    allowed, _ = cacheable_request(prompt, screenshots)
    if not allowed:
        return False
    if not video_url or not text.strip():
        return False

    normalized, key = key_for(prompt, variant)
    await library.store_entry(
        cache_key=key,
        normalized=normalized,
        educator_text=text,
        video_url=video_url,
        pipeline_version=PIPELINE_VERSION,
        variant=variant,
    )
    _schedule_embedding(key, prompt)
    return True


# Fire-and-forget tasks, held so the garbage collector cannot cancel them
# mid-flight - asyncio keeps only a weak reference to a running task.
_embedding_tasks: set = set()


def _schedule_embedding(key: str, prompt: str) -> None:
    """Attach a vector to the stored answer, in the background.

    Background, not awaited, and that is not an optimisation - it is required.
    This runs from the agent's receive loop, and asking the agent for an
    embedding means waiting for a frame that only that same loop can read.
    Awaiting here deadlocks until the request times out, silently, and no
    answer ever gets a vector.
    """
    if not CACHE_SEMANTIC_ENABLED:
        return
    task = asyncio.create_task(_attach_embedding(key, prompt))
    _embedding_tasks.add(task)
    task.add_done_callback(_embedding_tasks.discard)


async def _attach_embedding(key: str, prompt: str) -> None:
    """Give the stored answer a vector, so later phrasings can find it.

    Failures are swallowed: the entry is already saved and servable by exact
    match, and an answer without a vector is simply invisible to the semantic
    layer rather than broken.
    """
    from app.ws.manager import agent_manager

    try:
        embedding = await agent_manager.request_embedding(prompt, CACHE_EMBED_TIMEOUT_SEC)
        if not embedding or not embedding.get("vector"):
            print(f"[cache] no embedding for {key[:12]} - stays exact-match only")
            return
        await semantic.attach_embedding(
            key, embedding["vector"], embedding.get("language", ""),
            embedding.get("model", ""),
        )
    except Exception as e:  # noqa: BLE001
        print(f"embedding write failed: {type(e).__name__}: {e}")
