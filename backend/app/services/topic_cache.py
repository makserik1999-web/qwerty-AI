"""Videos filed by topic: answered once, watched by everyone who asks.

    video_cache   every successful video for a GENERAL question, filed under
                  its topic id. Served instead of rendering when the next
                  general question on the topic comes in.
    status        cached   - served, not yet looked at by the team
                  public   - checked by a person and on the showcase
                  rejected - never served again

Up to three versions per topic and language; the best by its 👍/👎 is the
one served. A new video takes the place of the worst unchecked version only
if that one is rated down - otherwise three is enough.

A specific question ("the legs are 3 and 4") is never filed: its video is
about that problem. Watching a filed video costs the viewer nothing - only
making a new one does.
"""

import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app import config
from app.db import db

CACHED, PUBLIC, REJECTED = "cached", "public", "rejected"
SERVABLE = (CACHED, PUBLIC)
MAX_VERSIONS = 3

TOPICS_PATH = Path(__file__).resolve().parent.parent / "data" / "topics.json"


@lru_cache(maxsize=1)
def topics() -> Dict[str, Dict[str, Any]]:
    with open(TOPICS_PATH, encoding="utf-8") as f:
        return {t["id"]: t for t in json.load(f)["topics"]}


def topic_title(topic_id: str, lang: str) -> str:
    topic = topics().get(topic_id) or {}
    return topic.get("kk" if lang == "kk" else "ru") or topic_id


def _score(entry: Dict[str, Any]) -> int:
    return int(entry.get("rating_up", 0)) - int(entry.get("rating_down", 0))


def _media_present(video_url: str) -> bool:
    name = os.path.basename(video_url or "")
    return bool(name) and (config.MEDIA_DIR / name).is_file()


async def best(topic_id: str, lang: str, *, narration: bool = True) -> Optional[Dict[str, Any]]:
    """The version to show for this topic in this language, or None.

    A video with sound is preferred when narration was asked for, a silent
    one when it was not; after that the better rated, a checked one before an
    unchecked one, and the newer. A file that is gone is skipped.

    A video known to be silent is never the answer to a request with the voice
    on: that is the choice quietly not happening, and the person would think
    narration is broken. It still answers a request with the voice off.
    """
    if not topic_id or not lang:
        return None
    candidates = [
        e async for e in db.db.video_cache.find(
            {"topic_id": topic_id, "lang": lang, "status": {"$in": list(SERVABLE)}})
    ]
    candidates = [e for e in candidates if _media_present(e.get("video_url", ""))
                  and not (narration and e.get("has_audio") is False)]
    if not candidates:
        return None

    def order(e):
        sound = e.get("has_audio")
        sound_match = 1 if sound is None or bool(sound) == narration else 0
        created = e.get("created_at")
        stamp = created.replace(tzinfo=created.tzinfo or timezone.utc).timestamp() \
            if isinstance(created, datetime) else 0
        return (sound_match, _score(e), 1 if e.get("status") == PUBLIC else 0, stamp)

    return max(candidates, key=order)


async def add(*, topic_id: str, lang: str, video_url: str, text: str, user_id: str,
              duration: Optional[float], has_audio: Optional[bool]) -> Optional[str]:
    """File a new video under its topic. Returns its id, or None if not kept."""
    topic = topics().get(topic_id)
    if not topic or not video_url or lang not in ("kk", "ru", "en"):
        return None
    existing = [
        e async for e in db.db.video_cache.find(
            {"topic_id": topic_id, "lang": lang, "status": {"$in": list(SERVABLE)}})
    ]
    if len(existing) >= MAX_VERSIONS:
        unchecked = [e for e in existing if e.get("status") == CACHED]
        worst = min(unchecked, key=_score, default=None)
        if not worst or _score(worst) >= 0:
            return None
        # Rated down and nobody vouched for it: this one takes its place.
        await db.db.video_cache.update_one({"_id": worst["_id"]}, {"$set": {"status": REJECTED,
                                                                          "replaced_at": datetime.now(timezone.utc)}})
    doc = {
        "topic_id": topic_id,
        "subject": topic["subject"],
        "grade": topic["grade"],
        "lang": lang,
        "title": topic_title(topic_id, lang),
        "video_url": video_url,
        "text": text[:20000],
        "duration": duration,
        "has_audio": has_audio,
        "rating_up": 0,
        "rating_down": 0,
        "status": CACHED,
        "created_by": user_id,
        "served": 0,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.db.video_cache.insert_one(doc)
    return str(result.inserted_id)


async def served(entry_id) -> None:
    await db.db.video_cache.update_one({"_id": entry_id}, {"$inc": {"served": 1}})


async def get(entry_id: str) -> Optional[Dict[str, Any]]:
    if not ObjectId.is_valid(entry_id or ""):
        return None
    return await db.db.video_cache.find_one({"_id": ObjectId(entry_id)})


async def rate(entry_id: str, user_id: str, value: int) -> Optional[Dict[str, int]]:
    """Set this person's vote to +1, -1 or 0 (none). Returns the new counts."""
    entry = await get(entry_id)
    if not entry:
        return None
    vote = await db.db.video_ratings.find_one({"video_id": entry_id, "user_id": user_id})
    old = int(vote["value"]) if vote else 0
    if old == value:
        return {"up": entry.get("rating_up", 0), "down": entry.get("rating_down", 0), "mine": value}
    inc = {"rating_up": (value == 1) - (old == 1), "rating_down": (value == -1) - (old == -1)}
    if value:
        await db.db.video_ratings.update_one(
            {"video_id": entry_id, "user_id": user_id},
            {"$set": {"value": value, "at": datetime.now(timezone.utc)}}, upsert=True)
    else:
        await db.db.video_ratings.delete_one({"video_id": entry_id, "user_id": user_id})
    await db.db.video_cache.update_one({"_id": entry["_id"]}, {"$inc": inc})
    fresh = await get(entry_id) or {}
    return {"up": fresh.get("rating_up", 0), "down": fresh.get("rating_down", 0), "mine": value}


async def my_vote(entry_id: str, user_id: str) -> int:
    vote = await db.db.video_ratings.find_one({"video_id": entry_id, "user_id": user_id})
    return int(vote["value"]) if vote else 0


def public_view(entry: Dict[str, Any]) -> Dict[str, Any]:
    created = entry.get("created_at")
    return {
        "id": str(entry["_id"]),
        "topic_id": entry.get("topic_id"),
        "subject": entry.get("subject"),
        "grade": entry.get("grade"),
        "lang": entry.get("lang"),
        "title": entry.get("title"),
        "video_url": entry.get("video_url"),
        "text": entry.get("text", ""),
        "duration": entry.get("duration"),
        "has_audio": entry.get("has_audio"),
        "rating_up": entry.get("rating_up", 0),
        "rating_down": entry.get("rating_down", 0),
        "status": entry.get("status"),
        "served": entry.get("served", 0),
        "created_at": created.isoformat() if isinstance(created, datetime) else None,
    }


async def showcase(subject: str = "", grade: Optional[int] = None, lang: str = "",
                   limit: int = 200) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"status": PUBLIC}
    if subject:
        query["subject"] = subject
    if grade:
        query["grade"] = grade
    if lang:
        query["lang"] = lang
    cursor = db.db.video_cache.find(query).sort([("subject", 1), ("grade", 1), ("title", 1)]).limit(limit)
    return [public_view(e) async for e in cursor if _media_present(e.get("video_url", ""))]
