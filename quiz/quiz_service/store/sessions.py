"""Sessions: one run of a quiz, with a code students join by.

A session carries its own copy of the questions and settings, taken when it
opens. Editing the quiz afterwards changes the next run and never the one in
progress - a question reworded while thirty phones are answering it would
make the results describe a test nobody took.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from quiz_service.codes import new_code
from quiz_service.db import db, now

OPEN = ("lobby", "running")


def _oid(value: str) -> Optional[ObjectId]:
    return ObjectId(value) if ObjectId.is_valid(value) else None


async def create(quiz: Dict[str, Any], owner_id: str, settings: Dict[str, Any],
                 class_label: str) -> Dict[str, Any]:
    stamp = now()
    for _ in range(12):
        code = new_code()
        # Checked before the insert as well as by the index: the test database
        # does not enforce a sparse unique index, and a collision in a class
        # would send students into somebody else's quiz.
        if await db.db.quiz_sessions.find_one({"live_code": code}, {"_id": 1}):
            continue
        doc = {
            "quiz_id": str(quiz["_id"]),
            "owner_id": owner_id,
            "code": code,
            "live_code": code,
            "status": "lobby",
            "title": quiz.get("title", ""),
            "subject": quiz.get("subject", "other"),
            "grade": quiz.get("grade", 0),
            "lang": quiz.get("lang", "kk"),
            "questions": quiz.get("questions") or [],
            "settings": settings,
            "class_label": class_label,
            "created_at": stamp,
            "starts_at": None,
            "ended_at": None,
        }
        try:
            result = await db.db.quiz_sessions.insert_one(doc)
        except DuplicateKeyError:
            continue
        doc["_id"] = result.inserted_id
        return doc
    raise RuntimeError("could not find a free join code")


async def get(session_id: str, owner_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    oid = _oid(session_id)
    if not oid:
        return None
    query: Dict[str, Any] = {"_id": oid}
    if owner_id is not None:
        query["owner_id"] = owner_id
    return await db.db.quiz_sessions.find_one(query)


async def get_open_by_code(code: str) -> Optional[Dict[str, Any]]:
    return await db.db.quiz_sessions.find_one({"live_code": code, "status": {"$in": list(OPEN)}})


async def start(session_id: str, starts_at: datetime) -> Optional[Dict[str, Any]]:
    oid = _oid(session_id)
    if not oid:
        return None
    return await db.db.quiz_sessions.find_one_and_update(
        {"_id": oid, "status": "lobby"},
        {"$set": {"status": "running", "starts_at": starts_at}},
        return_document=True,
    )


async def end(session_id: str) -> Optional[Dict[str, Any]]:
    oid = _oid(session_id)
    if not oid:
        return None
    return await db.db.quiz_sessions.find_one_and_update(
        {"_id": oid, "status": {"$in": list(OPEN)}},
        {"$set": {"status": "ended", "ended_at": now()}, "$unset": {"live_code": ""}},
        return_document=True,
    )


async def list_for_quiz(quiz_id: str, owner_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    cursor = (
        db.db.quiz_sessions.find(
            {"quiz_id": quiz_id, "owner_id": owner_id}, {"questions": 0}
        )
        .sort("created_at", -1)
        .limit(limit)
    )
    return [doc async for doc in cursor]


async def latest_for_owner(owner_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    cursor = (
        db.db.quiz_sessions.find({"owner_id": owner_id}, {"questions": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    return [doc async for doc in cursor]


async def count_open(owner_id: str) -> int:
    return await db.db.quiz_sessions.count_documents(
        {"owner_id": owner_id, "status": {"$in": list(OPEN)}}
    )


async def open_sessions() -> List[Dict[str, Any]]:
    cursor = db.db.quiz_sessions.find({"status": {"$in": list(OPEN)}})
    return [doc async for doc in cursor]


async def delete(session_id: str, owner_id: str) -> bool:
    oid = _oid(session_id)
    if not oid:
        return False
    result = await db.db.quiz_sessions.delete_one({"_id": oid, "owner_id": owner_id})
    return result.deleted_count > 0


async def ids_for_quiz(quiz_id: str) -> List[str]:
    cursor = db.db.quiz_sessions.find({"quiz_id": quiz_id}, {"_id": 1})
    return [str(doc["_id"]) async for doc in cursor]


async def ids_for_owner(owner_id: str) -> List[str]:
    cursor = db.db.quiz_sessions.find({"owner_id": owner_id}, {"_id": 1})
    return [str(doc["_id"]) async for doc in cursor]


async def delete_many(session_ids: List[str]) -> None:
    oids = [ObjectId(s) for s in session_ids if ObjectId.is_valid(s)]
    if oids:
        await db.db.quiz_sessions.delete_many({"_id": {"$in": oids}})
