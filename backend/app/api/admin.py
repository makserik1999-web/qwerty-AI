"""The admin panel's API: users, usage statistics, the audit log.

Every route is on this router and the router requires a staff role (see
app/security/staff.py). Routes that only an admin may use say so on top of
that. Nothing here can grant or take away a staff role: that is the server
command's job alone.

Read-only for now. When write actions arrive (blocking, granting a plan),
each one writes to the audit log in the same request.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from bson import ObjectId
from fastapi import APIRouter, Depends

from app.config import _OBJECT_ID_RE, STAFF_ROLES, STATS_UTC_OFFSET_HOURS, USER_ROLE_DEFAULT
from app.db import db
from app.errors import HTTPExceptionJson
from app.repositories import audit
from app.repositories.library import cache_stats
from app.security.staff import require_admin, require_staff, staff_role_of
from app.services.quota import usage as quota_usage
from app.ws.manager import agent_manager

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_staff)])

_SEARCH_MAX_LEN = 100
_PAGE_MAX = 100
_STATS_MAX_DAYS = 90

_USAGE_FIELDS = (
    "explanations", "videos", "from_library", "failed",
    "assessments", "lesson_plans", "quiz_drafts", "quizzes",
)


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


def _empty_usage() -> Dict[str, int]:
    return dict.fromkeys(_USAGE_FIELDS, 0)


def _count_into(counts: Dict[str, int], entry: Dict[str, Any]) -> None:
    """Add one usage_log entry to a counts dict shaped like _empty_usage()."""
    kind = entry.get("kind")
    if kind == "explanation":
        if entry.get("cached"):
            counts["from_library"] += 1
        elif not entry.get("ok", True):
            counts["failed"] += 1
        else:
            counts["explanations"] += 1
            if entry.get("video"):
                counts["videos"] += 1
    elif kind == "assessment":
        counts["assessments"] += 1
    elif kind == "lesson_plan":
        counts["lesson_plans"] += 1
    elif kind == "quiz_draft":
        counts["quiz_drafts"] += 1


async def _usage_for(user_ids: List[str]) -> Dict[str, Dict[str, int]]:
    """Lifetime counts per user, from the usage log and the quiz store."""
    result = {uid: _empty_usage() for uid in user_ids}
    if not user_ids:
        return result
    projection = {"user_id": 1, "kind": 1, "ok": 1, "video": 1, "cached": 1}
    async for entry in db.db.usage_log.find({"user_id": {"$in": user_ids}}, projection):
        counts = result.get(entry.get("user_id"))
        if counts is not None:
            _count_into(counts, entry)
    async for quiz in db.db.quizzes.find({"owner_id": {"$in": user_ids}}, {"owner_id": 1}):
        counts = result.get(quiz.get("owner_id"))
        if counts is not None:
            counts["quizzes"] += 1
    return result


def _user_row(user: Dict[str, Any], usage: Dict[str, int]) -> Dict[str, Any]:
    return {
        "id": str(user["_id"]),
        "email": user.get("email") or "",
        "name": user.get("name") or user.get("username", ""),
        "username": user.get("username", ""),
        "role": user.get("role") or USER_ROLE_DEFAULT,
        "staff_role": staff_role_of(user),
        "created_at": _iso(user.get("created_at")),
        "email_verified": bool(user.get("email") and user.get("email_verified_at")),
        "phone": user.get("phone") or None,
        "phone_verified": bool(user.get("phone") and user.get("phone_verified_at")),
        "google": bool(user.get("google_sub")),
        "usage": usage,
    }


def _search_filter(q: str) -> Dict[str, Any]:
    q = (q or "").strip()[:_SEARCH_MAX_LEN]
    if not q:
        return {}
    pattern = re.compile(re.escape(q), re.IGNORECASE)
    conditions: List[Dict[str, Any]] = [
        {"email": pattern}, {"name": pattern}, {"username": pattern},
    ]
    if _OBJECT_ID_RE.fullmatch(q):
        conditions.append({"_id": ObjectId(q)})
    # A phone typed any way: "+7 707 123", "8707123", "707 12 34". Stored as
    # 77071234567, so a leading 8 is the same as a 7.
    digits = re.sub(r"\D", "", q)
    if len(digits) >= 4 and len(digits) >= len(q.replace(" ", "")) - 3:
        if len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        conditions.append({"phone": re.compile(re.escape(digits))})
    return {"$or": conditions}


def _page(skip: int, limit: int) -> tuple:
    return max(0, int(skip)), min(max(1, int(limit)), _PAGE_MAX)


@router.get("/users")
async def list_users(q: str = "", skip: int = 0, limit: int = 50):
    skip, limit = _page(skip, limit)
    query = _search_filter(q)
    total = await db.db.users.count_documents(query)
    users = [
        u async for u in db.db.users.find(query, {"password_hash": 0})
        .sort("created_at", -1).skip(skip).limit(limit)
    ]
    usage = await _usage_for([str(u["_id"]) for u in users])
    return {
        "total": total,
        "items": [_user_row(u, usage[str(u["_id"])]) for u in users],
    }


@router.get("/users/{user_id}")
async def user_detail(user_id: str):
    if not _OBJECT_ID_RE.fullmatch(user_id or ""):
        raise HTTPExceptionJson(404, "User not found")
    user = await db.db.users.find_one({"_id": ObjectId(user_id)}, {"password_hash": 0})
    if not user:
        raise HTTPExceptionJson(404, "User not found")

    usage = (await _usage_for([user_id]))[user_id]
    last_session = await db.db.sessions.find_one(
        {"user_id": user_id}, sort=[("created_at", -1)]
    )
    recent = [
        {
            "at": _iso(e.get("at")),
            "kind": e.get("kind"),
            "ok": e.get("ok", True),
            "video": e.get("video", False),
            "cached": e.get("cached", False),
        }
        async for e in db.db.usage_log.find({"user_id": user_id}).sort("at", -1).limit(20)
    ]
    return {
        **_user_row(user, usage),
        "last_sign_in": _iso(last_session.get("created_at")) if last_session else None,
        "quota": await quota_usage(user_id),
        "recent": recent,
    }


@router.get("/stats")
async def statistics(days: int = 14):
    days = min(max(1, int(days)), _STATS_MAX_DAYS)
    offset = timedelta(hours=STATS_UTC_OFFSET_HOURS)
    local_today = (datetime.now(timezone.utc) + offset).date()
    first_day = local_today - timedelta(days=days - 1)
    since = datetime(first_day.year, first_day.month, first_day.day, tzinfo=timezone.utc) - offset

    buckets: Dict[str, Dict[str, int]] = {}
    for i in range(days):
        day = (first_day + timedelta(days=i)).isoformat()
        buckets[day] = {"signups": 0, **_empty_usage()}

    def bucket_for(value: Any) -> Any:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return buckets.get((value + offset).date().isoformat())

    async for user in db.db.users.find({"created_at": {"$gte": since}}, {"created_at": 1}):
        bucket = bucket_for(user.get("created_at"))
        if bucket is not None:
            bucket["signups"] += 1
    async for entry in db.db.usage_log.find({"at": {"$gte": since}}):
        bucket = bucket_for(entry.get("at"))
        if bucket is not None:
            _count_into(bucket, entry)
    async for quiz in db.db.quizzes.find({"created_at": {"$gte": since}}, {"created_at": 1}):
        bucket = bucket_for(quiz.get("created_at"))
        if bucket is not None:
            bucket["quizzes"] += 1

    first_entry = await db.db.usage_log.find_one({}, sort=[("at", 1)])
    return {
        "totals": {
            "users": await db.db.users.count_documents({}),
            "teachers": await db.db.users.count_documents({"role": "teacher"}),
            "staff": await db.db.users.count_documents({"staff_role": {"$in": list(STAFF_ROLES)}}),
        },
        # Usage is counted from the day this log was introduced; earlier days
        # read as zero, and the panel says so instead of implying no one came.
        "usage_logged_since": _iso(first_entry.get("at")) if first_entry else None,
        "utc_offset_hours": STATS_UTC_OFFSET_HOURS,
        "agent": {
            "connected": agent_manager.agent_connection is not None,
            "queue": agent_manager.queue_depth(),
        },
        "days": [{"date": day, **counts} for day, counts in buckets.items()],
    }


@router.get("/audit", dependencies=[Depends(require_admin)])
async def audit_log(skip: int = 0, limit: int = 50):
    skip, limit = _page(skip, limit)
    return {"items": await audit.list_entries(skip, limit)}


@router.get("/cache/stats", dependencies=[Depends(require_admin)])
async def cache_statistics():
    """The questions people ask most - other people's questions, so admin only."""
    return await cache_stats()
