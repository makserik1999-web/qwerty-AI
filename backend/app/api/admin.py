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
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import (
    _OBJECT_ID_RE,
    EFFORT_LEVELS,
    STAFF_ROLES,
    STATS_UTC_OFFSET_HOURS,
    USER_ROLE_DEFAULT,
    USER_ROLES,
)
from app.db import db
from app.errors import HTTPExceptionJson
from app.repositories import audit
from app.repositories.library import cache_stats
from app.security.staff import require_admin, require_staff, staff_role_of
from app.services import plans
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


def _plan_glance(user: Dict[str, Any]) -> str:
    sub = user.get("subscription") or {}
    expires = sub.get("expires_at")
    if isinstance(expires, datetime) and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if sub.get("status") == "paused":
        return "paused"
    if expires and expires > datetime.now(timezone.utc):
        return sub.get("plan_id") or "ustaz"
    return "trial" if user.get("trial") else "free"


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
        # A glance, without starting anyone's trial: the full picture is in
        # the detail, from plans.summary.
        "plan": _plan_glance(user),
        "blocked": bool(user.get("blocked_at")),
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
        "plan_detail": await plans.summary(user, activate=False),
        "blocked_reason": user.get("blocked_reason") or "",
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


# --------------------------------------------------------------- actions --
#
# Everything below changes something, and every one of them writes to the
# audit log in the same request, with the reason the staff member gave. A
# reason is required: in a month nobody remembers why a teacher has half a
# year of Ұстаз for free unless it was written down when it was given.


class _Reasoned(BaseModel):
    reason: str


class RoleRequest(_Reasoned):
    role: str


class GrantRequest(_Reasoned):
    plan_id: str
    months: Optional[int] = None
    # YYYY-MM-DD, the last day included (Kazakhstan time).
    until: Optional[str] = None


class CountRequest(_Reasoned):
    count: int


class PlanEdit(_Reasoned):
    title: Optional[str] = None
    price: Optional[int] = None
    limits: Optional[Dict[str, Optional[int]]] = None
    carryover_cap: Optional[int] = None
    # Per resource; a null value takes that resource's carry-over or ceiling away.
    carryover_caps: Optional[Dict[str, Optional[int]]] = None
    fair_use: Optional[Dict[str, Optional[int]]] = None
    max_effort: Optional[str] = None
    watermark: Optional[bool] = None
    docx_signature: Optional[bool] = None
    videos: Optional[int] = None


def _per_resource(current: Any, edits: Dict[str, Optional[int]], allowed, label: str) -> Dict[str, int]:
    """`current` with `edits` applied: a number sets, a null removes."""
    merged = dict(current or {})
    for key, value in edits.items():
        if key not in allowed:
            raise HTTPExceptionJson(400, f"Unknown {label} {key!r}")
        if value is None:
            merged.pop(key, None)
        elif not 0 <= value <= 10_000:
            raise HTTPExceptionJson(400, f"{label} {key} out of range")
        else:
            merged[key] = value
    return merged


def _reason(body: _Reasoned) -> str:
    reason = " ".join((body.reason or "").split())
    if not reason:
        raise HTTPExceptionJson(400, "Say why - it goes into the audit log", code="reason_required")
    return reason[:500]


async def _target(user_id: str) -> Dict[str, Any]:
    if not _OBJECT_ID_RE.fullmatch(user_id or ""):
        raise HTTPExceptionJson(404, "User not found")
    user = await db.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPExceptionJson(404, "User not found")
    return user


def _until(value: str) -> datetime:
    """The end of the given day in Kazakhstan, as the moment it stops working."""
    try:
        day = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPExceptionJson(400, "until must be YYYY-MM-DD") from None
    return plans._from_local(day.year, day.month, day.day) + timedelta(days=1)


@router.post("/users/{user_id}/subscription", dependencies=[Depends(require_admin)])
async def grant_subscription(user_id: str, body: GrantRequest, actor=Depends(require_staff)):
    """Give or extend Ұстаз by hand: a school pilot, a compensation, a promotion."""
    reason = _reason(body)
    target = await _target(user_id)
    plan = await plans.get_plan(body.plan_id)
    if not plan or plan.get("kind") != "subscription":
        raise HTTPExceptionJson(400, "Not a subscription plan")
    if body.months is not None and not 1 <= body.months <= 12:
        raise HTTPExceptionJson(400, "months must be 1-12")
    until = _until(body.until) if body.until else None
    if until and until <= datetime.now(timezone.utc):
        raise HTTPExceptionJson(400, "until is in the past")
    before = (target.get("subscription") or {}).get("expires_at")
    updated = await plans.grant(target, body.plan_id, months=body.months, until=until)
    after = updated["subscription"]["expires_at"]
    await audit.record(
        actor=audit.staff_actor(actor), action="plan.grant", target=audit.user_target(target),
        details={"plan_id": body.plan_id, "months": body.months, "until": body.until,
                 "expires_before": _iso(before), "expires_after": _iso(after)},
        reason=reason,
    )
    return {"plan": await plans.summary(updated, activate=False)}


@router.post("/users/{user_id}/subscription/end", dependencies=[Depends(require_admin)])
async def end_subscription(user_id: str, body: _Reasoned, actor=Depends(require_staff)):
    reason = _reason(body)
    target = await _target(user_id)
    await plans.end_subscription(target)
    await audit.record(actor=audit.staff_actor(actor), action="plan.end",
                       target=audit.user_target(target),
                       details={"plan_id": (target.get("subscription") or {}).get("plan_id")},
                       reason=reason)
    return {"plan": await plans.summary(await _target(user_id), activate=False)}


@router.post("/users/{user_id}/extra-videos", dependencies=[Depends(require_admin)])
async def extra_videos(user_id: str, body: CountRequest, actor=Depends(require_staff)):
    reason = _reason(body)
    if not 1 <= body.count <= 100:
        raise HTTPExceptionJson(400, "count must be 1-100")
    target = await _target(user_id)
    await plans.add_extra_videos(target, body.count)
    await audit.record(actor=audit.staff_actor(actor), action="plan.extra_videos",
                       target=audit.user_target(target), details={"count": body.count},
                       reason=reason)
    return {"plan": await plans.summary(await _target(user_id), activate=False)}


@router.post("/users/{user_id}/trial/reset")
async def reset_trial(user_id: str, body: _Reasoned, actor=Depends(require_staff)):
    """A fresh trial, on request. Support may do this; it frees the number too."""
    reason = _reason(body)
    target = await _target(user_id)
    used = (target.get("trial") or {}).get("used") or {}
    await plans.reset_trial(target)
    await audit.record(actor=audit.staff_actor(actor), action="trial.reset",
                       target=audit.user_target(target), details={"used_before": used},
                       reason=reason)
    return {"ok": True}


@router.post("/users/{user_id}/block")
async def block(user_id: str, body: _Reasoned, actor=Depends(require_staff)):
    """Sign the account out everywhere and keep it out - e.g. for farming trials."""
    reason = _reason(body)
    target = await _target(user_id)
    if staff_role_of(target):
        raise HTTPExceptionJson(400, "Take the staff role away on the server first",
                                code="target_is_staff")
    await db.db.users.update_one({"_id": target["_id"]},
                                 {"$set": {"blocked_at": datetime.now(timezone.utc),
                                           "blocked_reason": reason}})
    await db.db.sessions.delete_many({"user_id": str(target["_id"])})
    await audit.record(actor=audit.staff_actor(actor), action="user.block",
                       target=audit.user_target(target), reason=reason)
    return {"ok": True}


@router.post("/users/{user_id}/unblock")
async def unblock(user_id: str, body: _Reasoned, actor=Depends(require_staff)):
    reason = _reason(body)
    target = await _target(user_id)
    await db.db.users.update_one({"_id": target["_id"]},
                                 {"$unset": {"blocked_at": "", "blocked_reason": ""}})
    await audit.record(actor=audit.staff_actor(actor), action="user.unblock",
                       target=audit.user_target(target), reason=reason)
    return {"ok": True}


@router.post("/users/{user_id}/role")
async def change_role(user_id: str, body: RoleRequest, actor=Depends(require_staff)):
    """Teacher or student, for somebody who picked the wrong one at sign-up.

    Nothing in the interface lets a person change it themselves - a student who
    could make himself a teacher would be generating on a teacher's terms - so
    a person who asks support is the way, and it is in the audit log.
    """
    reason = _reason(body)
    if body.role not in USER_ROLES:
        raise HTTPExceptionJson(400, "Unknown role")
    target = await _target(user_id)
    before = target.get("role") or USER_ROLE_DEFAULT
    if before != body.role:
        await db.db.users.update_one({"_id": target["_id"]}, {"$set": {"role": body.role}})
        await audit.record(actor=audit.staff_actor(actor), action="user.role",
                           target=audit.user_target(target),
                           details={"from": before, "to": body.role}, reason=reason)
    return {"ok": True, "role": body.role}


@router.get("/plans", dependencies=[Depends(require_admin)])
async def list_plans():
    return {"items": [dict(p, id=p["_id"]) for p in await plans.list_plans() if p]}


@router.put("/plans/{plan_id}", dependencies=[Depends(require_admin)])
async def edit_plan(plan_id: str, body: PlanEdit, actor=Depends(require_staff)):
    """Change limits and prices without a deploy. New numbers apply from the
    next request; what was already counted stays counted."""
    reason = _reason(body)
    plan = await plans.get_plan(plan_id)
    if not plan:
        raise HTTPExceptionJson(404, "No such plan")
    changes: Dict[str, Any] = {}
    if body.title is not None:
        title = " ".join(body.title.split())[:60]
        if not title:
            raise HTTPExceptionJson(400, "Title cannot be empty")
        changes["title"] = title
    if body.price is not None:
        if not 0 <= body.price <= 1_000_000:
            raise HTTPExceptionJson(400, "Price out of range")
        changes["price"] = body.price
    if body.limits is not None:
        limits = dict(plan.get("limits") or {})
        for key, value in body.limits.items():
            if key not in plans.RESOURCES:
                raise HTTPExceptionJson(400, f"Unknown limit {key!r}")
            if value is not None and not 0 <= value <= 10_000:
                raise HTTPExceptionJson(400, f"{key} out of range")
            limits[key] = value
        changes["limits"] = limits
    if body.carryover_cap is not None:
        if not 0 <= body.carryover_cap <= 1000:
            raise HTTPExceptionJson(400, "carryover_cap out of range")
        changes["carryover_cap"] = body.carryover_cap
    if body.carryover_caps is not None:
        allowed = [r for r in plans.CARRY_RESOURCES if r != "videos"]
        changes["carryover_caps"] = _per_resource(plan.get("carryover_caps"), body.carryover_caps,
                                                  allowed, "carry-over")
    if body.fair_use is not None:
        changes["fair_use"] = _per_resource(plan.get("fair_use"), body.fair_use, plans.RESOURCES, "fair use")
    if body.max_effort is not None:
        if body.max_effort not in EFFORT_LEVELS:
            raise HTTPExceptionJson(400, "max_effort must be low, medium or high")
        changes["max_effort"] = body.max_effort
    if body.watermark is not None:
        changes["watermark"] = body.watermark
    if body.docx_signature is not None:
        changes["docx_signature"] = body.docx_signature
    if body.videos is not None:
        if plan.get("kind") != "addon" or not 1 <= body.videos <= 1000:
            raise HTTPExceptionJson(400, "videos applies to the add-on, 1-1000")
        changes["videos"] = body.videos
    if not changes:
        raise HTTPExceptionJson(400, "Nothing to change")

    before = {k: plan.get(k) for k in changes}
    stored = {k: v for k, v in {**plan, **changes}.items() if k != "_id"}
    await db.db.plans.update_one({"_id": plan_id}, {"$set": stored}, upsert=True)
    await audit.record(actor=audit.staff_actor(actor), action="plan.edit",
                       target={"plan_id": plan_id}, details={"before": before, "after": changes},
                       reason=reason)
    return dict(await plans.get_plan(plan_id), id=plan_id)
