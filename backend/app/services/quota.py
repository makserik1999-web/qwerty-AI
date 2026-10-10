"""How much rendering one account may ask for.

Closing the service behind a login stops anonymous abuse and nothing else:
signup is open, and a logged-in user could previously queue an unbounded
number of renders and hold the only agent indefinitely. This is the part that
makes "authorised only" a real limit rather than a speed bump.

Three rules, in the order they bite:

1. **One generation at a time.** This is the actual protection. A render
   occupies the agent for about a minute and a half, so a single slot means a
   user cannot enqueue faster than the queue drains, whatever the other
   numbers say.
2. **Per hour and per day**, as comfort ceilings on top of that.
3. **A global queue cap**, because with one agent a long queue is a promise
   nobody can keep.

Two things deliberately do NOT count:

- **Answers from the library.** A cache hit costs a couple of database reads,
  so charging for it would penalise exactly the behaviour that protects the
  system. This also makes the cache do double duty as load protection.
- **Failed generations.** Taking someone's quota for a video they never got is
  charging them for our failure.

The counters live in Mongo rather than in memory: an in-memory budget resets
on restart, which turns "crash the backend" into a quota bypass.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.config import (
    GENERATION_MAX_CONCURRENT,
    GENERATION_MAX_PER_DAY,
    GENERATION_MAX_PER_HOUR,
    GENERATION_QUEUE_MAX,
)
from app.db import db


@dataclass
class Verdict:
    """Whether a generation may start, and what to tell the user if not."""

    allowed: bool
    reason: str = ""
    # What the UI shows so nobody is surprised by the refusal that follows.
    remaining_hour: int = 0
    remaining_day: int = 0
    retry_after_sec: int = 0


async def _count_since(user_id: str, since: datetime) -> int:
    return await db.db.generation_events.count_documents(
        {"user_id": user_id, "created_at": {"$gte": since}}
    )


async def _oldest_since(user_id: str, since: datetime) -> Optional[datetime]:
    """When the earliest counted generation happened - i.e. when a slot frees."""
    doc = await db.db.generation_events.find_one(
        {"user_id": user_id, "created_at": {"$gte": since}},
        sort=[("created_at", 1)],
    )
    if not doc:
        return None
    created = doc.get("created_at")
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created


async def check(user_id: str, in_flight: int, queue_depth: int) -> Verdict:
    """May this user start a generation right now?

    `in_flight` and `queue_depth` come from the agent manager's pending
    requests, which is the live truth about what is actually running - a
    database counter would drift the moment a request failed.
    """
    now = datetime.now(timezone.utc)
    hour_start = now - timedelta(hours=1)
    day_start = now - timedelta(days=1)

    used_hour = await _count_since(user_id, hour_start)
    used_day = await _count_since(user_id, day_start)
    remaining_hour = max(0, GENERATION_MAX_PER_HOUR - used_hour)
    remaining_day = max(0, GENERATION_MAX_PER_DAY - used_day)

    def verdict(reason: str, retry_after: int = 0) -> Verdict:
        return Verdict(
            allowed=not reason,
            reason=reason,
            remaining_hour=remaining_hour,
            remaining_day=remaining_day,
            retry_after_sec=retry_after,
        )

    if in_flight >= GENERATION_MAX_CONCURRENT:
        # Phrased as "wait", not "denied": nothing was lost, the previous
        # request is still coming.
        return verdict(
            "Your previous video is still being made. Wait for it to finish, "
            "then ask the next question."
        )

    if queue_depth >= GENERATION_QUEUE_MAX:
        return verdict(
            "The service is busy right now - too many videos are being made. "
            "Try again in a few minutes."
        )

    if remaining_day <= 0:
        oldest = await _oldest_since(user_id, day_start)
        retry = int((oldest + timedelta(days=1) - now).total_seconds()) if oldest else 3600
        return verdict(
            f"You have used your {GENERATION_MAX_PER_DAY} videos for today. "
            "Answers already in the library still work.",
            max(retry, 60),
        )

    if remaining_hour <= 0:
        oldest = await _oldest_since(user_id, hour_start)
        retry = int((oldest + timedelta(hours=1) - now).total_seconds()) if oldest else 600
        return verdict(
            f"You have made {GENERATION_MAX_PER_HOUR} videos in the last hour. "
            "Answers already in the library still work.",
            max(retry, 60),
        )

    return verdict("")


async def record(user_id: str, request_id: str) -> None:
    """Count one generation, keyed by the request it belongs to.

    Keyed rather than anonymous so it can be given back: `refund` needs to
    find this exact event when the generation fails.
    """
    await db.db.generation_events.insert_one(
        {
            "user_id": user_id,
            "request_id": request_id,
            "created_at": datetime.now(timezone.utc),
            # The TTL index needs a wider window than the longest quota
            # period, or a day-old event would vanish before the daily count
            # stopped caring about it.
            "expires_at": datetime.now(timezone.utc) + timedelta(days=2),
        }
    )


async def refund(request_id: str) -> bool:
    """Give the quota back for a generation that produced nothing."""
    result = await db.db.generation_events.delete_one({"request_id": request_id})
    return result.deleted_count > 0


async def usage(user_id: str) -> Dict[str, Any]:
    """What is left, for showing before the user runs out rather than after."""
    now = datetime.now(timezone.utc)
    used_hour = await _count_since(user_id, now - timedelta(hours=1))
    used_day = await _count_since(user_id, now - timedelta(days=1))
    return {
        "used_hour": used_hour,
        "used_day": used_day,
        "limit_hour": GENERATION_MAX_PER_HOUR,
        "limit_day": GENERATION_MAX_PER_DAY,
        "remaining_hour": max(0, GENERATION_MAX_PER_HOUR - used_hour),
        "remaining_day": max(0, GENERATION_MAX_PER_DAY - used_day),
    }
