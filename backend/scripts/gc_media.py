#!/usr/bin/env python3
"""Run media retention once, by hand.

    docker compose exec backend python scripts/gc_media.py [--dry-run]

It lives inside the backend image because that is where the media volume
and the database connection are.

The backend runs the same sweep hourly on its own; this is for checking what
would happen, or for reclaiming space immediately after lowering the budget.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DATABASE_NAME, MONGO_URL  # noqa: E402
from app.db import db  # noqa: E402
from app.services.retention import collect_garbage  # noqa: E402


async def main() -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    db.client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db.db = db.client[DATABASE_NAME]
    try:
        result = await collect_garbage(dry_run="--dry-run" in sys.argv)
    finally:
        db.client.close()
    return 0 if result.get("status") != "still_over_budget" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
