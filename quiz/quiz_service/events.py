"""Accounts deleted on the backend, removed here too.

The backend appends to `account_events` when somebody deletes their account -
an outbox, so the deletion is recorded by the same request that performs it
and nothing has to be reachable at that moment for it to stick. This loop
reads it and removes the quizzes, runs and answers that account owned.

Each event is marked as handled by this service rather than deleted: another
consumer may want the same event, and "who has dealt with this" belongs on
the event, not in each consumer's private bookkeeping.
"""

import asyncio

from quiz_service import lifecycle
from quiz_service.db import db
from quiz_service.store import players as players_store
from quiz_service.store import quizzes as quizzes_store
from quiz_service.store import sessions as sessions_store

CONSUMER = "quiz"
POLL_INTERVAL_SEC = 30


async def purge_owner(owner_id: str) -> None:
    session_ids = await sessions_store.ids_for_owner(owner_id)
    for session_id in session_ids:
        await lifecycle.end_session(session_id)
    await players_store.delete_for_sessions(session_ids)
    await sessions_store.delete_many(session_ids)
    await quizzes_store.delete_all_for(owner_id)


async def consume_once() -> int:
    handled = 0
    cursor = db.db.account_events.find(
        {"type": "account_deleted", "handled_by": {"$ne": CONSUMER}}
    ).sort("created_at", 1).limit(100)
    async for event in cursor:
        user_id = str(event.get("user_id") or "")
        if user_id:
            await purge_owner(user_id)
        await db.db.account_events.update_one(
            {"_id": event["_id"]}, {"$addToSet": {"handled_by": CONSUMER}}
        )
        handled += 1
    return handled


async def consume_loop() -> None:
    while True:
        try:
            await consume_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[account-events] {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(POLL_INTERVAL_SEC)
