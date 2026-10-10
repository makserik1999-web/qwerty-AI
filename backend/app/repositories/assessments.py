"""Assessment papers, stored per teacher.

A paper is written once and then edited: a teacher rewords a question, swaps
one out, and prints the result. So the questions live in the document rather
than being regenerated on each read - what was printed and what is on screen
have to be the same paper.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.db import db

MAX_PER_TEACHER = 200


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else None


def _public(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "subject": doc.get("subject", ""),
        "grade": doc.get("grade", 0),
        "topic": doc.get("topic", ""),
        "type": doc.get("type", ""),
        "difficulty": doc.get("difficulty", ""),
        "lang": doc.get("lang", ""),
        "questions": doc.get("questions", []),
        "createdAt": _iso(doc.get("created_at")),
    }


async def create_assessment(user_id: str, spec: Dict[str, Any],
                            questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    doc = {
        "user_id": user_id,
        "subject": spec.get("subject", ""),
        "grade": int(spec.get("grade") or 0),
        "topic": spec.get("topic", ""),
        "type": spec.get("type", ""),
        "difficulty": spec.get("difficulty", ""),
        "lang": spec.get("lang", ""),
        # Each question carries its own id so the interface can address one to
        # edit or replace it without depending on its position - a teacher who
        # deletes the second question must not thereby rename the third.
        "questions": questions,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.db.assessments.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _public(doc)


async def list_assessments(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    cursor = (
        db.db.assessments.find({"user_id": user_id})
        .sort("created_at", -1)
        .limit(limit)
    )
    return [_public(doc) async for doc in cursor]


async def get_assessment(assessment_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Owned by this teacher, or nothing. A guessed id gets you nobody's paper."""
    if not ObjectId.is_valid(assessment_id):
        return None
    doc = await db.db.assessments.find_one(
        {"_id": ObjectId(assessment_id), "user_id": user_id}
    )
    return _public(doc) if doc else None


async def replace_questions(assessment_id: str, user_id: str,
                            questions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not ObjectId.is_valid(assessment_id):
        return None
    result = await db.db.assessments.find_one_and_update(
        {"_id": ObjectId(assessment_id), "user_id": user_id},
        {"$set": {"questions": questions, "updated_at": datetime.now(timezone.utc)}},
        return_document=True,
    )
    return _public(result) if result else None


async def delete_assessment(assessment_id: str, user_id: str) -> bool:
    if not ObjectId.is_valid(assessment_id):
        return False
    result = await db.db.assessments.delete_one(
        {"_id": ObjectId(assessment_id), "user_id": user_id}
    )
    return result.deleted_count > 0


async def count_for(user_id: str) -> int:
    return await db.db.assessments.count_documents({"user_id": user_id})
