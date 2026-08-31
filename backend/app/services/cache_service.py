"""Deciding what may enter the cache, and serving what is already in it.

The admission rules matter more than the lookup. A cache that stores every
answer fills the disk with questions nobody will ask twice; one that stores
none saves nothing. So: count every question, keep only answers that are
expensive to produce and safe to repeat.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from app import config
from app.cache.normalize import cache_key, normalize_question
from app.config import CACHE_MAX_QUESTION_LEN, PIPELINE_VERSION
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


def key_for(prompt: str) -> Tuple[str, str]:
    """The (normalised question, cache key) pair for a prompt."""
    normalized = normalize_question(prompt)
    return normalized, cache_key(normalized, PIPELINE_VERSION)


async def lookup(prompt: str, screenshots: List[Any]) -> Optional[Dict[str, Any]]:
    """Return a stored answer for this question, or None.

    Also records the question in the counters, because a miss is exactly the
    signal that decides whether the answer about to be generated is worth
    keeping.
    """
    allowed, _ = cacheable_request(prompt, screenshots)
    if not allowed:
        return None

    normalized, key = key_for(prompt)
    hits = await library.record_question(key, normalized)

    entry = await library.get_entry(key)
    if not entry:
        return None

    # The answer may reference a video that retention has since removed.
    # Serving a dead link is worse than regenerating.
    video_url = entry.get("video_url")
    if video_url and not _media_present(video_url):
        return None

    await library.touch_entry(key, hits)
    return entry


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

    normalized, key = key_for(prompt)
    await library.store_entry(
        cache_key=key,
        normalized=normalized,
        educator_text=text,
        video_url=video_url,
        pipeline_version=PIPELINE_VERSION,
    )
    return True
