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
    # The only way a paper is ever read: this teacher's, newest first.
    await db.db.assessments.create_index([("user_id", 1), ("created_at", -1)])
    # Lesson plans are read the same way, and were shipped without one.
    await db.db.lesson_plans.create_index([("user_id", 1), ("created_at", -1)])
    # The outbox other services read to learn an account is gone (the quiz
    # service, so far). Kept a month: long enough for a consumer that was
    # down to catch up, short enough that it does not grow forever.
    await db.db.account_events.create_index("created_at", expireAfterSeconds=30 * 24 * 3600)
    await db.db.messages.create_index([("chat_id", 1), ("timestamp", 1)])
    # A person's own library: listed newest-saved first, and checked for
    # a duplicate before every save.
    await db.db.saved_explanations.create_index([("user_id", 1), ("saved_at", -1)])
    await db.db.saved_explanations.create_index([("user_id", 1), ("message_id", 1)])
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
    # Admin statistics: per day across everyone, and per person. No TTL -
    # the point of this log is that it outlives the quota counters.
    await db.db.usage_log.create_index([("at", -1)])
    await db.db.usage_log.create_index([("user_id", 1), ("at", -1)])
    await db.db.admin_audit.create_index([("at", -1)])
    await db.db.users.create_index("staff_role", sparse=True)
    # One number per account, one Google identity per account.
    await db.db.users.create_index("phone", unique=True, sparse=True)
    await db.db.users.create_index("google_sub", unique=True, sparse=True)
    # Emailed one-time links, the Google round trip, SMS codes and the SMS
    # rationing log - all short-lived, all removed by their TTL index.
    await db.db.auth_tokens.create_index("token_hash", unique=True)
    await db.db.auth_tokens.create_index([("user_id", 1), ("kind", 1)])
    await db.db.auth_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.db.oauth_states.create_index("state_hash", unique=True)
    await db.db.oauth_states.create_index("expires_at", expireAfterSeconds=0)
    await db.db.phone_codes.create_index("user_id", unique=True)
    await db.db.phone_codes.create_index("expires_at", expireAfterSeconds=0)
    await db.db.sms_log.create_index([("user_id", 1), ("at", -1)])
    await db.db.sms_log.create_index([("phone", 1), ("at", -1)])
    await db.db.sms_log.create_index([("ip", 1), ("at", -1)])
    await db.db.sms_log.create_index([("at", -1)])
    await db.db.sms_log.create_index("expires_at", expireAfterSeconds=0)
    # Plans. One trial per phone number (an HMAC of it) and per account; the
    # claims are never removed with the account, which is the point.
    await db.db.trial_claims.create_index("phone_hash", unique=True)
    await db.db.trial_claims.create_index("user_id")
    await db.db.plan_reservations.create_index("ref", unique=True)
    await db.db.plan_reservations.create_index("expires_at", expireAfterSeconds=0)
    await db.db.users.create_index("subscription.expires_at", sparse=True)
    # Payments: looked up by the code a teacher reads out, listed per account
    # and per status for the admin panel. Kept for good - it is the money log.
    await db.db.payments.create_index("code", unique=True)
    await db.db.payments.create_index([("user_id", 1), ("created_at", -1)])
    await db.db.payments.create_index([("status", 1), ("created_at", -1)])
    # Topic videos: looked up by topic and language on every general
    # question, listed by status for moderation, by subject for the showcase.
    await db.db.video_cache.create_index([("topic_id", 1), ("lang", 1), ("status", 1)])
    await db.db.video_cache.create_index([("status", 1), ("created_at", -1)])
    await db.db.video_cache.create_index([("status", 1), ("subject", 1), ("grade", 1)])
    await db.db.video_ratings.create_index([("video_id", 1), ("user_id", 1)], unique=True)
    # Referrals: a code per teacher, who invited whom, one reward per invitee.
    await db.db.users.create_index("referral_code", unique=True, sparse=True)
    await db.db.users.create_index("referred_by", sparse=True)
    await db.db.referral_rewards.create_index("invitee_id", unique=True)
    await db.db.referral_rewards.create_index([("inviter_id", 1), ("at", -1)])

    print(f"Connected to MongoDB at {MONGO_URL}")
    if not AGENT_SECRET:
        print("WARNING: AGENT_SECRET is not set - agent connections will be refused.")

    # Imported here, not at module scope: retention needs `db`, which this
    # module defines, so a top-level import would be circular.
    from app.services.plans import reminder_loop, seed_plans
    from app.services.retention import retention_loop

    await seed_plans()

    sweep_task = asyncio.create_task(_sweep_pending_requests_loop())
    retention_task = asyncio.create_task(retention_loop())
    reminder_task = asyncio.create_task(reminder_loop())
    try:
        yield
    finally:
        sweep_task.cancel()
        retention_task.cancel()
        reminder_task.cancel()
        db.client.close()
        print("Disconnected from MongoDB")
