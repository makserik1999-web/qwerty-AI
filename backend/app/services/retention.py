"""Keeping the rendered-video directory inside its disk budget.

Nothing here runs unless the directory is actually over the high-water mark:
deleting videos that fit is pure loss. When it does run, it removes the least
valuable files until usage is back under the low-water mark, and it repairs
the database as it goes so no chat is left pointing at a file that is gone.

What is never deleted:
- anything a curated (hand-reviewed) library entry points at
- anything younger than MEDIA_MIN_AGE_HOURS, so a video cannot disappear from
  under the person who just asked for it
"""

import asyncio
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from app import config
from app.config import (
    MEDIA_GC_HIGH_WATER,
    MEDIA_GC_INTERVAL_SEC,
    MEDIA_GC_LOW_WATER,
    MEDIA_MAX_BYTES,
    MEDIA_MIN_AGE_HOURS,
)
from app.db import db
from app.repositories.library import TIER_CURATED

# How quickly a file's value decays once nobody asks for it. Two weeks without
# a hit halves the score, so steady favourites outlive one-off curiosities.
_HALF_LIFE_DAYS = 14.0


def _score(hits: int, age_days: float, size_bytes: int) -> float:
    """Value per megabyte kept. Lower scores are deleted first."""
    size_mb = max(size_bytes / (1024 * 1024), 0.01)
    recency = math.exp(-age_days / _HALF_LIFE_DAYS)
    # hits + 1 so a never-reused file still ranks by age and size rather than
    # collapsing every candidate to zero.
    return (hits + 1) * recency / size_mb


async def _referenced_entries() -> Dict[str, Dict[str, Any]]:
    """Library entries keyed by the media filename they point at."""
    by_file: Dict[str, Dict[str, Any]] = {}
    async for entry in db.db.library_entries.find({"video_url": {"$ne": None}}):
        filename = str(entry.get("video_url", "")).rsplit("/", 1)[-1]
        if filename:
            by_file[filename] = entry
    return by_file


async def _forget_file(filename: str) -> None:
    """Drop every database reference to a file that no longer exists.

    Messages keep their text and lose only the video, so an old chat degrades
    to "explanation without the animation" rather than to a broken player.
    """
    video_url = f"/media/{filename}"
    await db.db.library_entries.delete_many({"video_url": video_url})
    await db.db.messages.update_many({"video_url": video_url}, {"$set": {"video_url": None}})
    await db.db.chats.update_many(
        {"current_video_url": video_url}, {"$set": {"current_video_url": None}}
    )


async def collect_garbage(dry_run: bool = False) -> Dict[str, Any]:
    """Bring the media directory back under budget. Returns what it did."""
    media_dir: Path = config.MEDIA_DIR
    if not media_dir.is_dir():
        return {"status": "no_media_dir", "deleted": 0, "freed_bytes": 0}

    files: List[Dict[str, Any]] = []
    total = 0
    for path in media_dir.iterdir():
        if not path.is_file():
            continue
        try:
            stat_result = path.stat()
        except OSError:
            continue
        files.append({"path": path, "name": path.name, "size": stat_result.st_size,
                      "mtime": stat_result.st_mtime})
        total += stat_result.st_size

    if total <= MEDIA_MAX_BYTES * MEDIA_GC_HIGH_WATER:
        return {
            "status": "under_budget",
            "used_bytes": total,
            "budget_bytes": MEDIA_MAX_BYTES,
            "deleted": 0,
            "freed_bytes": 0,
        }

    entries = await _referenced_entries()
    now = datetime.now(timezone.utc)
    min_age = timedelta(hours=MEDIA_MIN_AGE_HOURS)

    candidates = []
    protected = 0
    for item in files:
        entry = entries.get(item["name"])
        if entry and entry.get("tier") == TIER_CURATED:
            protected += 1
            continue

        modified = datetime.fromtimestamp(item["mtime"], tz=timezone.utc)
        if now - modified < min_age:
            # Too fresh: somebody may be watching it right now.
            protected += 1
            continue

        last_hit = entry.get("last_hit_at") if entry else None
        if last_hit is not None and last_hit.tzinfo is None:
            last_hit = last_hit.replace(tzinfo=timezone.utc)
        reference = last_hit or modified
        age_days = max((now - reference).total_seconds() / 86400.0, 0.0)

        item["score"] = _score(int((entry or {}).get("hits", 0)), age_days, item["size"])
        candidates.append(item)

    candidates.sort(key=lambda c: c["score"])

    target = MEDIA_MAX_BYTES * MEDIA_GC_LOW_WATER
    deleted, freed, failed = 0, 0, 0
    for item in candidates:
        if total <= target:
            break
        if dry_run:
            total -= item["size"]
            freed += item["size"]
            deleted += 1
            continue
        try:
            item["path"].unlink()
        except OSError as e:
            print(f"[retention] could not remove {item['name']}: {type(e).__name__}: {e}")
            failed += 1
            continue
        await _forget_file(item["name"])
        total -= item["size"]
        freed += item["size"]
        deleted += 1

    result = {
        "status": "collected",
        "used_bytes": total,
        "budget_bytes": MEDIA_MAX_BYTES,
        "deleted": deleted,
        "freed_bytes": freed,
        "protected": protected,
        "failed": failed,
        "dry_run": dry_run,
    }
    if total > target:
        # Everything left is curated or too new. Say so loudly rather than
        # quietly deleting content that was promised to be permanent.
        result["status"] = "still_over_budget"
        print(
            "[retention] still over budget after collection - the remainder is "
            "curated or too recent to remove. Raise MEDIA_MAX_BYTES or review "
            "the curated library."
        )
    print(f"[retention] {result}")
    return result


async def retention_loop() -> None:
    """Periodic collection, started from the application lifespan."""
    while True:
        await asyncio.sleep(MEDIA_GC_INTERVAL_SEC)
        try:
            await collect_garbage()
        except Exception as e:
            # Retention failing must never take the backend down with it.
            print(f"[retention] sweep failed: {type(e).__name__}: {e}")
