"""Plans: what an account may make, and counting what it made.

An account is on one of three footings:

    free    nothing generated - watching the library, joining quizzes. Every
            student, and a teacher before their phone is confirmed or after
            the trial is spent.
    trial   Сынақ. Once per phone number, ever; it does not expire. It waits
            for the moment a teacher actually needs a paper.
    ustaz   Ұстаз, the subscription: by the month or for the school year
            (September to May). Counted in monthly periods from the day it
            started; unused videos and БЖБ/ТЖБ carry into the next period.

The numbers - limits, prices, the carry-over caps, the fair-use ceilings -
live in the `plans` collection, not here, so they can be changed from the
admin panel without a deploy. DEFAULT_PLANS is only what an empty database
starts with.

A limit of None is unlimited, and the interface says so. A plan may still
keep a fair-use ceiling on it (`fair_use`): far above what one teacher
makes, there so that one paid account shared by a staff room is not
unlimited for all of them. The plan page names it, so it is not a secret.

Counting is a reservation: the unit is taken before the work starts, with an
atomic conditional increment so two requests cannot both take the last one,
and given back if the work fails. A video that was never made is not charged
for - the same rule the hourly quota already follows.
"""

import calendar
import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app import config
from app.config import EFFORT_LEVELS, USER_ROLE_DEFAULT
from app.db import db

RESOURCES = ("videos", "assessments", "quiz_drafts", "lesson_plans")
# What a finished month may pass on. Videos carried first and keep their own
# field for it (`carryover_cap`, `period.carryover`); the rest go by name in
# `carryover_caps` and `period.carried`. БЖБ/ТЖБ carry because they come in
# a rush at the end of a term, not evenly through it.
CARRY_RESOURCES = ("videos", "assessments")

TRIAL = "trial"
USTAZ_MONTH = "ustaz_month"
USTAZ_YEAR = "ustaz_year"
VIDEOS_10 = "videos_10"

FREE, ON_TRIAL, ON_USTAZ = "free", "trial", "ustaz"

WATERMARK_TEXT = "Akron · сынақ"

DEFAULT_PLANS: List[Dict[str, Any]] = [
    {
        "_id": TRIAL, "kind": "trial", "title": "Сынақ", "price": 0,
        "limits": {"videos": 2, "assessments": 2, "quiz_drafts": 3, "lesson_plans": 2},
        "max_effort": "medium", "watermark": True, "docx_signature": True,
    },
    {
        "_id": USTAZ_MONTH, "kind": "subscription", "title": "Ұстаз · ай", "price": 4990,
        "period": "month",
        "limits": {"videos": 20, "assessments": 20, "quiz_drafts": None, "lesson_plans": 40},
        "carryover_cap": 20, "carryover_caps": {"assessments": 20}, "fair_use": {"quiz_drafts": 100},
        "max_effort": "high", "watermark": False, "docx_signature": False,
    },
    {
        "_id": USTAZ_YEAR, "kind": "subscription", "title": "Ұстаз · оқу жылы", "price": 29900,
        "period": "school_year",
        "limits": {"videos": 20, "assessments": 20, "quiz_drafts": None, "lesson_plans": 40},
        "carryover_cap": 20, "carryover_caps": {"assessments": 20}, "fair_use": {"quiz_drafts": 100},
        "max_effort": "high", "watermark": False, "docx_signature": False,
    },
    {"_id": VIDEOS_10, "kind": "addon", "title": "+10 видео", "price": 990, "videos": 10},
]

RESERVATION_KEEP = timedelta(days=2)


class PlanRefusal(Exception):
    """The account may not make this. `code` is what the interface translates."""

    def __init__(self, code: str, resource: str):
        super().__init__(code)
        self.code = code
        self.resource = resource


# ------------------------------------------------------------------ time --


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _aware(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def add_months(moment: datetime, months: int) -> datetime:
    """The same day `months` later, or the month's last day if it is shorter."""
    index = moment.month - 1 + months
    year, month = moment.year + index // 12, index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def _local(moment: datetime) -> datetime:
    return moment + timedelta(hours=config.STATS_UTC_OFFSET_HOURS)


def _from_local(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc) - timedelta(hours=config.STATS_UTC_OFFSET_HOURS)


def school_year_end(moment: datetime) -> datetime:
    """1 June (Kazakhstan time) that ends the school year `moment` is in.

    June to August belong to the year that starts in September, so a school
    year plan bought in the summer runs to the following June. So does one
    bought from 15 May: the year it would otherwise buy is a fortnight long,
    and that is not what anybody paying for a year means.
    """
    local = _local(moment)
    late_may = local.month == 5 and local.day >= 15
    year = local.year if local.month < 6 and not late_may else local.year + 1
    return _from_local(year, 6, 1)


def next_september(moment: datetime) -> datetime:
    local = _local(moment)
    year = local.year if local.month < 9 else local.year + 1
    return _from_local(year, 9, 1)


def pause_allowed_now(moment: datetime) -> bool:
    """Summer: from 15 May to the end of August."""
    local = _local(moment)
    return local.month in (6, 7, 8) or (local.month == 5 and local.day >= 15)


# ----------------------------------------------------------------- plans --


async def seed_plans() -> None:
    """Write the defaults that are missing. Never overwrites an edited plan.

    A plan stored before a setting existed gets that setting's default - the
    БЖБ carry-over and the quiz fair-use ceiling arrived on a running
    database. Only settings it has no value for at all: one an admin has
    edited, even to nothing, stays as they left it.
    """
    for plan in DEFAULT_PLANS:
        stored = await db.db.plans.find_one({"_id": plan["_id"]})
        if not stored:
            await db.db.plans.insert_one(dict(plan))
            continue
        missing = {k: v for k, v in plan.items() if k not in stored}
        if missing:
            await db.db.plans.update_one({"_id": plan["_id"]}, {"$set": missing})


async def get_plan(plan_id: str) -> Optional[Dict[str, Any]]:
    found = await db.db.plans.find_one({"_id": plan_id})
    if found:
        return found
    # A database that was never seeded (tests, a fresh volume before startup
    # finished) still has the defaults to go by.
    return next((dict(p) for p in DEFAULT_PLANS if p["_id"] == plan_id), None)


async def list_plans() -> List[Dict[str, Any]]:
    return [await get_plan(p["_id"]) for p in DEFAULT_PLANS]


def carry_cap(plan: Dict[str, Any], resource: str) -> int:
    """How much of `resource` a finished month may pass on to the next."""
    if resource == "videos":
        return int(plan.get("carryover_cap", (plan.get("limits") or {}).get("videos")) or 0)
    return int((plan.get("carryover_caps") or {}).get(resource) or 0)


def fair_use_ceiling(plan: Optional[Dict[str, Any]], resource: str) -> Optional[int]:
    """The quiet ceiling on an unlimited resource, or None if there is none."""
    value = ((plan or {}).get("fair_use") or {}).get(resource)
    return int(value) if value is not None else None


def _period_carry(period: Dict[str, Any], resource: str) -> int:
    if resource == "videos":
        return int(period.get("carryover", 0) or 0)
    return int((period.get("carried") or {}).get(resource, 0) or 0)


def _unused_carry(plan: Dict[str, Any], period: Dict[str, Any]) -> Dict[str, int]:
    """What this period would pass on if it ended now, per resource, capped."""
    limits = plan.get("limits") or {}
    out: Dict[str, int] = {}
    for resource in CARRY_RESOURCES:
        limit = limits.get(resource)
        if limit is None:
            continue
        unused = limit + _period_carry(period, resource) - int((period.get("used") or {}).get(resource, 0))
        out[resource] = max(0, min(carry_cap(plan, resource), unused))
    return out


def clamp_effort(requested: str, plan: Optional[Dict[str, Any]]) -> str:
    """The requested quality, but no higher than the plan allows."""
    ceiling = (plan or {}).get("max_effort") or EFFORT_LEVELS[-1]
    if requested in EFFORT_LEVELS and ceiling in EFFORT_LEVELS:
        return EFFORT_LEVELS[min(EFFORT_LEVELS.index(requested), EFFORT_LEVELS.index(ceiling))]
    return requested


# ----------------------------------------------------------------- trial --


def phone_claim_hash(phone: str) -> str:
    secret = config.PHONE_HASH_SECRET or hashlib.sha256(
        f"{config.AGENT_SECRET}:phone-claims".encode()).hexdigest()
    return hmac.new(secret.encode(), phone.encode(), hashlib.sha256).hexdigest()


async def trial_blocked_reason(user: Dict[str, Any]) -> Optional[str]:
    """Why this account has no trial yet, or None if it has one or can get one."""
    if user.get("trial"):
        return None
    if (user.get("role") or USER_ROLE_DEFAULT) != "teacher":
        return "teacher_only"
    if not (user.get("phone") and user.get("phone_verified_at")):
        return "phone_required"
    claim = await db.db.trial_claims.find_one({"phone_hash": phone_claim_hash(user["phone"])})
    if claim and claim.get("user_id") != str(user["_id"]):
        return "phone_used"
    return None


async def ensure_trial(user: Dict[str, Any]) -> Dict[str, Any]:
    """Start the trial the first time a teacher with a confirmed phone needs it."""
    if user.get("trial") or await trial_blocked_reason(user):
        return user
    phone_hash = phone_claim_hash(user["phone"])
    user_id = str(user["_id"])
    now = _now()
    if not await db.db.trial_claims.find_one({"phone_hash": phone_hash}):
        try:
            await db.db.trial_claims.insert_one({"phone_hash": phone_hash, "user_id": user_id, "at": now})
        except Exception:  # noqa: BLE001 - lost a race for the same number
            return user
    # Invited by a colleague: two more videos on the trial.
    bonus = {"videos": 2} if user.get("referred_by") else {}
    trial = {"activated_at": now, "used": {}, "bonus": bonus}
    result = await db.db.users.update_one(
        {"_id": user["_id"], "trial": {"$exists": False}}, {"$set": {"trial": trial}})
    if result.modified_count:
        return {**user, "trial": trial}
    return await db.db.users.find_one({"_id": user["_id"]}) or user


# ---------------------------------------------------------- subscription --


def _sub_active(sub: Optional[Dict[str, Any]], now: datetime) -> bool:
    expires = _aware((sub or {}).get("expires_at"))
    return bool(sub and sub.get("status") == "active" and expires and expires > now)


def _period_bounds(anchor: datetime, now: datetime) -> tuple:
    months = (now.year - anchor.year) * 12 + (now.month - anchor.month)
    start = add_months(anchor, months)
    if start > now:
        months -= 1
        start = add_months(anchor, months)
    return months, start, add_months(anchor, months + 1)


async def _roll_period(user: Dict[str, Any], plan: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Make sure `period` is the current month of the subscription.

    The carry-over is worked out here, when a period ends: the videos and
    БЖБ/ТЖБ the finished period left unused, each up to the plan's cap for
    it. Months nobody touched still leave the previous month's allowance
    unused, so a returning teacher gets the cap too.
    """
    sub = user["subscription"]
    anchor = _aware(sub["anchor"])
    index, start, end = _period_bounds(anchor, now)
    key = start.isoformat()
    period = user.get("period") or {}
    if period.get("key") == key:
        return user

    carried: Dict[str, int] = {}
    if period.get("key"):
        previous_key = add_months(anchor, index - 1).isoformat() if index >= 1 else None
        if period.get("key") == previous_key:
            carried = _unused_carry(plan, period)
        elif index >= 1:
            limits = plan.get("limits") or {}
            carried = {r: min(carry_cap(plan, r), limits[r])
                       for r in CARRY_RESOURCES if limits.get(r) is not None}
    carry = carried.pop("videos", 0)
    new = {"key": key, "start": start, "end": end, "used": {}, "carryover": carry,
           "carried": {r: n for r, n in carried.items() if n}}
    result = await db.db.users.update_one(
        {"_id": user["_id"], "period.key": period.get("key")}, {"$set": {"period": new}})
    if result.modified_count:
        return {**user, "period": new}
    return await db.db.users.find_one({"_id": user["_id"]}) or user


async def _resume_if_due(user: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    sub = user.get("subscription") or {}
    if sub.get("status") == "paused" and _aware(sub.get("pause_until")) and _aware(sub["pause_until"]) <= now:
        return await resume(user, now=_aware(sub["pause_until"]))
    return user


# ---------------------------------------------------------- entitlement --


@dataclass
class Entitlement:
    kind: str = FREE
    plan_id: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    limits: Dict[str, Optional[int]] = field(default_factory=dict)
    used: Dict[str, int] = field(default_factory=dict)
    carryover: int = 0
    extra_videos: int = 0
    user: Dict[str, Any] = field(default_factory=dict)
    # Carried from last month, for everything but videos (those are `carryover`).
    carried: Dict[str, int] = field(default_factory=dict)

    def carry(self, resource: str) -> int:
        return self.carryover if resource == "videos" else int(self.carried.get(resource, 0))

    def available(self, resource: str) -> Optional[int]:
        """How many more may be made; None for unlimited."""
        if self.kind == FREE:
            return 0
        limit = self.limits.get(resource)
        if limit is None:
            return None
        allowance = (limit or 0) + self.carry(resource)
        left = max(0, allowance - self.used.get(resource, 0))
        if resource == "videos":
            left += self.extra_videos
        return left

    @property
    def watermark(self) -> Optional[str]:
        return WATERMARK_TEXT if (self.plan or {}).get("watermark") else None


async def resolve(user: Dict[str, Any], now: Optional[datetime] = None,
                  activate: bool = True) -> Entitlement:
    """What this account is on right now, with the trial started and the period
    rolled over if either was due. `activate=False` only looks: the admin
    panel must not start somebody's trial by opening their card."""
    now = now or _now()
    user = await _resume_if_due(user, now)
    sub = user.get("subscription")
    extra = int(user.get("extra_videos", 0) or 0)

    if _sub_active(sub, now):
        plan = await get_plan(sub["plan_id"]) or {}
        user = await _roll_period(user, plan, now)
        period = user.get("period") or {}
        return Entitlement(
            kind=ON_USTAZ, plan_id=sub["plan_id"], plan=plan,
            limits=dict(plan.get("limits") or {}), used=dict(period.get("used") or {}),
            carryover=int(period.get("carryover", 0)), extra_videos=extra, user=user,
            carried={r: int(n) for r, n in (period.get("carried") or {}).items()},
        )

    if activate:
        user = await ensure_trial(user)
    if user.get("trial"):
        plan = await get_plan(TRIAL) or {}
        limits = dict(plan.get("limits") or {})
        bonus = (user["trial"].get("bonus") or {})
        for resource, more in bonus.items():
            if limits.get(resource) is not None:
                limits[resource] = limits[resource] + int(more)
        return Entitlement(kind=ON_TRIAL, plan_id=TRIAL, plan=plan, limits=limits,
                           used=dict(user["trial"].get("used") or {}), user=user)

    return Entitlement(kind=FREE, user=user)


# --------------------------------------------------------- reservations --


async def _take(user_id: ObjectId, path: str, limit: Optional[int], extra_filter: Dict[str, Any]) -> bool:
    query: Dict[str, Any] = {"_id": user_id, **extra_filter}
    if limit is not None:
        if limit <= 0:
            return False
        query["$or"] = [{path: {"$exists": False}}, {path: {"$lt": limit}}]
    result = await db.db.users.update_one(query, {"$inc": {path: 1}})
    return result.modified_count == 1


async def reserve(user: Dict[str, Any], resource: str, ref: str) -> Entitlement:
    """Take one unit of `resource` for the work `ref` names, or raise PlanRefusal.

    Returns the entitlement it was taken under: the caller needs it for what
    the plan decides beyond the count - the watermark, the quality ceiling.
    """
    ent = await resolve(user)
    if ent.kind == FREE:
        raise PlanRefusal("plan_required", resource)

    user_id = ent.user["_id"]
    limit = ent.limits.get(resource)
    taken: Optional[tuple] = None
    if ent.kind == ON_TRIAL:
        path = f"trial.used.{resource}"
        if await _take(user_id, path, limit, {"trial.activated_at": {"$exists": True}}):
            taken = (path, 1)
    else:
        path = f"period.used.{resource}"
        if limit is None:
            # Unlimited, as the page says - up to the fair-use ceiling, if any.
            allowance = fair_use_ceiling(ent.plan, resource)
        else:
            allowance = limit + ent.carry(resource)
        period_key = (ent.user.get("period") or {}).get("key")
        if await _take(user_id, path, allowance, {"period.key": period_key}):
            taken = (path, 1)
        elif resource == "videos":
            result = await db.db.users.update_one(
                {"_id": user_id, "extra_videos": {"$gt": 0}}, {"$inc": {"extra_videos": -1}})
            if result.modified_count:
                taken = ("extra_videos", -1)
    if not taken:
        code = "fair_use_reached" if ent.kind == ON_USTAZ and limit is None else "plan_exhausted"
        await _note_limit_hit(ent, resource, code)
        raise PlanRefusal(code, resource)

    now = _now()
    await db.db.plan_reservations.insert_one({
        "ref": ref, "user_id": str(user_id), "resource": resource,
        "path": taken[0], "delta": taken[1], "at": now, "expires_at": now + RESERVATION_KEEP,
    })
    return ent


LIMIT_HITS_KEEP = timedelta(days=180)


async def _note_limit_hit(ent: Entitlement, resource: str, code: str) -> None:
    """Somebody wanted more than the plan gives. Kept for the metrics page.

    Whether forty lesson plans a month is enough is answered by how many
    teachers run out, and how far into their month: running out on day 28
    is a plan that fits, on day 12 one that does not.
    """
    now = _now()
    hit: Dict[str, Any] = {
        "user_id": str(ent.user["_id"]), "resource": resource, "code": code,
        "kind": ent.kind, "plan_id": ent.plan_id, "at": now, "expires_at": now + LIMIT_HITS_KEEP,
    }
    start = _aware((ent.user.get("period") or {}).get("start"))
    if ent.kind == ON_USTAZ and start:
        hit["period_day"] = (now - start).days + 1
    try:
        await db.db.plan_limit_hits.insert_one(hit)
    except Exception as e:  # noqa: BLE001 - counting must never get in the way of the answer
        print(f"plan limit hit not recorded: {type(e).__name__}: {e}")


async def release(ref: str) -> bool:
    """Give back what `ref` took, once. Safe to call for refs that took nothing."""
    found = await db.db.plan_reservations.find_one_and_delete({"ref": ref})
    if not found:
        return False
    await db.db.users.update_one(
        {"_id": ObjectId(found["user_id"])}, {"$inc": {found["path"]: -int(found["delta"])}})
    return True


async def commit(ref: str) -> None:
    """The work happened: the unit stays spent."""
    await db.db.plan_reservations.delete_one({"ref": ref})


# ------------------------------------------------- granting and changing --


async def grant(user: Dict[str, Any], plan_id: str, *, months: Optional[int] = None,
                until: Optional[datetime] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Start or extend a subscription. Used by the admin panel, and by payments.

    The same plan, still running: the end date moves out. Another plan while
    one is running is a switch, see below. Nothing running: a new one starts
    now, with a fresh period and nothing carried over.
    """
    now = now or _now()
    plan = await get_plan(plan_id)
    if not plan or plan.get("kind") != "subscription":
        raise ValueError(f"not a subscription plan: {plan_id}")
    sub = user.get("subscription") or {}
    running = _sub_active(sub, now) and sub.get("plan_id") == plan_id

    if _sub_active(sub, now) and not running:
        # A switch between month and school year. It used to start the new
        # plan from scratch: a school-year teacher who paid for a month was cut
        # back to one month from today, and every switch handed out a fresh
        # month of videos. Now the days already paid for stay, and so does
        # the month in progress - its count, its carry-over, its anchor.
        expires = _aware(sub["expires_at"])
        if until:
            new_expires = max(until, expires)
        elif plan.get("period") == "school_year":
            new_expires = max(school_year_end(now), expires)
        else:
            new_expires = add_months(expires, months or 1)
        await db.db.users.update_one({"_id": user["_id"]}, {"$set": {
            "subscription.plan_id": plan_id, "subscription.expires_at": new_expires}})
        return await db.db.users.find_one({"_id": user["_id"]})

    if running:
        expires = _aware(sub["expires_at"])
        if until:
            new_expires = max(until, expires)
        elif plan.get("period") == "school_year":
            new_expires = school_year_end(expires)
            if new_expires <= expires:
                new_expires = school_year_end(expires + timedelta(days=1))
        else:
            new_expires = add_months(expires, months or 1)
        await db.db.users.update_one({"_id": user["_id"]}, {"$set": {"subscription.expires_at": new_expires}})
        return await db.db.users.find_one({"_id": user["_id"]})

    if until:
        expires = until
    elif plan.get("period") == "school_year":
        expires = school_year_end(now)
    else:
        expires = add_months(now, months or 1)
    subscription = {
        "plan_id": plan_id, "status": "active", "started_at": now, "anchor": now,
        "expires_at": expires,
    }
    period = {"key": now.isoformat(), "start": now, "end": add_months(now, 1), "used": {}, "carryover": 0}
    await db.db.users.update_one({"_id": user["_id"]}, {"$set": {"subscription": subscription, "period": period}})
    return await db.db.users.find_one({"_id": user["_id"]})


async def extend_by_months(user: Dict[str, Any], months: int, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Add months to whatever Ұстаз is running, or start a month if none is.

    Unlike grant(), this never switches plans: a school-year subscriber who
    earns a month keeps the school-year plan, a month longer.
    """
    now = now or _now()
    sub = user.get("subscription") or {}
    if _sub_active(sub, now):
        new_expires = add_months(_aware(sub["expires_at"]), months)
        await db.db.users.update_one({"_id": user["_id"]}, {"$set": {"subscription.expires_at": new_expires}})
        return await db.db.users.find_one({"_id": user["_id"]})
    return await grant(user, USTAZ_MONTH, months=months, now=now)


async def end_subscription(user: Dict[str, Any]) -> None:
    await db.db.users.update_one(
        {"_id": user["_id"], "subscription": {"$exists": True}},
        {"$set": {"subscription.expires_at": _now(), "subscription.status": "active"}})


async def add_extra_videos(user: Dict[str, Any], count: int) -> None:
    await db.db.users.update_one({"_id": user["_id"]}, {"$inc": {"extra_videos": int(count)}})


async def reset_trial(user: Dict[str, Any]) -> None:
    """A fresh trial on the next request: the claim on the number goes too."""
    await db.db.trial_claims.delete_many({"user_id": str(user["_id"])})
    if user.get("phone"):
        await db.db.trial_claims.delete_many({"phone_hash": phone_claim_hash(user["phone"])})
    await db.db.users.update_one({"_id": user["_id"]}, {"$unset": {"trial": ""}})


async def pause(user: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Freeze a monthly subscription until September instead of cancelling it.

    June is when people cancel. The paid days left are kept and restart on
    1 September; nothing is generated in between, so nothing is charged for.
    """
    now = now or _now()
    sub = user.get("subscription") or {}
    plan = await get_plan(sub.get("plan_id", "")) or {}
    if not _sub_active(sub, now):
        raise PlanRefusal("no_subscription", "")
    if plan.get("period") != "month":
        raise PlanRefusal("pause_month_only", "")
    if not pause_allowed_now(now):
        raise PlanRefusal("pause_summer_only", "")
    period = user.get("period") or {}
    carried = _unused_carry(plan, period)
    carry = carried.pop("videos", 0)
    remaining = int((_aware(sub["expires_at"]) - now).total_seconds())
    await db.db.users.update_one({"_id": user["_id"]}, {"$set": {
        "subscription.status": "paused", "subscription.paused_at": now,
        "subscription.pause_until": next_september(now),
        "subscription.remaining_sec": remaining, "subscription.carry_on_resume": carry,
        "subscription.carried_on_resume": {r: n for r, n in carried.items() if n},
    }})
    return await db.db.users.find_one({"_id": user["_id"]})


async def resume(user: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = (now or _now()).replace(microsecond=0)
    sub = user.get("subscription") or {}
    if sub.get("status") != "paused":
        return user
    expires = now + timedelta(seconds=int(sub.get("remaining_sec", 0)))
    period = {"key": now.isoformat(), "start": now, "end": add_months(now, 1), "used": {},
              "carryover": int(sub.get("carry_on_resume", 0)),
              "carried": dict(sub.get("carried_on_resume") or {})}
    result = await db.db.users.update_one(
        {"_id": user["_id"], "subscription.status": "paused"},
        {"$set": {"subscription.status": "active", "subscription.expires_at": expires,
                  "subscription.anchor": now, "period": period},
         "$unset": {"subscription.paused_at": "", "subscription.pause_until": "",
                    "subscription.remaining_sec": "", "subscription.carry_on_resume": "",
                    "subscription.carried_on_resume": ""}})
    if result.modified_count:
        return await db.db.users.find_one({"_id": user["_id"]})
    return await db.db.users.find_one({"_id": user["_id"]}) or user


# --------------------------------------------------------------- summary --


def _iso(value: Any) -> Optional[str]:
    moment = _aware(value)
    return moment.isoformat() if moment else None


def _fair_use_shown(ent: Entitlement) -> Dict[str, int]:
    """The ceilings on what the page calls unlimited, for the page to name."""
    shown: Dict[str, int] = {}
    if ent.kind != ON_USTAZ:
        return shown
    for resource in RESOURCES:
        ceiling = fair_use_ceiling(ent.plan, resource)
        if ent.limits.get(resource) is None and ceiling is not None:
            shown[resource] = ceiling
    return shown


async def summary(user: Dict[str, Any], activate: bool = True) -> Dict[str, Any]:
    """Everything the plan page shows, for this account."""
    now = _now()
    ent = await resolve(user, now, activate=activate)
    user = ent.user
    sub = user.get("subscription") or {}
    period = user.get("period") or {}
    out: Dict[str, Any] = {
        "kind": ent.kind,
        "plan_id": ent.plan_id,
        "title": (ent.plan or {}).get("title"),
        "limits": ent.limits,
        "used": {r: int(ent.used.get(r, 0)) for r in RESOURCES},
        "available": {r: ent.available(r) for r in RESOURCES},
        "carryover": ent.carryover,
        "carried": {r: ent.carry(r) for r in CARRY_RESOURCES if r != "videos"},
        "fair_use": _fair_use_shown(ent),
        "extra_videos": ent.extra_videos,
        "watermark": bool(ent.watermark),
        "max_effort": (ent.plan or {}).get("max_effort"),
        "docx_signature": ent.kind != ON_USTAZ,
        "trial_unavailable": await trial_blocked_reason(user) if ent.kind == FREE else None,
        "trial_used_up": ent.kind == FREE and bool(user.get("trial")),
        "subscription": None,
    }
    if sub:
        plan = await get_plan(sub.get("plan_id", "")) or {}
        started = _aware(sub.get("started_at"))
        if _sub_active(sub, now):
            status = "active"
        elif sub.get("status") == "paused":
            status = "paused"
        else:
            status = "expired"
        out["subscription"] = {
            "plan_id": sub.get("plan_id"),
            "title": plan.get("title"),
            "status": status,
            "expires_at": _iso(sub.get("expires_at")),
            "period_end": _iso(period.get("end")) if ent.kind == ON_USTAZ else None,
            "pause_until": _iso(sub.get("pause_until")),
            "can_pause": _sub_active(sub, now) and plan.get("period") == "month" and pause_allowed_now(now),
            # A month in, the school year is the better deal; say so once.
            "suggest_year": _sub_active(sub, now) and plan.get("period") == "month"
            and bool(started) and now - started >= timedelta(days=25),
        }
    return out


# -------------------------------------------------------------- reminder --


async def send_reminders(now: Optional[datetime] = None) -> int:
    """Email everyone whose subscription ends within PLAN_REMINDER_DAYS, once.

    A surprise charge is a message in the teachers' chat warning everyone
    off; a reminder costs nothing. There is no automatic charge yet - payment
    is by hand - so the email says the subscription ends, not that it renews.
    """
    from app.services import mailer

    now = now or _now()
    horizon = now + timedelta(days=config.PLAN_REMINDER_DAYS)
    sent = 0
    cursor = db.db.users.find({
        "subscription.status": "active",
        "subscription.expires_at": {"$gt": now, "$lte": horizon},
    })
    async for user in cursor:
        sub = user["subscription"]
        if sub.get("reminded_for") == _iso(sub.get("expires_at")) or not user.get("email"):
            continue
        local_end = _local(_aware(sub["expires_at"])).strftime("%d.%m.%Y")
        subject = "Akron: Ұстаз жазылымы аяқталуға жақын / подписка заканчивается"
        text = (
            f"Ұстаз жазылымыңыз {local_end} аяқталады. Жалғастыру үшін Akron-дағы «Тариф» бетін ашыңыз.\n\n"
            f"Ваша подписка Ұстаз заканчивается {local_end}. Продлить её можно на странице «Тариф» в Akron.\n\n"
            f"{config.PUBLIC_BASE_URL}/app/billing"
        )
        if await mailer.send(user["email"], subject, text):
            await db.db.users.update_one(
                {"_id": user["_id"]}, {"$set": {"subscription.reminded_for": _iso(sub["expires_at"])}})
            sent += 1
    return sent


async def reminder_loop() -> None:
    import asyncio

    while True:
        try:
            await send_reminders()
        except Exception as e:  # noqa: BLE001 - a reminder never takes the backend down
            print(f"plan reminders failed: {type(e).__name__}: {e}")
        await asyncio.sleep(3600)
