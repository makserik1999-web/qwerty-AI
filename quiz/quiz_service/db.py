"""The Mongo handle and the indexes this service relies on.

The collections are this service's own - `quizzes`, `quiz_sessions` and
`quiz_players` - and nothing else writes to them. The one collection it reads
that it does not own is `account_events`, which the backend appends to when an
account is deleted (see events.py).
"""

from datetime import datetime, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient

from quiz_service.config import DATABASE_NAME, MONGO_URL


class Database:
    client: Any = None
    db: Any = None


db = Database()


def connect() -> None:
    db.client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db.db = db.client[DATABASE_NAME]


async def create_indexes() -> None:
    await db.db.quizzes.create_index([("owner_id", 1), ("updated_at", -1)])

    # A code belongs to a session only while it is open: `live_code` is set on
    # creation and removed when the session ends, and a sparse unique index
    # ignores documents without it. That is what lets a code be reused next
    # week without two open sessions ever answering to the same one.
    await db.db.quiz_sessions.create_index("live_code", unique=True, sparse=True)
    await db.db.quiz_sessions.create_index([("quiz_id", 1), ("created_at", -1)])
    await db.db.quiz_sessions.create_index([("owner_id", 1), ("status", 1)])

    await db.db.quiz_players.create_index("token_hash", unique=True)
    await db.db.quiz_players.create_index([("session_id", 1), ("joined_at", 1)])


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: Optional[datetime]) -> Optional[datetime]:
    """Mongo hands datetimes back without a zone; they were written as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def iso(value: Optional[datetime]) -> Optional[str]:
    value = aware(value)
    return value.isoformat() if value else None
