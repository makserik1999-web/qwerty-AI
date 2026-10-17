"""The students in a session, and their answers.

A student is known by a random token their phone keeps, stored here only as a
hash - the same arrangement as the backend's session cookie, so a copy of this
collection does not let anybody answer as anybody.
"""

import hashlib
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from quiz_service.db import db, now


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


async def create(session_id: str, name: str, order: List[str],
                 option_orders: Dict[str, List[str]],
                 started_at: Optional[datetime]) -> Dict[str, Any]:
    token = new_token()
    doc = {
        "session_id": session_id,
        "name": name,
        # Compared without case, so "Айгерім" and "айгерім" are one name.
        "name_key": name.casefold(),
        "token_hash": hash_token(token),
        "joined_at": now(),
        "started_at": started_at,
        "finished_at": None,
        "kicked": False,
        "order": order,
        "option_orders": option_orders,
        "answers": {},
        "answered": 0,
        "correct": 0,
        "score": 0,
        "streak": 0,
        "best_streak": 0,
        "last_answer_at": None,
    }
    result = await db.db.quiz_players.insert_one(doc)
    doc["_id"] = result.inserted_id
    doc["token"] = token
    return doc


async def by_token(token: str) -> Optional[Dict[str, Any]]:
    if not token or len(token) > 200:
        return None
    return await db.db.quiz_players.find_one({"token_hash": hash_token(token)})


async def get(player_id: str) -> Optional[Dict[str, Any]]:
    if not ObjectId.is_valid(player_id):
        return None
    return await db.db.quiz_players.find_one({"_id": ObjectId(player_id)})


async def in_session(session_id: str, include_kicked: bool = False) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"session_id": session_id}
    if not include_kicked:
        query["kicked"] = False
    cursor = db.db.quiz_players.find(query).sort("joined_at", 1)
    return [doc async for doc in cursor]


async def count(session_id: str) -> int:
    return await db.db.quiz_players.count_documents({"session_id": session_id, "kicked": False})


async def name_taken(session_id: str, name: str) -> bool:
    return bool(await db.db.quiz_players.find_one(
        {"session_id": session_id, "kicked": False, "name_key": name.casefold()},
        {"_id": 1},
    ))


async def start_waiting(session_id: str, starts_at: datetime) -> None:
    """Everyone already in the lobby starts on the same beat."""
    await db.db.quiz_players.update_many(
        {"session_id": session_id, "started_at": None, "kicked": False},
        {"$set": {"started_at": starts_at}},
    )


async def record_answer(player: Dict[str, Any], question_id: str, entry: Dict[str, Any],
                        points: int, streak: int, finished: bool) -> bool:
    """Write one answer, once.

    The filter carries "not answered yet" and "not finished", so a double tap,
    a retry after a timeout, or two tabs sending the same answer all land as
    exactly one answer - the first.
    """
    stamp = entry["at"]
    update: Dict[str, Any] = {
        "$set": {
            f"answers.{question_id}": entry,
            "streak": streak,
            "last_answer_at": stamp,
        },
        "$inc": {"answered": 1, "correct": 1 if entry["correct"] else 0, "score": points},
        "$max": {"best_streak": streak},
    }
    if finished:
        update["$set"]["finished_at"] = stamp
    result = await db.db.quiz_players.update_one(
        {
            "_id": player["_id"],
            f"answers.{question_id}": {"$exists": False},
            "finished_at": None,
            "kicked": False,
        },
        update,
    )
    return result.modified_count == 1


async def finish(player_id: ObjectId, at: datetime) -> bool:
    result = await db.db.quiz_players.update_one(
        {"_id": player_id, "finished_at": None},
        {"$set": {"finished_at": at, "streak": 0}},
    )
    return result.modified_count == 1


async def finish_all(session_id: str, at: datetime) -> None:
    await db.db.quiz_players.update_many(
        {"session_id": session_id, "finished_at": None},
        {"$set": {"finished_at": at}},
    )


async def kick(session_id: str, player_id: str) -> Optional[Dict[str, Any]]:
    if not ObjectId.is_valid(player_id):
        return None
    return await db.db.quiz_players.find_one_and_update(
        {"_id": ObjectId(player_id), "session_id": session_id, "kicked": False},
        {"$set": {"kicked": True, "finished_at": now()}},
        return_document=True,
    )


async def delete_for_sessions(session_ids: List[str]) -> None:
    if session_ids:
        await db.db.quiz_players.delete_many({"session_id": {"$in": session_ids}})
