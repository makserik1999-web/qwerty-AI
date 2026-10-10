"""Lesson plans, stored per teacher.

The same shape as assessments and for the same reason: a plan is written once
and then edited. A teacher rewrites a stage, changes the minutes, adds the
objective code they looked up - and then submits it. So the plan lives in the
document rather than being regenerated on each read: what was submitted and
what is on screen have to be the same plan.
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
        "lang": doc.get("lang", ""),
        "duration": doc.get("duration", 0),
        "plan": doc.get("plan", {}),
        # How many minutes the stages actually add up to, as generated. Kept
        # so the interface can say "40 of 40" without re-adding it, and so an
        # edit that breaks the total is visible against what it started as.
        "minutesPlanned": doc.get("minutes_planned", 0),
        "createdAt": _iso(doc.get("created_at")),
        "updatedAt": _iso(doc.get("updated_at")),
    }


async def create_lesson_plan(user_id: str, spec: Dict[str, Any],
                             plan: Dict[str, Any],
                             minutes_planned: int) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": user_id,
        "subject": spec.get("subject", ""),
        "grade": int(spec.get("grade") or 0),
        "topic": spec.get("topic", ""),
        "lang": spec.get("lang", ""),
        "duration": int(spec.get("duration") or 0),
        # Each stage carries its own id so the interface can address one to
        # edit or delete it without depending on its position - the same rule
        # the assessment questions follow, for the same reason.
        "plan": plan,
        "minutes_planned": int(minutes_planned or 0),
        "created_at": now,
        "updated_at": now,
    }
    result = await db.db.lesson_plans.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _public(doc)


async def list_lesson_plans(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    cursor = (
        db.db.lesson_plans.find({"user_id": user_id})
        .sort("created_at", -1)
        .limit(limit)
    )
    return [_public(doc) async for doc in cursor]


async def get_lesson_plan(plan_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Owned by this teacher, or nothing. A guessed id gets you nobody's plan."""
    if not ObjectId.is_valid(plan_id):
        return None
    doc = await db.db.lesson_plans.find_one(
        {"_id": ObjectId(plan_id), "user_id": user_id}
    )
    return _public(doc) if doc else None


async def replace_plan(plan_id: str, user_id: str,
                       plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not ObjectId.is_valid(plan_id):
        return None
    result = await db.db.lesson_plans.find_one_and_update(
        {"_id": ObjectId(plan_id), "user_id": user_id},
        {"$set": {"plan": plan, "updated_at": datetime.now(timezone.utc)}},
        return_document=True,
    )
    return _public(result) if result else None


async def delete_lesson_plan(plan_id: str, user_id: str) -> bool:
    if not ObjectId.is_valid(plan_id):
        return False
    result = await db.db.lesson_plans.delete_one(
        {"_id": ObjectId(plan_id), "user_id": user_id}
    )
    return result.deleted_count > 0


async def count_for(user_id: str) -> int:
    return await db.db.lesson_plans.count_documents({"user_id": user_id})
