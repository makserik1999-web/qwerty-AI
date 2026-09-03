"""Finding a stored answer to the same question asked differently.

The exact layer hashes the wording, so "что такое сила тяжести" and "что такое
гравитация" are two questions to it. This layer compares meaning instead.

Everything here is shaped by one measurement. On labelled pairs of this
product's own questions:

    same question, different words   0.701 ... 0.937
    genuinely different questions    0.633 ... 0.797

The bands overlap, so no threshold is right - only more or less wrong in a
chosen direction. A miss costs what the system costs today; a false hit hands
someone an answer to a question they did not ask. So the threshold sits above
every observed different-question pair, and half the paraphrases are given up
deliberately.

The other measurement decided the language rule outright: the same question in
Kazakh and Russian scores 0.92, higher than any paraphrase within one
language. Comparing across languages would therefore match those first, and a
Kazakh student would be handed a Russian video. Matching is same-language
only, and that is not a tuning knob.
"""

import math
from typing import Any, Dict, List, Optional, Sequence

from app.config import (
    CACHE_SEMANTIC_MAX_CANDIDATES,
    CACHE_SEMANTIC_THRESHOLD,
)
from app.db import db


def normalise(vector: Sequence[float]) -> List[float]:
    """Scale to unit length, so similarity is a plain dot product later.

    Done once at write time rather than on every comparison: the scan below
    runs over every stored vector of a language, and a square root per
    candidate is the difference between a cheap lookup and a slow one.
    """
    magnitude = math.sqrt(sum(x * x for x in vector))
    if magnitude == 0:
        return []
    return [x / magnitude for x in vector]


def similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two already-normalised vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    # strict=True: differing lengths mean the stored vector came from a
    # different embedding model, and comparing the overlap would produce a
    # plausible-looking score from unrelated numbers. The length check
    # above already returns 0.0 for that case.
    return sum(x * y for x, y in zip(a, b, strict=True))


async def find_similar(
    vector: Sequence[float],
    language: str,
    threshold: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """The closest stored answer above the threshold, or None.

    A linear scan in this process, on purpose: at the volumes this serves it
    is a few milliseconds, and a vector database would be a service to run,
    back up and keep in sync for a gain nobody would notice. The candidate
    cap is where that stops being true - past it the scan should move to an
    index rather than quietly getting slower.
    """
    cutoff = CACHE_SEMANTIC_THRESHOLD if threshold is None else threshold
    if not vector or not language:
        # No language means no safe comparison: see the module docstring.
        return None

    query = normalise(vector)
    if not query:
        return None

    best: Optional[Dict[str, Any]] = None
    best_score = cutoff
    scanned = 0

    cursor = db.db.library_entries.find(
        {"language": language, "embedding": {"$exists": True, "$ne": []}},
        # Only what the comparison and the answer need; an entry's full text
        # is fetched once, for the winner.
        {"cache_key": 1, "embedding": 1, "normalized_question": 1},
    ).limit(CACHE_SEMANTIC_MAX_CANDIDATES)

    async for entry in cursor:
        scanned += 1
        score = similarity(query, entry.get("embedding") or [])
        if score > best_score:
            best_score = score
            best = entry

    if best is None:
        return None

    full = await db.db.library_entries.find_one({"cache_key": best["cache_key"]})
    if not full:
        return None
    full["semantic_score"] = round(best_score, 4)
    full["semantic_scanned"] = scanned
    return full


async def attach_embedding(
    cache_key: str, vector: Sequence[float], language: str, model: str = ""
) -> bool:
    """Store a normalised vector on an existing entry."""
    unit = normalise(vector)
    if not unit or not language:
        return False
    result = await db.db.library_entries.update_one(
        {"cache_key": cache_key},
        {"$set": {"embedding": unit, "language": language, "embedding_model": model}},
    )
    return result.matched_count > 0
