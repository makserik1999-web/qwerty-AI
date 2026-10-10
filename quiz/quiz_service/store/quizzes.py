"""A teacher's quizzes."""

from typing import Any, Dict, List, Optional

from bson import ObjectId

from quiz_service.db import db, iso, now
from quiz_service.questions import problems


def _oid(value: str) -> Optional[ObjectId]:
    return ObjectId(value) if ObjectId.is_valid(value) else None


def public(doc: Dict[str, Any]) -> Dict[str, Any]:
    questions = doc.get("questions") or []
    found = {q["id"]: problems(q) for q in questions}
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title", ""),
        "subject": doc.get("subject", "other"),
        "grade": doc.get("grade", 0),
        "lang": doc.get("lang", "kk"),
        "topic": doc.get("topic", ""),
        "questions": questions,
        "settings": doc.get("settings") or {},
        # Only the questions that have something wrong, so an empty object
        # means "ready to play".
        "problems": {qid: codes for qid, codes in found.items() if codes},
        "questionCount": len(questions),
        "createdAt": iso(doc.get("created_at")),
        "updatedAt": iso(doc.get("updated_at")),
    }


def summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    questions = doc.get("questions") or []
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title", ""),
        "subject": doc.get("subject", "other"),
        "grade": doc.get("grade", 0),
        "lang": doc.get("lang", "kk"),
        "questionCount": len(questions),
        "kinds": {
            "choice": sum(1 for q in questions if q.get("type") == "choice"),
            "short": sum(1 for q in questions if q.get("type") == "short"),
        },
        "ready": bool(questions) and not any(problems(q) for q in questions),
        "createdAt": iso(doc.get("created_at")),
        "updatedAt": iso(doc.get("updated_at")),
    }


async def create(owner_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    stamp = now()
    doc = {**fields, "owner_id": owner_id, "created_at": stamp, "updated_at": stamp}
    result = await db.db.quizzes.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def list_for(owner_id: str, limit: int = 300) -> List[Dict[str, Any]]:
    cursor = db.db.quizzes.find({"owner_id": owner_id}).sort("updated_at", -1).limit(limit)
    return [doc async for doc in cursor]


async def get(quiz_id: str, owner_id: str) -> Optional[Dict[str, Any]]:
    oid = _oid(quiz_id)
    if not oid:
        return None
    return await db.db.quizzes.find_one({"_id": oid, "owner_id": owner_id})


async def update(quiz_id: str, owner_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    oid = _oid(quiz_id)
    if not oid:
        return None
    return await db.db.quizzes.find_one_and_update(
        {"_id": oid, "owner_id": owner_id},
        {"$set": {**fields, "updated_at": now()}},
        return_document=True,
    )


async def delete(quiz_id: str, owner_id: str) -> bool:
    oid = _oid(quiz_id)
    if not oid:
        return False
    result = await db.db.quizzes.delete_one({"_id": oid, "owner_id": owner_id})
    return result.deleted_count > 0


async def count_for(owner_id: str) -> int:
    return await db.db.quizzes.count_documents({"owner_id": owner_id})


async def delete_all_for(owner_id: str) -> int:
    result = await db.db.quizzes.delete_many({"owner_id": owner_id})
    return result.deleted_count
