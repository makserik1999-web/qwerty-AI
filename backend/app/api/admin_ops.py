"""Running the service: generation tasks, metrics, and the system's health.

Tasks and health are for any staff role - support is there to answer "my
video never came", and that starts here. Metrics include money, so they are
the admin's, like the payments page.

Restarting a failed task makes it again for the same teacher, on the teacher's
own plan: a failure was given back, so the restart takes it again, and a plan
with nothing left refuses the restart the way it would refuse the teacher.
Only videos and lesson plans can be restarted - the two that land somewhere
the teacher will find them. A quiz draft was for a page that has since moved
on, and a paper the teacher asks for again in seconds.
"""

import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import AZURE_TTS_FREE_CHARS, MEDIA_DIR, STATS_UTC_OFFSET_HOURS
from app.db import db
from app.errors import HTTPExceptionJson
from app.repositories import audit
from app.security.staff import require_admin, require_staff
from app.services import jobs, payments, plans
from app.ws.manager import agent_manager

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_staff)])

_STARTED = time.time()

# When the system page starts saying something is wrong.
HEARTBEAT_STALE_SEC = 120
DISK_LOW_SHARE = 0.10
QUEUE_OLD_SEC = 15 * 60
FAILURES_MANY = 5


class Restart(BaseModel):
    reason: Optional[str] = ""


def _iso_ts(seconds: Optional[float]) -> Optional[str]:
    if not seconds:
        return None
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


# ------------------------------------------------------------------- tasks --


@router.get("/jobs")
async def list_jobs(status: str = "", kind: str = "", silent: bool = False, page: int = 1):
    return await jobs.listing(status=status, kind=kind, silent=silent, page=page)


@router.post("/jobs/{job_id}/restart")
async def restart_job(job_id: str, body: Restart, actor=Depends(require_staff)):
    job = await jobs.get(job_id)
    if not job:
        raise HTTPExceptionJson(404, "Not found")
    if not jobs.restartable(job):
        raise HTTPExceptionJson(409, "Only a failed video or lesson plan, once", code="not_restartable")

    # Claimed first, so two people pressing the button make one restart.
    claimed = await db.db.generation_jobs.find_one_and_update(
        {"_id": job["_id"], "status": "failed", "restarted_as": {"$exists": False}},
        {"$set": {"restarted_as": "pending"}})
    if not claimed:
        raise HTTPExceptionJson(409, "Already restarted", code="not_restartable")
    try:
        user = await _owner(job)
        if job["kind"] == "video":
            new_id = await _restart_video(job, user)
        else:
            new_id = await _restart_lesson_plan(job, user)
    except BaseException:
        await db.db.generation_jobs.update_one({"_id": job["_id"]}, {"$unset": {"restarted_as": ""}})
        raise
    await db.db.generation_jobs.update_one({"_id": job["_id"]}, {"$set": {"restarted_as": new_id}})
    await audit.record(actor=audit.staff_actor(actor), action="job.restart",
                       target={"job_id": job_id, "kind": job["kind"], "user_id": job.get("user_id")},
                       details={"new_job_id": new_id}, reason=(body.reason or "")[:300])
    return {"ok": True, "job_id": new_id}


async def _owner(job: Dict[str, Any]) -> Dict[str, Any]:
    user_id = job.get("user_id") or ""
    user = await db.db.users.find_one({"_id": ObjectId(user_id)}) if ObjectId.is_valid(user_id) else None
    if not user or user.get("blocked_at") or user.get("role") != "teacher":
        raise HTTPExceptionJson(409, "The account is gone, blocked or not a teacher", code="owner_unavailable")
    return user


def _refused(exc: plans.PlanRefusal) -> HTTPExceptionJson:
    return HTTPExceptionJson(409, "The teacher's plan has nothing left for this", code=exc.code)


async def _restart_video(job: Dict[str, Any], user: Dict[str, Any]) -> str:
    spec = job.get("spec") or {}
    user_id = str(user["_id"])
    chat_id = str(spec.get("chat_id") or "")
    if not ObjectId.is_valid(chat_id) or not await db.db.chats.find_one(
            {"_id": ObjectId(chat_id), "user_id": user_id}, {"_id": 1}):
        raise HTTPExceptionJson(409, "The teacher deleted that chat", code="chat_gone")
    if not agent_manager.agent_connection:
        raise HTTPExceptionJson(503, "The agent is not connected", code="agent_unavailable")

    screenshots: List[Dict[str, Any]] = []
    if spec.get("screenshots"):
        message_id = str(spec.get("user_message_id") or "")
        message = (await db.db.messages.find_one({"_id": ObjectId(message_id)})
                   if ObjectId.is_valid(message_id) else None)
        screenshots = (message or {}).get("screenshots") or []
        if not screenshots:
            raise HTTPExceptionJson(409, "The question's pictures are gone", code="chat_gone")

    request_id = str(uuid.uuid4())
    try:
        entitlement = await plans.reserve(user, "videos", request_id)
    except plans.PlanRefusal as exc:
        raise _refused(exc) from None
    effort = str(spec.get("effort") or "")
    if entitlement.plan:
        effort = plans.clamp_effort(effort, entitlement.plan)
    prompt = str(spec.get("prompt") or "")

    agent_manager.pending_requests[request_id] = {
        "user_id": user_id,
        "chat_id": chat_id,
        "created_at": time.monotonic(),
        "prompt": prompt,
        "screenshots": screenshots,
        "variant": spec.get("variant", ""),
        "watermark": entitlement.watermark,
        "classification": spec.get("classification"),
        "output_language": str(spec.get("output_language") or ""),
        "orientation": str(spec.get("orientation") or ""),
    }
    new_id = await jobs.start("video", user_id, request_id, narration=bool(spec.get("narration")),
                              spec=spec, restart_of=str(job["_id"]))
    try:
        await agent_manager.send_to_agent(
            request_id=request_id, user_id=user_id, chat_id=chat_id, text=prompt,
            screenshots=screenshots, narration=bool(spec.get("narration")),
            narration_voice=str(spec.get("voice") or "aigul"),
            video_length=str(spec.get("video_length") or ""), effort=effort,
            watermark=entitlement.watermark,
            output_language=str(spec.get("output_language") or ""),
            orientation=str(spec.get("orientation") or ""),
        )
    except Exception:
        agent_manager.pending_requests.pop(request_id, None)
        await plans.release(request_id)
        await jobs.finish(request_id, ok=False, error_type="delivery")
        raise HTTPExceptionJson(503, "The request did not reach the agent", code="agent_unavailable") from None
    return new_id or ""


async def _restart_lesson_plan(job: Dict[str, Any], user: Dict[str, Any]) -> str:
    # Imported here: the endpoint module imports the agent manager and the
    # plans, and this one is imported by main beside it.
    from app.api.lesson_plans import produce

    spec = job.get("spec") or {}
    user_id = str(user["_id"])
    ref = f"lesson_plan:{uuid.uuid4().hex}"
    try:
        await plans.reserve(user, "lesson_plans", ref)
    except plans.PlanRefusal as exc:
        raise _refused(exc) from None
    new_id = await jobs.start("lesson_plan", user_id, ref, spec=spec, restart_of=str(job["_id"]))
    jobs.spawn(produce(user_id, spec, ref))
    return new_id or ""


# ------------------------------------------------------------------ health --


@router.get("/system")
async def system():
    now = time.time()
    heartbeat = dict(agent_manager.heartbeat or {})
    connected = bool(agent_manager.agent_connection)

    pending = list(agent_manager.pending_requests.values())
    oldest = max((time.monotonic() - p.get("created_at", time.monotonic()) for p in pending), default=0)

    try:
        usage = shutil.disk_usage(MEDIA_DIR)
        disk = {"free": usage.free, "total": usage.total,
                "free_share": round(usage.free / usage.total, 3) if usage.total else None}
    except OSError:
        disk = {"free": None, "total": None, "free_share": None}

    database: Dict[str, Any] = {"ok": False}
    try:
        await db.db.command("ping")
        database["ok"] = True
        stats = await db.db.command("dbStats")
        database.update({"data_bytes": int(stats.get("dataSize", 0)),
                         "storage_bytes": int(stats.get("storageSize", 0))})
    except Exception:  # noqa: BLE001 - a missing privilege is not an outage
        pass

    counts = await jobs.counts()
    exports_waiting = await db.db.export_jobs.count_documents({"status": {"$in": ["queued", "running"]}})

    warnings: List[str] = []
    if not connected:
        warnings.append("agent_offline")
    elif heartbeat.get("at") and now - heartbeat["at"] > HEARTBEAT_STALE_SEC:
        warnings.append("heartbeat_stale")
    if disk["free_share"] is not None and disk["free_share"] < DISK_LOW_SHARE:
        warnings.append("disk_low")
    if oldest > QUEUE_OLD_SEC:
        warnings.append("queue_old")
    if counts["failed_24h"] >= FAILURES_MANY:
        warnings.append("failures_many")
    if not database["ok"]:
        warnings.append("database")

    return {
        "agent": {
            "connected": connected,
            "connected_at": _iso_ts(agent_manager.connected_at),
            "last_seen": _iso_ts(agent_manager.last_seen),
            "features": sorted(agent_manager.agent_features),
            "heartbeat": {**heartbeat, "at": _iso_ts(heartbeat.get("at"))} if heartbeat else None,
        },
        "queue": {
            "videos": len(pending),
            "documents": len(agent_manager.pending_documents),
            "oldest_sec": round(oldest),
            "exports": exports_waiting,
        },
        "jobs": counts,
        "disk": disk,
        "database": database,
        "backend": {"uptime_sec": round(now - _STARTED)},
        "warnings": warnings,
    }


# ----------------------------------------------------------------- metrics --


def _local_day(moment: Any) -> Optional[str]:
    if not isinstance(moment, datetime):
        return None
    moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return (moment + timedelta(hours=STATS_UTC_OFFSET_HOURS)).strftime("%Y-%m-%d")


async def _funnel(since: datetime) -> Dict[str, int]:
    """Teachers who signed up in the window, and how far each of them got."""
    trial = await plans.get_plan(plans.TRIAL) or {}
    limits = trial.get("limits") or {}
    paid_ids = set(await db.db.payments.distinct("user_id", {"status": payments.CONFIRMED}))

    steps = {"registered": 0, "phone_confirmed": 0, "trial_started": 0,
             "trial_used": 0, "trial_spent": 0, "paid": 0}
    projection = {"phone_verified_at": 1, "trial": 1}
    async for user in db.db.users.find({"role": "teacher", "created_at": {"$gte": since}}, projection):
        steps["registered"] += 1
        if user.get("phone_verified_at"):
            steps["phone_confirmed"] += 1
        started = user.get("trial") or {}
        if started.get("activated_at"):
            steps["trial_started"] += 1
            used = started.get("used") or {}
            if any(int(v or 0) > 0 for v in used.values()):
                steps["trial_used"] += 1
            bonus = started.get("bonus") or {}
            # Spent: everything of one kind the trial is about - its videos or its papers.
            spent = any(
                limits.get(kind) is not None
                and int(used.get(kind) or 0) >= int(limits[kind]) + int(bonus.get(kind) or 0)
                for kind in ("videos", "assessments")
            )
            if spent:
                steps["trial_spent"] += 1
        if str(user["_id"]) in paid_ids:
            steps["paid"] += 1
    return steps


async def _active_teachers(now: datetime) -> Dict[str, int]:
    found: Dict[str, int] = {}
    for label, days in (("day", 1), ("week", 7), ("month", 30)):
        ids = await db.db.usage_log.distinct("user_id", {"at": {"$gte": now - timedelta(days=days)}})
        object_ids = [ObjectId(i) for i in ids if ObjectId.is_valid(i)]
        found[label] = await db.db.users.count_documents({"_id": {"$in": object_ids}, "role": "teacher"})
    return found


async def _renders(since: datetime) -> List[Dict[str, Any]]:
    days: Dict[str, Dict[str, Any]] = {}
    projection = {"created_at": 1, "status": 1, "video": 1, "has_audio": 1, "narration": 1, "render_sec": 1}
    async for job in db.db.generation_jobs.find({"kind": "video", "created_at": {"$gte": since}}, projection):
        key = _local_day(job.get("created_at"))
        if not key:
            continue
        day = days.setdefault(key, {"date": key, "videos": 0, "failed": 0, "silent": 0, "_secs": []})
        if job.get("status") == "failed":
            day["failed"] += 1
        elif job.get("status") == "done" and job.get("video"):
            day["videos"] += 1
            if job.get("narration") and job.get("has_audio") is False:
                day["silent"] += 1
            if isinstance(job.get("render_sec"), (int, float)):
                day["_secs"].append(job["render_sec"])
    rows = []
    for key in sorted(days):
        day = days[key]
        secs = day.pop("_secs")
        day["avg_render_sec"] = round(sum(secs) / len(secs)) if secs else None
        rows.append(day)
    return rows


async def _failure_types(since: datetime) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    async for job in db.db.generation_jobs.find(
            {"status": "failed", "created_at": {"$gte": since}}, {"error_type": 1}):
        key = job.get("error_type") or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return [{"error_type": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]


# Running out before this day of the subscription month means the plan is too
# small for that teacher, not that the month was busy.
EARLY_PERIOD_DAY = 15


async def _limit_hits(since: datetime) -> List[Dict[str, Any]]:
    """Who ran out of what: per resource, the refusals and the people behind them."""
    rows: Dict[str, Dict[str, Any]] = {}
    async for hit in db.db.plan_limit_hits.find({"at": {"$gte": since}}):
        resource = hit.get("resource") or "?"
        row = rows.setdefault(resource, {"resource": resource, "hits": 0, "_users": set(), "_trial": set(),
                                         "_ustaz": set(), "_early": set(), "_fair": set()})
        user = hit.get("user_id")
        row["hits"] += 1
        row["_users"].add(user)
        if hit.get("kind") == plans.ON_TRIAL:
            row["_trial"].add(user)
        elif hit.get("kind") == plans.ON_USTAZ:
            row["_ustaz"].add(user)
            if int(hit.get("period_day") or 99) < EARLY_PERIOD_DAY:
                row["_early"].add(user)
        if hit.get("code") == "fair_use_reached":
            row["_fair"].add(user)
    out = []
    for resource in [r for r in plans.RESOURCES if r in rows] + [r for r in rows if r not in plans.RESOURCES]:
        row = rows[resource]
        out.append({
            "resource": resource, "hits": row["hits"], "users": len(row["_users"]),
            "trial_users": len(row["_trial"]), "ustaz_users": len(row["_ustaz"]),
            "early_users": len(row["_early"]), "fair_use_users": len(row["_fair"]),
        })
    return out


async def _azure(now: datetime) -> Dict[str, Any]:
    """Characters sent to Azure this calendar month, against the free tier.

    Counted from what the agent reports per generation, so it misses only
    syntheses this log never saw - a render whose answer never came back.
    Azure's own portal is the authority; this is the early warning.
    """
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    chars = 0
    async for job in db.db.generation_jobs.find(
            {"kind": "video", "created_at": {"$gte": month_start}, "tts_chars": {"$gt": 0}}, {"tts_chars": 1}):
        chars += int(job.get("tts_chars") or 0)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    elapsed = max((now - month_start).total_seconds(), 3600)
    whole = (next_month - month_start).total_seconds()
    return {
        "month": month_start.strftime("%Y-%m"),
        "chars": chars,
        "limit": AZURE_TTS_FREE_CHARS,
        "projected": round(chars * whole / elapsed),
    }


@router.get("/metrics", dependencies=[Depends(require_admin)])
async def metrics(days: int = 30):
    days = max(7, min(90, days))
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    return {
        "days": days,
        "funnel": await _funnel(since),
        "active_teachers": await _active_teachers(now),
        "revenue": await payments.revenue_by_month(12),
        "renders": await _renders(since),
        "failures": await _failure_types(since),
        "limit_hits": await _limit_hits(since),
        "early_period_day": EARLY_PERIOD_DAY,
        "azure": await _azure(now),
        "utc_offset_hours": STATS_UTC_OFFSET_HOURS,
    }
