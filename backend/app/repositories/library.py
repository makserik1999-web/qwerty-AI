"""The answer cache: counters, stored answers and their storage tiers.

Two collections, deliberately separate:

- `question_stats` is a counter per normalised question. It is tiny (tens of
  bytes) and every question gets one, asked once or a thousand times.
- `library_entries` holds an actual answer, and only questions that have
  earned one are allowed in.

That split is the whole storage policy: counting is cheap, keeping video is
not, so we count everything and keep only what repeats.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.config import (
    CACHE_EPHEMERAL_TTL_HOURS,
    CACHE_WARM_PROMOTION_HITS,
    CACHE_WARM_TTL_DAYS,
)
from app.db import db

TIER_EPHEMERAL = "ephemeral"
TIER_WARM = "warm"
TIER_CURATED = "curated"


def _expiry_for(tier: str) -> Optional[datetime]:
    """When an entry in this tier should stop being served.

    Curated entries return None: the TTL index ignores documents whose
    `expires_at` is missing, so a hand-approved video is never swept away.
    """
    now = datetime.now(timezone.utc)
    if tier == TIER_CURATED:
        return None
    if tier == TIER_WARM:
        return now + timedelta(days=CACHE_WARM_TTL_DAYS)
    return now + timedelta(hours=CACHE_EPHEMERAL_TTL_HOURS)


async def record_question(cache_key: str, normalized: str, language: str = "") -> int:
    """Count one occurrence of a question and return its running total."""
    now = datetime.now(timezone.utc)
    doc = await db.db.question_stats.find_one_and_update(
        {"_id": cache_key},
        {
            "$inc": {"hits": 1},
            "$set": {"normalized_question": normalized, "language": language, "last_seen": now},
            "$setOnInsert": {"first_seen": now},
        },
        upsert=True,
        return_document=True,
    )
    return int((doc or {}).get("hits", 1))


async def get_entry(cache_key: str) -> Optional[Dict[str, Any]]:
    """The stored answer for a key, if one is still live.

    `expires_at` is checked here as well as by the TTL index, because that
    index only runs about once a minute and we must never serve an answer we
    have already decided is stale.
    """
    entry = await db.db.library_entries.find_one({"cache_key": cache_key})
    if not entry:
        return None

    expires_at = entry.get("expires_at")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return None
    return entry


async def touch_entry(cache_key: str, question_hits: int) -> None:
    """Register a cache hit, and promote the entry if it has earned it.

    Promotion is what keeps the disk honest: an answer only graduates from the
    48-hour tier to the 30-day one once the question has actually come back.
    """
    entry = await db.db.library_entries.find_one({"cache_key": cache_key})
    if not entry:
        return

    tier = entry.get("tier", TIER_EPHEMERAL)
    if tier == TIER_EPHEMERAL and question_hits >= CACHE_WARM_PROMOTION_HITS:
        tier = TIER_WARM

    update: Dict[str, Any] = {
        "$inc": {"hits": 1},
        "$set": {"last_hit_at": datetime.now(timezone.utc), "tier": tier},
    }
    # Every hit renews the clock, so a question in steady use never expires.
    if tier == TIER_CURATED:
        update["$unset"] = {"expires_at": ""}
    else:
        update["$set"]["expires_at"] = _expiry_for(tier)

    await db.db.library_entries.update_one({"cache_key": cache_key}, update)


async def store_entry(
    cache_key: str,
    normalized: str,
    educator_text: str,
    video_url: Optional[str],
    language: str = "",
    pipeline_version: str = "",
    variant: str = "",
    tier: str = TIER_EPHEMERAL,
) -> None:
    """Write an answer into the cache, replacing any earlier one for the key.

    A curated entry is never overwritten by a generated one: hand-approved
    content outranks whatever the model produced this time.
    """
    existing = await db.db.library_entries.find_one({"cache_key": cache_key})
    if existing and existing.get("tier") == TIER_CURATED and tier != TIER_CURATED:
        return

    now = datetime.now(timezone.utc)
    await db.db.library_entries.update_one(
        {"cache_key": cache_key},
        {
            "$set": {
                "normalized_question": normalized,
                "educator_text": educator_text,
                "video_url": video_url,
                "language": language,
                "pipeline_version": pipeline_version,
                # Stored, not just hashed into the key: the semantic layer
                # searches by meaning and never sees the key, so without this
                # column it cannot tell a silent answer from a spoken one.
                "variant": variant,
                "tier": tier,
                "expires_at": _expiry_for(tier),
                "last_hit_at": now,
            },
            "$setOnInsert": {"created_at": now, "hits": 0},
        },
        upsert=True,
    )


async def cache_stats() -> Dict[str, Any]:
    """Counts per tier plus the questions seen most often."""
    per_tier = {
        row["_id"]: row["count"]
        async for row in db.db.library_entries.aggregate(
            [{"$group": {"_id": "$tier", "count": {"$sum": 1}}}]
        )
    }
    total_questions = await db.db.question_stats.count_documents({})
    repeated = await db.db.question_stats.count_documents({"hits": {"$gt": 1}})

    top = [
        {"question": row.get("normalized_question", ""), "hits": row.get("hits", 0)}
        async for row in db.db.question_stats.find().sort("hits", -1).limit(20)
    ]
    return {
        "entries_by_tier": per_tier,
        "entries_total": sum(per_tier.values()),
        "questions_seen": total_questions,
        "questions_repeated": repeated,
        "top_questions": top,
    }


# --------------------------------------------------------------------------
# Curated entries
#
# A curated entry is not a cached answer that happened to survive - it is a
# video a person watched and approved, so it is written by the seeding tool
# rather than earned by repetition. Two things follow: it never expires, and
# it is addressed by (topic_id, language) so re-seeding can replace exactly
# the keys a topic used to own.
# --------------------------------------------------------------------------


async def replace_curated_topic(
    topic_id: str,
    language: str,
    keys: Dict[str, str],
    educator_text: str,
    video_url: str,
    pipeline_version: str = "",
) -> Dict[str, int]:
    """Publish one language of one topic, and retire the keys it dropped.

    `keys` maps cache_key -> normalised question, one per alias. Aliases the
    topic no longer lists are deleted, otherwise an alias removed from
    topic.yaml would keep resolving to the video forever.
    """
    now = datetime.now(timezone.utc)
    written = 0
    for cache_key, normalized in keys.items():
        await db.db.library_entries.update_one(
            {"cache_key": cache_key},
            {
                "$set": {
                    "normalized_question": normalized,
                    "educator_text": educator_text,
                    "video_url": video_url,
                    "language": language,
                    "pipeline_version": pipeline_version,
                    "tier": TIER_CURATED,
                    "topic_id": topic_id,
                    "last_hit_at": now,
                },
                # A curated entry has no expiry at all: the TTL index skips
                # documents without the field, so it is never swept.
                "$unset": {"expires_at": ""},
                "$setOnInsert": {"created_at": now, "hits": 0},
            },
            upsert=True,
        )
        written += 1

    stale = await db.db.library_entries.delete_many(
        {
            "topic_id": topic_id,
            "language": language,
            "tier": TIER_CURATED,
            "cache_key": {"$nin": list(keys)},
        }
    )
    return {"written": written, "retired": stale.deleted_count}


async def curated_entry_for(topic_id: str, language: str) -> Optional[Dict[str, Any]]:
    """Any published entry for this topic and language, to reuse its video."""
    return await db.db.library_entries.find_one(
        {"topic_id": topic_id, "language": language, "tier": TIER_CURATED}
    )


async def curated_topics() -> Dict[str, Dict[str, Any]]:
    """What is published right now, keyed by "<topic_id>/<language>"."""
    published: Dict[str, Dict[str, Any]] = {}
    async for entry in db.db.library_entries.find({"tier": TIER_CURATED}):
        topic_id = entry.get("topic_id")
        if not topic_id:
            continue
        slot = f"{topic_id}/{entry.get('language', '')}"
        row = published.setdefault(
            slot,
            {
                "topic_id": topic_id,
                "language": entry.get("language", ""),
                "video_url": entry.get("video_url"),
                "pipeline_version": entry.get("pipeline_version", ""),
                "aliases": 0,
                "hits": 0,
            },
        )
        row["aliases"] += 1
        row["hits"] += int(entry.get("hits", 0))
    return published
