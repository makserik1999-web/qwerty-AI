"""Mongo client, index creation and the application lifespan."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import AGENT_SECRET, DATABASE_NAME, MONGO_URL
from app.ws.manager import _sweep_pending_requests_loop


class Database:
    client: AsyncIOMotorClient = None
    db = None


db = Database()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db.client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db.db = db.client[DATABASE_NAME]

    await db.db.users.create_index("username", unique=True)
    await db.db.users.create_index("email", unique=True, sparse=True)
    # TTL index: expired sessions are removed automatically.
    await db.db.sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.db.sessions.create_index("token_hash", unique=True)
    await db.db.chats.create_index([("user_id", 1), ("updated_at", -1)])
    await db.db.messages.create_index([("chat_id", 1), ("timestamp", 1)])
    # Answer cache. The TTL index skips documents with no `expires_at`, which
    # is exactly how curated entries stay forever while generated ones age out.
    await db.db.library_entries.create_index("cache_key", unique=True)
    await db.db.library_entries.create_index("expires_at", expireAfterSeconds=0)
    await db.db.library_entries.create_index([("tier", 1), ("last_hit_at", -1)])
    await db.db.question_stats.create_index([("hits", -1)])
    # Export queue. The worker claims by (status, created_at); the TTL
    # index drops finished jobs, and the worker removes their files first.
    await db.db.export_jobs.create_index([("status", 1), ("created_at", 1)])
    await db.db.export_jobs.create_index([("user_id", 1), ("created_at", -1)])
    await db.db.export_jobs.create_index("expires_at", expireAfterSeconds=0)
    # Generation quota counters. Tiny documents, one per started render;
    # the TTL window is wider than the longest quota period so a day-old
    # event cannot vanish while the daily count still needs it.
    await db.db.generation_events.create_index([("user_id", 1), ("created_at", -1)])
    await db.db.generation_events.create_index("request_id")
    await db.db.generation_events.create_index("expires_at", expireAfterSeconds=0)

    print(f"Connected to MongoDB at {MONGO_URL}")
    if not AGENT_SECRET:
        print("WARNING: AGENT_SECRET is not set - agent connections will be refused.")

    # Imported here, not at module scope: retention needs `db`, which this
    # module defines, so a top-level import would be circular.
    from app.services.retention import retention_loop

    sweep_task = asyncio.create_task(_sweep_pending_requests_loop())
    retention_task = asyncio.create_task(retention_loop())
    try:
        yield
    finally:
        sweep_task.cancel()
        retention_task.cancel()
        db.client.close()
        print("Disconnected from MongoDB")
